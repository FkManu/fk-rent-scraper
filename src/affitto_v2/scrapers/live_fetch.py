from __future__ import annotations

import asyncio
import json
import random
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

from ..db import ListingRecord
from ..models import CaptchaMode, ExtractionFields

_CAPTCHA_URL_KEYS = (
    "captcha-delivery.com",
    "/captcha",
    "/challenge",
    "datadome",
)

_CAPTCHA_TEXT_KEYS = (
    "dialogare con te e non con un robot",
    "accesso è stato bloccato",
    "accesso e stato bloccato",
    "verify you are a human",
    "sei un robot",
    "please verify you are human",
)

_CAPTCHA_HTML_STRONG_KEYS = (
    "geo.captcha-delivery.com/captcha/",
    "ct.captcha-delivery.com/c.js",
    "datadome captcha",
)

_CAPTCHA_WIDGET_SELECTORS = (
    "iframe[src*='captcha-delivery.com']",
    "iframe[title*='captcha']",
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "div.g-recaptcha",
    "div.h-captcha",
    "[class*='captcha-delivery']",
    "[id*='captcha'][class*='challenge']",
)
_LEGIT_EMPTY_TEXT_KEYS = (
    "nessun risultato",
    "nessun annuncio",
    "nessuna casa",
    "nessun immobile",
    "non abbiamo trovato",
    "0 risultati",
    "0 annunci",
    "salva la ricerca",
)
_SUSPICIOUS_EMPTY_TEXT_KEYS = (
    "access denied",
    "accesso bloccato",
    "too many requests",
    "temporarily unavailable",
    "verify you are a human",
    "just a moment",
    "enable javascript",
    "browser non supportato",
)
_SOFT_BLOCK_HTML_KEYS = (
    "captcha-delivery",
    "datadome",
    "cf-chl",
    "/captcha",
    "/challenge",
)
_HTTP_BLOCK_STATUSES = {403, 429}
_HTTP_NETWORK_STATUSES = {408, 425, 500, 502, 503, 504, 522, 524}

_HARD_BLOCK_PATTERNS = (
    re.compile(r"uso\s+improprio", re.IGNORECASE),
    re.compile(r"accesso.{0,40}bloccat", re.IGNORECASE),
    re.compile(r"difficolt[aà].{0,40}accedere", re.IGNORECASE),
    re.compile(r"contatta.{0,30}assistenza", re.IGNORECASE),
    re.compile(r"team\s+di\s+idealista", re.IGNORECASE),
)
_HARD_BLOCK_ID_RE = re.compile(r"\bID\s*:\s*([A-Za-z0-9-]{8,})\b", re.IGNORECASE)
_CHANNEL_LABELS = ("msedge", "chrome", "chromium")
_PREFERRED_AUTO_CHANNELS = ("msedge", "chrome")
_GUARD_STATE_VERSION = 2


@dataclass(slots=True)
class FetchOutcome:
    tier: str
    code: str
    http_status: int = 0
    listings: int = 0
    retryable: bool = False
    detail: str = ""
    challenge_visible: bool = False
    hard_block: bool = False
    suspicious_empty: bool = False
    parse_issue: bool = False
    network_issue: bool = False
    from_fallback: bool = False
    extraction_quality: str = ""


@dataclass(slots=True)
class GuardDecision:
    action: str
    cooldown_sec: int = 0
    transition: bool = False
    recovered: bool = False
    previous_tier: str = ""
    previous_code: str = ""


class LiveFetchBlocked(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class ExtractionMetrics:
    site: str
    cards_count: int
    missing_title_pct: int
    missing_price_pct: int
    missing_location_pct: int
    missing_agency_pct: int
    fallback_used: bool
    selector_primary_count: int = 0
    selector_alt_count: int = 0
    quality: str = "good"
    dominant_gap: str = ""


@dataclass(slots=True)
class DriftDiagnostic:
    triggered: bool
    severity: str = ""
    reason: str = ""
    detail: str = ""
    artifact_event: str = ""


def _normalize(value: str | None) -> str:
    return " ".join((value or "").split()).strip()


def _guess_location_from_title(title: str) -> str:
    text = _normalize(title)
    if not text:
        return ""
    comma_parts = [part.strip() for part in text.split(",") if part.strip()]
    if len(comma_parts) >= 2:
        return comma_parts[-1]
    m = re.search(r"\bin\s+(.+)$", text, flags=re.IGNORECASE)
    if m:
        return _normalize(m.group(1))
    return ""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc_iso(value: str | None) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _site_key_from_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "idealista.it" in host:
        return "idealista"
    if "immobiliare.it" in host:
        return "immobiliare"
    return host or "unknown"


def _channel_to_label(channel: str | None) -> str:
    return "chromium" if channel is None else channel


def _label_to_channel(label: str) -> str | None:
    return None if label == "chromium" else label


def _new_guard_site_entry() -> dict[str, object]:
    return {
        "strikes": 0,
        "cooldown_until_utc": "",
        "last_reason": "",
        "last_outcome_tier": "",
        "last_outcome_code": "",
        "last_outcome_detail": "",
        "last_attempt_utc": "",
        "last_success_utc": "",
        "last_recovery_utc": "",
        "last_valid_channel": "",
        "consecutive_successes": 0,
        "consecutive_failures": 0,
        "consecutive_suspect": 0,
        "consecutive_blocks": 0,
        "last_cards_count": 0,
        "last_quality": "",
        "last_fallback_used": False,
        "last_missing_title_pct": 0,
        "last_missing_price_pct": 0,
        "last_missing_location_pct": 0,
        "last_missing_agency_pct": 0,
    }


def _load_guard_state(path: Path) -> dict:
    default = {"version": _GUARD_STATE_VERSION, "last_channel": "chromium", "sites": {}}
    try:
        if not path.exists():
            return default
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return default
        sites = raw.get("sites", {})
        if not isinstance(sites, dict):
            sites = {}
        last_channel = str(raw.get("last_channel") or "chromium").strip().lower()
        if last_channel not in _CHANNEL_LABELS:
            last_channel = "chromium"
        return {
            "version": _GUARD_STATE_VERSION,
            "last_channel": last_channel,
            "sites": sites,
        }
    except Exception:
        return default


def _save_guard_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def _site_state(state: dict, site: str) -> dict:
    sites = state.setdefault("sites", {})
    entry = sites.get(site)
    if not isinstance(entry, dict):
        entry = _new_guard_site_entry()
    for key, value in _new_guard_site_entry().items():
        entry.setdefault(key, value)
    sites[site] = entry
    return entry


def _cooldown_remaining_sec(state: dict, site: str, now: datetime) -> int:
    entry = _site_state(state, site)
    until = _parse_utc_iso(str(entry.get("cooldown_until_utc") or ""))
    if until is None:
        return 0
    delta = int((until - now).total_seconds())
    return delta if delta > 0 else 0


def _count_hits(haystack: str, keys: tuple[str, ...]) -> int:
    text = (haystack or "").lower()
    return sum(1 for key in keys if key in text)


def _body_hint(text: str, limit: int = 180) -> str:
    clean = _normalize(text)
    return clean[:limit]


def _pct(part: int, total: int) -> int:
    if total <= 0:
        return 0
    return int(round((part / total) * 100))


def _build_extraction_metrics(
    *,
    site: str,
    cards: list[dict],
    fallback_used: bool,
    selector_primary_count: int = 0,
    selector_alt_count: int = 0,
) -> ExtractionMetrics:
    total = len(cards)
    if total <= 0:
        return ExtractionMetrics(
            site=site,
            cards_count=0,
            missing_title_pct=0,
            missing_price_pct=0,
            missing_location_pct=0,
            missing_agency_pct=0,
            fallback_used=fallback_used,
            selector_primary_count=selector_primary_count,
            selector_alt_count=selector_alt_count,
            quality="empty",
        )

    missing_title = sum(1 for card in cards if not _normalize(card.get("title")))
    missing_price = sum(1 for card in cards if not _normalize(card.get("price")))
    missing_location = sum(1 for card in cards if not _normalize(card.get("location")))
    missing_agency = sum(1 for card in cards if not _normalize(card.get("agency")))

    metrics = ExtractionMetrics(
        site=site,
        cards_count=total,
        missing_title_pct=_pct(missing_title, total),
        missing_price_pct=_pct(missing_price, total),
        missing_location_pct=_pct(missing_location, total),
        missing_agency_pct=_pct(missing_agency, total),
        fallback_used=fallback_used,
        selector_primary_count=selector_primary_count,
        selector_alt_count=selector_alt_count,
    )

    gap_pairs = [
        ("title", metrics.missing_title_pct),
        ("price", metrics.missing_price_pct),
        ("location", metrics.missing_location_pct),
        ("agency", metrics.missing_agency_pct),
    ]
    metrics.dominant_gap = max(gap_pairs, key=lambda item: item[1])[0]

    if fallback_used and total > 0:
        metrics.quality = "fallback_only"
    elif metrics.missing_title_pct >= 60 or metrics.missing_location_pct >= 85 or metrics.missing_agency_pct >= 90:
        metrics.quality = "poor"
    elif metrics.missing_title_pct >= 30 or metrics.missing_location_pct >= 60 or metrics.missing_agency_pct >= 70:
        metrics.quality = "partial"
    else:
        metrics.quality = "good"
    return metrics


def _detect_parser_drift(*, metrics: ExtractionMetrics, prior: dict | None, outcome: FetchOutcome) -> DriftDiagnostic:
    if metrics.cards_count <= 0:
        prev_cards = int((prior or {}).get("last_cards_count") or 0)
        prev_quality = str((prior or {}).get("last_quality") or "")
        if prev_cards >= 3 and prev_quality in {"good", "partial", "fallback_only"}:
            return DriftDiagnostic(
                triggered=True,
                severity="warn",
                reason="zero_after_previous_success",
                detail=f"previous_cards={prev_cards} previous_quality={prev_quality}",
                artifact_event="parser_zero_cards",
            )
        return DriftDiagnostic(triggered=False)

    prev_cards = int((prior or {}).get("last_cards_count") or 0)
    prev_quality = str((prior or {}).get("last_quality") or "")
    prev_title = int((prior or {}).get("last_missing_title_pct") or 0)
    prev_location = int((prior or {}).get("last_missing_location_pct") or 0)
    prev_agency = int((prior or {}).get("last_missing_agency_pct") or 0)

    if metrics.fallback_used and prev_quality in {"good", "partial"}:
        return DriftDiagnostic(
            triggered=True,
            severity="warn",
            reason="fallback_dominant",
            detail=f"cards={metrics.cards_count} dominant_gap={metrics.dominant_gap}",
            artifact_event="parser_fallback_drift",
        )
    if metrics.quality == "poor":
        return DriftDiagnostic(
            triggered=True,
            severity="warn",
            reason="high_missing_fields",
            detail=(
                f"title_missing={metrics.missing_title_pct}% "
                f"location_missing={metrics.missing_location_pct}% "
                f"agency_missing={metrics.missing_agency_pct}%"
            ),
            artifact_event="parser_high_missing",
        )
    if prev_cards >= 4 and metrics.cards_count == 1 and prev_quality == "good":
        return DriftDiagnostic(
            triggered=True,
            severity="info",
            reason="cards_drop",
            detail=f"previous_cards={prev_cards} now_cards={metrics.cards_count}",
            artifact_event="parser_cards_drop",
        )
    if metrics.missing_title_pct >= max(50, prev_title + 35):
        return DriftDiagnostic(
            triggered=True,
            severity="warn",
            reason="title_missing_spike",
            detail=f"previous={prev_title}% now={metrics.missing_title_pct}%",
            artifact_event="parser_title_spike",
        )
    if metrics.missing_location_pct >= max(75, prev_location + 35) or metrics.missing_agency_pct >= max(80, prev_agency + 35):
        return DriftDiagnostic(
            triggered=True,
            severity="info",
            reason="field_missing_spike",
            detail=(
                f"location_previous={prev_location}% now={metrics.missing_location_pct}% "
                f"agency_previous={prev_agency}% now={metrics.missing_agency_pct}%"
            ),
            artifact_event="parser_field_spike",
        )
    if outcome.code == "parse_issue":
        return DriftDiagnostic(
            triggered=True,
            severity="info",
            reason="parse_issue_detected",
            detail=outcome.detail,
            artifact_event="parser_parse_issue",
        )
    return DriftDiagnostic(triggered=False)


def _store_extraction_metrics(*, entry: dict, metrics: ExtractionMetrics) -> None:
    entry["last_cards_count"] = metrics.cards_count
    entry["last_quality"] = metrics.quality
    entry["last_fallback_used"] = metrics.fallback_used
    entry["last_missing_title_pct"] = metrics.missing_title_pct
    entry["last_missing_price_pct"] = metrics.missing_price_pct
    entry["last_missing_location_pct"] = metrics.missing_location_pct
    entry["last_missing_agency_pct"] = metrics.missing_agency_pct


def _log_extraction_metrics(*, logger, site: str, url: str, metrics: ExtractionMetrics, drift: DriftDiagnostic | None = None) -> None:
    level_log = logger.warning if metrics.quality in {"poor", "fallback_only"} or (drift and drift.triggered and drift.severity == "warn") else logger.info
    level_log(
        "Extraction quality. site=%s quality=%s cards=%s title_missing=%s%% price_missing=%s%% location_missing=%s%% agency_missing=%s%% fallback=%s url=%s",
        site,
        metrics.quality,
        metrics.cards_count,
        metrics.missing_title_pct,
        metrics.missing_price_pct,
        metrics.missing_location_pct,
        metrics.missing_agency_pct,
        metrics.fallback_used,
        url,
    )
    if drift and drift.triggered:
        drift_log = logger.warning if drift.severity == "warn" else logger.info
        drift_log(
            "Parser drift signal. site=%s reason=%s detail=%s url=%s",
            site,
            drift.reason,
            drift.detail,
            url,
        )


def _save_parser_diagnostic_artifact(
    *,
    debug_dir: Path | None,
    site: str,
    event: str,
    url: str,
    outcome: FetchOutcome,
    metrics: ExtractionMetrics,
    drift: DriftDiagnostic,
    logger,
) -> None:
    if debug_dir is None:
        return
    payload = {
        "site": site,
        "url": url,
        "outcome": asdict(outcome),
        "metrics": asdict(metrics),
        "drift": asdict(drift),
    }
    _save_guard_event_artifact(
        debug_dir=debug_dir,
        site=site,
        event=event,
        payload=payload,
        logger=logger,
    )


def _classify_runtime_exception(exc: Exception) -> FetchOutcome:
    detail = _normalize(str(exc))
    low = detail.lower()
    if isinstance(exc, PlaywrightTimeout) or "timeout" in low or "timed out" in low:
        return FetchOutcome(
            tier="degraded",
            code="timeout_network",
            retryable=True,
            detail=detail,
            network_issue=True,
        )
    if any(token in low for token in ("net::err_", "connection reset", "dns", "network", "econnreset", "tunnel")):
        return FetchOutcome(
            tier="degraded",
            code="network_issue",
            retryable=True,
            detail=detail,
            network_issue=True,
        )
    return FetchOutcome(tier="degraded", code="unexpected_error", detail=detail)


def _classify_empty_result(
    *,
    site: str,
    title: str,
    body_text: str,
    html: str,
    response_status: int,
    count_primary: int,
    count_alt: int,
    listing_signals: bool,
) -> FetchOutcome:
    haystack = "\n".join([title, body_text, html]).lower()
    detail = (
        f"site={site} http_status={response_status or 'n/a'} "
        f"selector_primary={count_primary} selector_alt={count_alt} "
        f"body_hint={_body_hint(body_text)}"
    )
    if response_status in _HTTP_BLOCK_STATUSES:
        return FetchOutcome(
            tier="blocked",
            code="hard_block",
            http_status=response_status,
            detail=detail,
            hard_block=True,
        )
    if _count_hits(haystack, _SOFT_BLOCK_HTML_KEYS) > 0 or _count_hits(haystack, _SUSPICIOUS_EMPTY_TEXT_KEYS) > 0:
        return FetchOutcome(
            tier="suspect",
            code="empty_suspicious",
            http_status=response_status,
            retryable=True,
            detail=detail,
            suspicious_empty=True,
        )
    if listing_signals or count_primary > 0 or count_alt > 0:
        return FetchOutcome(
            tier="degraded",
            code="parse_issue",
            http_status=response_status,
            detail=detail,
            parse_issue=True,
        )
    if _count_hits(haystack, _LEGIT_EMPTY_TEXT_KEYS) > 0:
        return FetchOutcome(
            tier="healthy",
            code="empty_legit",
            http_status=response_status,
            detail=detail,
        )
    if response_status in _HTTP_NETWORK_STATUSES:
        return FetchOutcome(
            tier="degraded",
            code="network_issue",
            http_status=response_status,
            retryable=True,
            detail=detail,
            network_issue=True,
        )
    if len(_normalize(body_text)) < 120:
        return FetchOutcome(
            tier="suspect",
            code="empty_suspicious",
            http_status=response_status,
            retryable=True,
            detail=detail,
            suspicious_empty=True,
        )
    return FetchOutcome(
        tier="degraded",
        code="parse_issue",
        http_status=response_status,
        detail=detail,
        parse_issue=True,
    )


def _apply_guard_outcome(
    *,
    state: dict,
    site: str,
    outcome: FetchOutcome,
    now: datetime,
    base_sec: int,
    max_sec: int,
    channel_label: str,
) -> GuardDecision:
    entry = _site_state(state, site)
    previous_tier = str(entry.get("last_outcome_tier") or "")
    previous_code = str(entry.get("last_outcome_code") or "")
    previous_strikes = int(entry.get("strikes") or 0)
    transition = previous_tier != outcome.tier or previous_code != outcome.code

    entry["last_attempt_utc"] = now.isoformat()
    entry["last_outcome_tier"] = outcome.tier
    entry["last_outcome_code"] = outcome.code
    entry["last_outcome_detail"] = (outcome.detail or "")[:240]

    if outcome.tier == "cooling":
        return GuardDecision(
            action="skip_due_cooldown",
            transition=transition,
            previous_tier=previous_tier,
            previous_code=previous_code,
        )

    if outcome.tier == "healthy":
        success_streak = int(entry.get("consecutive_successes") or 0) + 1
        was_problematic = previous_tier in {"suspect", "degraded", "blocked", "cooling"} or previous_strikes > 0
        entry["consecutive_successes"] = success_streak
        entry["consecutive_failures"] = 0
        entry["consecutive_suspect"] = 0
        entry["consecutive_blocks"] = 0
        entry["cooldown_until_utc"] = ""
        entry["last_success_utc"] = now.isoformat()
        entry["last_valid_channel"] = channel_label
        entry["strikes"] = 0 if success_streak >= 2 else max(0, previous_strikes - 1)
        if was_problematic:
            entry["last_recovery_utc"] = now.isoformat()
        return GuardDecision(
            action="recovered" if was_problematic else "healthy",
            transition=transition,
            recovered=was_problematic,
            previous_tier=previous_tier,
            previous_code=previous_code,
        )

    entry["consecutive_successes"] = 0
    entry["consecutive_failures"] = int(entry.get("consecutive_failures") or 0) + 1
    entry["last_reason"] = outcome.code

    if outcome.tier == "blocked":
        blocks = int(entry.get("consecutive_blocks") or 0) + 1
        strikes = previous_strikes + 1
        cooldown = min(max_sec, base_sec * (2 ** max(0, strikes - 1)))
        entry["consecutive_blocks"] = blocks
        entry["consecutive_suspect"] = 0
        entry["strikes"] = strikes
        entry["cooldown_until_utc"] = (now + timedelta(seconds=cooldown)).isoformat()
        return GuardDecision(
            action="apply_cooldown_block",
            cooldown_sec=cooldown,
            transition=transition,
            previous_tier=previous_tier,
            previous_code=previous_code,
        )

    entry["consecutive_blocks"] = 0
    if outcome.tier == "suspect":
        suspect_streak = int(entry.get("consecutive_suspect") or 0) + 1
        entry["consecutive_suspect"] = suspect_streak
        if suspect_streak >= 2:
            cooldown = min(max_sec, max(90, base_sec // 3) * min(3, suspect_streak - 1))
            entry["strikes"] = max(previous_strikes, 1)
            entry["cooldown_until_utc"] = (now + timedelta(seconds=cooldown)).isoformat()
            return GuardDecision(
                action="apply_cooldown_suspect",
                cooldown_sec=cooldown,
                transition=transition,
                previous_tier=previous_tier,
                previous_code=previous_code,
            )
        return GuardDecision(
            action="observe_suspect",
            transition=transition,
            previous_tier=previous_tier,
            previous_code=previous_code,
        )

    entry["consecutive_suspect"] = 0
    if outcome.code in {"timeout_network", "network_issue", "unexpected_error"} and int(entry.get("consecutive_failures") or 0) >= 2:
        cooldown = min(max_sec, max(120, base_sec // 4) * min(3, int(entry.get("consecutive_failures") or 0) - 1))
        entry["strikes"] = max(previous_strikes, 1)
        entry["cooldown_until_utc"] = (now + timedelta(seconds=cooldown)).isoformat()
        return GuardDecision(
            action="apply_cooldown_degraded",
            cooldown_sec=cooldown,
            transition=transition,
            previous_tier=previous_tier,
            previous_code=previous_code,
        )
    return GuardDecision(
        action="observe_degraded",
        transition=transition,
        previous_tier=previous_tier,
        previous_code=previous_code,
    )


def _save_guard_event_artifact(*, debug_dir: Path | None, site: str, event: str, payload: dict, logger) -> None:
    if debug_dir is None:
        return
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = debug_dir / f"{stamp}_{_slug(site)}_{_slug(event)}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        logger.info("Saved guard event artifact. file=%s", path)
    except Exception as exc:
        logger.debug("Unable to save guard event artifact (%s): %s", event, exc)


def _log_guard_decision(*, logger, site: str, url: str, outcome: FetchOutcome, decision: GuardDecision, entry: dict) -> None:
    if outcome.tier == "healthy" and decision.recovered:
        logger.info(
            "Site guard recovery. site=%s previous=%s/%s now=%s/%s strikes=%s success_streak=%s url=%s",
            site,
            decision.previous_tier or "n/a",
            decision.previous_code or "n/a",
            outcome.tier,
            outcome.code,
            entry.get("strikes"),
            entry.get("consecutive_successes"),
            url,
        )
        return
    log = logger.warning if outcome.tier in {"suspect", "blocked"} or decision.cooldown_sec > 0 else logger.info
    log(
        "Site guard outcome. site=%s tier=%s code=%s action=%s strikes=%s cooldown_sec=%s url=%s",
        site,
        outcome.tier,
        outcome.code,
        decision.action,
        entry.get("strikes"),
        decision.cooldown_sec,
        url,
    )


def _rotated_channel_candidates(
    *,
    requested_channel: str | None,
    rotation_mode: str,
    state: dict | None,
) -> list[str | None]:
    if rotation_mode != "round_robin":
        return [requested_channel]
    if requested_channel is not None:
        return [requested_channel]
    last_label = _PREFERRED_AUTO_CHANNELS[-1]
    if state is not None:
        last_label = str(state.get("last_channel") or _PREFERRED_AUTO_CHANNELS[-1]).strip().lower()
    if last_label not in _CHANNEL_LABELS:
        last_label = _PREFERRED_AUTO_CHANNELS[-1]

    # Prefer real installed channels first (msedge/chrome), keep bundled chromium as fallback.
    preferred = list(_PREFERRED_AUTO_CHANNELS)
    if last_label in preferred:
        start = (preferred.index(last_label) + 1) % len(preferred)
    else:
        start = 0
    labels = [preferred[(start + i) % len(preferred)] for i in range(len(preferred))]
    labels.append("chromium")
    return [_label_to_channel(label) for label in labels]


def _slug(value: str) -> str:
    out = []
    for ch in (value or "").lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in {"-", "_"}:
            out.append(ch)
        else:
            out.append("-")
    slug = "".join(out).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "n-a"


def _profile_dir_for_channel(base_dir: Path, channel_label: str) -> Path:
    """
    Keep isolated user-data dirs per browser channel to avoid profile corruption
    when switching between msedge/chrome/chromium.
    """
    base_name = base_dir.name.strip().lower()
    if base_name == channel_label:
        return base_dir
    if base_name in _CHANNEL_LABELS:
        return base_dir.parent / channel_label
    return base_dir / channel_label


async def _save_debug_artifacts(*, page, debug_dir: Path | None, site: str, reason: str, logger) -> None:
    if debug_dir is None:
        return
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stem = f"{stamp}_{_slug(site)}_{_slug(reason)}"
        html_path = debug_dir / f"{stem}.html"
        png_path = debug_dir / f"{stem}.png"
        title = _normalize(await page.title())
        html = await page.content()
        header = f"<!-- url: {page.url}\n title: {title}\n reason: {reason}\n -->\n"
        html_path.write_text(header + html, encoding="utf-8")
        await page.screenshot(path=str(png_path), full_page=True)
        logger.info("Saved live debug artifacts. html=%s screenshot=%s", html_path, png_path)
    except Exception as exc:
        logger.debug("Unable to save debug artifacts (%s): %s", reason, exc)


def _guess_ad_id(url: str) -> str:
    m = re.search(r"/(\d{6,})/?", url)
    if m:
        return m.group(1)
    digits = "".join(ch for ch in url if ch.isdigit())
    return digits[-12:] if digits else url


def _sanitize_search_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return raw
    split = urlsplit(raw)
    host = (split.hostname or "").lower()
    blocked_params = {"dtcookie"}
    if "idealista.it" in host:
        blocked_params |= {"xtor", "xts"}
    if not split.query:
        return raw
    query = []
    for key, value in parse_qsl(split.query, keep_blank_values=True):
        if key.lower() in blocked_params:
            continue
        query.append((key, value))
    clean_query = urlencode(query, doseq=True)
    return urlunsplit((split.scheme, split.netloc, split.path, clean_query, split.fragment))


def _extract_cards_from_html_fallback(
    *,
    html: str,
    site: str,
    search_url: str,
    max_per_site: int,
) -> list[dict]:
    if site == "immobiliare":
        patterns = [
            r"https://www\.immobiliare\.it/annunci/\d+/?",
            r"/annunci/\d+/?",
        ]
        base = "https://www.immobiliare.it"
    else:
        patterns = [
            r"https://www\.idealista\.it/immobile/\d+/?",
            r"/immobile/\d+/?",
        ]
        base = "https://www.idealista.it"

    seen: set[str] = set()
    urls: list[str] = []
    for pattern in patterns:
        for m in re.finditer(pattern, html):
            href = m.group(0)
            if href.startswith("/"):
                href = base + href
            href = href.strip()
            if href not in seen:
                seen.add(href)
                urls.append(href)
            if len(urls) >= max_per_site:
                break
        if len(urls) >= max_per_site:
            break

    out = []
    for href in urls:
        out.append(
            {
                "site": site,
                "url": href,
                "ad_id": _guess_ad_id(href),
                "title": "",
                "price": "",
                "location": "",
                "agency": "",
                "fallback": True,
                "search_url": search_url,
            }
        )
    return out


async def _accept_cookies_if_present(page) -> None:
    selectors = [
        "button#onetrust-accept-btn-handler",
        'button[id*="onetrust-accept"]',
        "button#didomi-notice-agree-button",
        '[data-testid="uc-accept-all-button"]',
    ]
    for selector in selectors:
        try:
            node = page.locator(selector)
            if await node.count() > 0:
                await node.first.click(timeout=1200)
                await page.wait_for_timeout(250)
                return
        except Exception:
            continue
    labels = ["Accetta", "Accetta tutto", "Accept all", "Consenti", "Si, accetto", "Accetto"]
    for label in labels:
        try:
            btn = page.get_by_role("button", name=label)
            if await btn.count() > 0:
                await btn.first.click(timeout=1200)
                await page.wait_for_timeout(250)
                return
        except Exception:
            continue


async def _dismiss_intrusive_popups(page, *, site: str, logger) -> None:
    dismissed = 0
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(120)
    except Exception:
        pass

    selectors = [
        'button[aria-label*="chiudi" i]',
        'button[aria-label*="close" i]',
        'button[title*="chiudi" i]',
        '[data-testid*="close" i]',
        '[data-cy*="close" i]',
        '[class*="modal"] button[class*="close" i]',
        '[class*="popup"] button[class*="close" i]',
    ]
    for selector in selectors:
        try:
            nodes = page.locator(selector)
            count = await nodes.count()
            for idx in range(min(count, 3)):
                node = nodes.nth(idx)
                if not await node.is_visible():
                    continue
                await node.click(timeout=700)
                await page.wait_for_timeout(180)
                dismissed += 1
                break
        except Exception:
            continue

    labels = [
        "Chiudi",
        "Non ora",
        "No grazie",
        "Continua senza registrarti",
        "Continua senza",
        "Più tardi",
    ]
    for label in labels:
        try:
            btn = page.get_by_role("button", name=label)
            if await btn.count() > 0 and await btn.first.is_visible():
                await btn.first.click(timeout=700)
                await page.wait_for_timeout(180)
                dismissed += 1
        except Exception:
            continue

    if dismissed > 0:
        logger.info("Dismissed intrusive popup(s). site=%s count=%s", site, dismissed)


async def _has_captcha_widgets(page) -> bool:
    for selector in _CAPTCHA_WIDGET_SELECTORS:
        try:
            nodes = page.locator(selector)
            count = await nodes.count()
            for idx in range(min(count, 5)):
                node = nodes.nth(idx)
                if await node.is_visible():
                    return True
        except Exception:
            continue
    return False


async def _has_listing_signals(page, site: str) -> bool:
    if site == "immobiliare":
        selectors = [
            'ul[data-cy="search-layout-list"] li',
            'article[data-cy="listing-item"]',
            'a[href*="/annunci/"]',
        ]
    elif site == "idealista":
        selectors = [
            'a[itemprop="url"]',
            'a[href*="/immobile/"]',
            "article",
        ]
    else:
        return False

    for selector in selectors:
        try:
            if await page.locator(selector).count() > 0:
                return True
        except Exception:
            continue
    return False


def _extract_block_id(*, html: str, body_text: str) -> str:
    for source in (body_text, html):
        m = _HARD_BLOCK_ID_RE.search(source or "")
        if m:
            return m.group(1).strip()
    return ""


async def _is_hard_block_page(page, html: str | None = None) -> tuple[bool, str]:
    html_raw = html or await page.content()
    try:
        title = _normalize(await page.title())
    except Exception:
        title = ""
    try:
        body = _normalize(await page.locator("body").inner_text())
    except Exception:
        body = ""

    haystack = "\n".join([title, body, html_raw])
    hits = sum(1 for pattern in _HARD_BLOCK_PATTERNS if pattern.search(haystack))
    if hits >= 2:
        return True, _extract_block_id(html=html_raw, body_text=body)
    return False, ""


async def _is_likely_captcha(page, html: str | None = None) -> bool:
    url_l = (page.url or "").lower()
    if any(key in url_l for key in _CAPTCHA_URL_KEYS):
        return True
    html_l = (html or await page.content()).lower()
    if any(key in html_l for key in _CAPTCHA_HTML_STRONG_KEYS):
        return True
    hits = sum(1 for key in _CAPTCHA_TEXT_KEYS if key in html_l)
    if hits >= 1:
        return True
    try:
        title_l = _normalize(await page.title()).lower()
    except Exception:
        title_l = ""
    if "captcha" in title_l:
        return True
    try:
        body_l = _normalize(await page.locator("body").inner_text()).lower()
    except Exception:
        body_l = ""
    if any(key in body_l for key in _CAPTCHA_TEXT_KEYS):
        return True
    return await _has_captcha_widgets(page)


async def _wait_until_captcha_cleared(page, timeout_sec: int, logger) -> bool:
    elapsed = 0
    interval = 2
    while elapsed < timeout_sec:
        await asyncio.sleep(interval)
        elapsed += interval
        try:
            hard_block, block_id = await _is_hard_block_page(page)
            if hard_block:
                suffix = f" block_id={block_id}" if block_id else ""
                logger.warning(
                    "Detected non-interactive hard block while waiting for captcha solve.%s",
                    suffix,
                )
                return False
            if not await _is_likely_captcha(page):
                logger.info("Captcha appears solved after %s sec.", elapsed)
                return True
        except Exception:
            continue
    return False


async def _resolve_captcha_flow(
    *,
    page,
    search_url: str,
    site: str,
    captcha_mode: CaptchaMode,
    captcha_wait_sec: int,
    headless: bool,
    logger,
    phase: str,
    html: str | None = None,
) -> tuple[bool, str]:
    if await _has_listing_signals(page, site):
        return True, "ok"

    hard_block, block_id = await _is_hard_block_page(page, html)
    if hard_block:
        suffix = f" block_id={block_id}" if block_id else ""
        logger.warning(
            "Hard block page detected (%s). url=%s current_url=%s%s",
            phase,
            search_url,
            page.url,
            suffix,
        )
        if captcha_mode == "stop_and_notify":
            raise LiveFetchBlocked("hard_block", f"Hard block detected with stop mode on {search_url}")
        if captcha_mode == "pause_and_notify" and not headless:
            logger.warning("Manual captcha wait skipped: this page is blocked and not solvable from browser.")
        return False, "hard_block"

    if not await _is_likely_captcha(page, html):
        return True, "ok"
    logger.warning(
        "Captcha/block likely detected (%s). url=%s current_url=%s",
        phase,
        search_url,
        page.url,
    )
    if captcha_mode == "stop_and_notify":
        raise LiveFetchBlocked("challenge_visible", f"Captcha detected with stop mode on {search_url}")
    if captcha_mode == "skip_and_notify" and not headless:
        auto_wait = min(12, max(6, int(captcha_wait_sec // 2)))
        logger.info(
            "Captcha/verification challenge detected (%s). Auto-wait up to %s sec for self-clear.",
            phase,
            auto_wait,
        )
        solved = await _wait_until_captcha_cleared(page, timeout_sec=auto_wait, logger=logger)
        if solved:
            return True, "ok"
        logger.warning("Verification/captcha still active after auto-wait. skip url=%s", search_url)
        return False, "challenge_visible"
    if captcha_mode == "pause_and_notify" and not headless:
        if not await _has_captcha_widgets(page):
            logger.warning(
                "Manual captcha wait skipped: no interactive captcha widget detected (likely hard block)."
            )
            return False, "challenge_visible"
        logger.warning("Waiting up to %s sec for manual captcha solve...", captcha_wait_sec)
        solved = await _wait_until_captcha_cleared(page, timeout_sec=max(10, captcha_wait_sec), logger=logger)
        if not solved:
            logger.warning("Captcha not solved in time. skip url=%s", search_url)
            return False, "challenge_visible"
        return True, "ok"
    return False, "challenge_visible"


async def _wait_for_any_selector(page, selectors: list[str], timeout_ms: int) -> bool:
    deadline = max(200, timeout_ms)
    slice_ms = 1500
    elapsed = 0
    while elapsed < deadline:
        for selector in selectors:
            try:
                if await page.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
        await page.wait_for_timeout(min(slice_ms, deadline - elapsed))
        elapsed += slice_ms
    return False


async def _gentle_scroll(page, steps: int, delay_ms: int, selectors: list[str] | None = None) -> None:
    for _ in range(max(0, steps)):
        moved = False
        if selectors:
            for selector in selectors:
                try:
                    moved = bool(
                        await page.evaluate(
                            """
                            (sel) => {
                              const el = document.querySelector(sel);
                              if (!el) return false;
                              const before = el.scrollTop;
                              el.scrollBy({ top: 1100, left: 0, behavior: 'instant' });
                              return el.scrollTop !== before;
                            }
                            """,
                            selector,
                        )
                    )
                    if moved:
                        break
                except Exception:
                    continue
        if not moved:
            try:
                await page.evaluate("window.scrollBy(0, 1100)")
            except Exception:
                break
        await page.wait_for_timeout(delay_ms)


async def _prepare_site_view(page, site: str, nav_timeout_ms: int, logger) -> None:
    if site == "immobiliare":
        try:
            btn = await page.query_selector('[data-cy="switch-to-list"], button[aria-controls*="results-list"]')
            if btn:
                await btn.click(timeout=1500)
                await page.wait_for_load_state("domcontentloaded", timeout=nav_timeout_ms)
                await page.wait_for_timeout(500)
        except Exception:
            logger.debug("List switch not applied for immobiliare.")
        await _wait_for_any_selector(
            page,
            [
                'ul[data-cy="search-layout-list"] li',
                'article[data-cy="listing-item"]',
                'a[href*="/annunci/"]',
            ],
            timeout_ms=min(15000, nav_timeout_ms),
        )
        await _gentle_scroll(
            page,
            steps=4,
            delay_ms=260,
            selectors=[
                'ul[data-cy="search-layout-list"]',
                '[data-cy="search-layout-list"]',
                'section[data-cy="results-list"]',
            ],
        )
    elif site == "idealista":
        await _wait_for_any_selector(
            page,
            [
                'a[itemprop="url"]',
                'a[href*="/immobile/"]',
                "article",
            ],
            timeout_ms=min(15000, nav_timeout_ms),
        )
        await _gentle_scroll(page, steps=5, delay_ms=260)


async def _extract_cards(
    page,
    selector: str,
    base_url: str,
    max_per_site: int,
    site: str,
    extraction: ExtractionFields,
):
    cards = []
    seen_urls: set[str] = set()
    anchors = await page.query_selector_all(selector)
    for anchor in anchors:
        try:
            href = await anchor.get_attribute("href")
            if not href:
                continue
            if href.startswith("/"):
                href = base_url + href
            href = href.strip()
            if href in seen_urls:
                continue
            seen_urls.add(href)

            meta = await anchor.evaluate(
                """
                (el, site) => {
                  const card =
                    el.closest('article') ||
                    el.closest('li') ||
                    el.closest('div[class*="item"]') ||
                    el.closest('div[class*="listing"]') ||
                    el.parentElement;

                  const clean = (v) => ((v || "").replace(/\\s+/g, " ").trim());

                  const firstText = (selectors) => {
                    if (!card) return "";
                    for (const sel of selectors) {
                      const n = card.querySelector(sel);
                      if (!n) continue;
                      const txt = clean(n.textContent || "");
                      if (txt) return txt;
                    }
                    return "";
                  };

                  const firstAttrOrText = (selectors, attr) => {
                    if (!card) return "";
                    for (const sel of selectors) {
                      const n = card.querySelector(sel);
                      if (!n) continue;
                      const av = attr && n.getAttribute ? clean(n.getAttribute(attr) || "") : "";
                      if (av) return av;
                      const txt = clean(n.textContent || "");
                      if (txt) return txt;
                    }
                    return "";
                  };

                  const anchorTitle = clean((el.getAttribute && el.getAttribute('title')) || el.textContent || "");
                  let title = "";
                  let price = "";
                  let location = "";
                  let agency = "";

                  if (site === "idealista") {
                    title =
                      firstAttrOrText(
                        [
                          'a[href*="/immobile/"][title]',
                          'a[itemprop="url"][title]',
                          'a[class*="item-link"][title]',
                        ],
                        "title",
                      ) ||
                      firstText(
                        [
                          'a[href*="/immobile/"]',
                          'a[itemprop="url"]',
                          'a[class*="item-link"]',
                          '[data-cy="listing-title"]',
                          'h2, h3',
                        ],
                      );
                    price = firstText(
                      [
                        '[class*="price"]',
                        'span[itemprop="price"]',
                        '.item-price',
                        '[data-cy="price"]',
                      ],
                    );
                    location = firstText(
                      [
                        '[data-cy="listing-location"]',
                        '[class*="listingCardAddress"]',
                        '[class*="Address"]',
                        '[class*="location"]',
                        '[class*="card-location"]',
                        'span[itemprop="addressLocality"]',
                        '.item-location',
                      ],
                    );
                    agency =
                      firstAttrOrText(
                        [
                          'figure[class*="listingCardAgencyLogo"] img',
                          'img[class*="listingCardAgencyLogo"]',
                          'img[alt*="Agenzia"]',
                          'img[alt*="Immobiliare"]',
                        ],
                        "alt",
                      ) ||
                      firstText(
                        [
                          '[class*="advertiser"] [class*="name"]',
                          '[data-testid="company-name"]',
                          '.item-info [class*="item-brand"]',
                          '.item-info [class*="company"]',
                          'a[href*="/agenzie-immobiliari/"]',
                          'a[href*="/pro/"]',
                        ],
                      );
                  } else {
                    title =
                      firstAttrOrText(
                        [
                          '[data-cy="listing-title"]',
                          'a[class*="listingCardTitle"]',
                          'a[href*="/annunci/"][title]',
                        ],
                        "title",
                      ) ||
                      firstText(['h2', 'h3', 'a[href*="/annunci/"]']);
                    price = firstText(
                      [
                        '[data-cy="price"] span',
                        '[data-cy="price"]',
                        '[class*="listingCardPrice"] span',
                        '[class*="price"]',
                        '.item-price',
                      ],
                    );
                    location = firstText(
                      [
                        '[data-cy="listing-location"]',
                        '[class*="address"]',
                        '[class*="location"]',
                        '.item-location',
                      ],
                    );
                    agency =
                      firstAttrOrText(
                        [
                          '[data-cy="agency-name"]',
                          'img[alt][class*="Agency"]',
                          'figure img[alt]',
                          'img[alt*="Agenzia"]',
                          'img[alt*="Immobiliare"]',
                        ],
                        "alt",
                      ) ||
                      firstText(
                        [
                          '[class*="advertiser"] [class*="name"]',
                          '[data-testid="company-name"]',
                          'a[href*="/agenzie-immobiliari/"]',
                        ],
                      );
                  }

                  return {
                    title: clean(title),
                    price: clean(price),
                    location: clean(location),
                    agency: clean(agency),
                    anchor_title: anchorTitle,
                  };
                }
                """,
                site,
            )

            title = _normalize(meta.get("title"))
            price = _normalize(meta.get("price")) if extraction.extract_price else ""
            location = _normalize(meta.get("location")) if extraction.extract_zone else ""
            agency = _normalize(meta.get("agency")) if extraction.extract_agency else ""
            anchor_title = _normalize(meta.get("anchor_title"))
            if not title:
                title = anchor_title or _normalize(await anchor.inner_text())
            if extraction.extract_zone and not location:
                location = _guess_location_from_title(title)
            if site == "idealista":
                # Guard against false title capture on agency elements.
                if agency and title and _normalize(title).lower() == _normalize(agency).lower():
                    if anchor_title and _normalize(anchor_title).lower() != _normalize(agency).lower():
                        title = anchor_title

            cards.append(
                {
                    "site": site,
                    "url": href,
                    "ad_id": _guess_ad_id(href),
                    "title": title,
                    "price": price,
                    "location": location,
                    "agency": agency,
                }
            )
            if len(cards) >= max_per_site:
                break
        except Exception:
            continue
    return cards


async def _extract_for_url(
    page,
    search_url: str,
    extraction: ExtractionFields,
    max_per_site: int,
    wait_after_goto_ms: int,
    nav_timeout_ms: int,
    captcha_mode: CaptchaMode,
    captcha_wait_sec: int,
    headless: bool,
    debug_dir: Path | None,
    logger,
) -> tuple[list[dict], FetchOutcome]:
    request_url = _sanitize_search_url(search_url)
    if request_url != search_url:
        logger.info("Sanitized search URL for navigation. host=%s", (urlparse(search_url).hostname or "").lower())
    response = await page.goto(request_url, timeout=nav_timeout_ms)
    response_status = response.status if response is not None else 0
    await page.wait_for_load_state("domcontentloaded", timeout=nav_timeout_ms)
    await page.wait_for_timeout(wait_after_goto_ms)
    await _accept_cookies_if_present(page)
    selector_primary_count = 0
    selector_alt_count = 0

    host = (urlparse(search_url).hostname or "").lower()
    if "immobiliare.it" in host:
        selector = (
            'ul[data-cy="search-layout-list"] a[href*="/annunci/"], '
            'article[data-cy="listing-item"] a[href*="/annunci/"], '
            'a[href^="https://www.immobiliare.it/annunci/"], a[href^="/annunci/"]'
        )
        base = "https://www.immobiliare.it"
        site = "immobiliare"
    elif "idealista.it" in host:
        selector = 'a[href*="/immobile/"], a[itemprop="url"], a[class*="item-link"]'
        base = "https://www.idealista.it"
        site = "idealista"
    else:
        logger.warning("Unsupported host, skipped url=%s", search_url)
        return [], FetchOutcome(tier="degraded", code="unsupported_site", http_status=response_status, detail=search_url)

    await _dismiss_intrusive_popups(page, site=site, logger=logger)
    html = await page.content()
    can_continue, flow_code = await _resolve_captcha_flow(
        page=page,
        search_url=search_url,
        site=site,
        captcha_mode=captcha_mode,
        captcha_wait_sec=captcha_wait_sec,
        headless=headless,
        logger=logger,
        phase="after_goto",
        html=html,
    )
    if not can_continue:
        hard_block, _ = await _is_hard_block_page(page, html)
        outcome = FetchOutcome(
            tier="blocked",
            code="hard_block" if hard_block or flow_code == "hard_block" or response_status in _HTTP_BLOCK_STATUSES else "challenge_visible",
            http_status=response_status,
            detail=f"phase=after_goto url={page.url}",
            challenge_visible=not hard_block,
            hard_block=hard_block or response_status in _HTTP_BLOCK_STATUSES,
        )
        await _save_debug_artifacts(
            page=page,
            debug_dir=debug_dir,
            site=site,
            reason=outcome.code,
            logger=logger,
        )
        if captcha_mode == "skip_and_notify" and not headless:
            logger.warning(
                "Headed session closed because captcha_mode=skip_and_notify. "
                "Use --override-captcha-mode pause_and_notify to solve captcha manually."
            )
        return [], outcome

    await _prepare_site_view(page, site=site, nav_timeout_ms=nav_timeout_ms, logger=logger)
    await _dismiss_intrusive_popups(page, site=site, logger=logger)
    can_continue, flow_code = await _resolve_captcha_flow(
        page=page,
        search_url=search_url,
        site=site,
        captcha_mode=captcha_mode,
        captcha_wait_sec=captcha_wait_sec,
        headless=headless,
        logger=logger,
        phase="after_prepare",
    )
    if not can_continue:
        hard_block, _ = await _is_hard_block_page(page)
        outcome = FetchOutcome(
            tier="blocked",
            code="hard_block" if hard_block or flow_code == "hard_block" else "challenge_visible",
            http_status=response_status,
            detail=f"phase=after_prepare url={page.url}",
            challenge_visible=not hard_block,
            hard_block=hard_block,
        )
        await _save_debug_artifacts(
            page=page,
            debug_dir=debug_dir,
            site=site,
            reason=outcome.code,
            logger=logger,
        )
        if captcha_mode == "skip_and_notify" and not headless:
            logger.warning(
                "Headed session closed because captcha_mode=skip_and_notify. "
                "Use --override-captcha-mode pause_and_notify to solve captcha manually."
            )
        return [], outcome
    cards = await _extract_cards(
        page=page,
        selector=selector,
        base_url=base,
        max_per_site=max_per_site,
        site=site,
        extraction=extraction,
    )
    used_fallback = False
    if not cards:
        html_after = await page.content()
        if await _is_likely_captcha(page, html_after):
            logger.warning("Captcha/block detected during extraction fallback. url=%s current_url=%s", search_url, page.url)
        if site == "immobiliare":
            count_primary = await page.locator('ul[data-cy="search-layout-list"] a[href*="/annunci/"]').count()
            count_alt = await page.locator('a[href*="/annunci/"]').count()
        else:
            count_primary = await page.locator('a[itemprop="url"], article a[href*="/immobile/"]').count()
            count_alt = await page.locator('a[href*="/immobile/"]').count()
        selector_primary_count = count_primary
        selector_alt_count = count_alt
        try:
            title = _normalize(await page.title())
        except Exception:
            title = ""
        try:
            body_text = _normalize(await page.locator("body").inner_text())
            body_hint = body_text[:240]
        except Exception:
            body_hint = ""
            body_text = ""
        try:
            listing_signals = await _has_listing_signals(page, site)
        except Exception:
            listing_signals = False
        logger.info(
            "No DOM cards parsed. site=%s selector_primary=%s selector_alt=%s current_url=%s title=%s body_hint=%s",
            site,
            count_primary,
            count_alt,
            page.url,
            title,
            body_hint,
        )
        fallback_cards = _extract_cards_from_html_fallback(
            html=html_after,
            site=site,
            search_url=search_url,
            max_per_site=max_per_site,
        )
        if fallback_cards:
            logger.info("Using HTML fallback extraction. site=%s listings=%s", site, len(fallback_cards))
            cards = fallback_cards
            used_fallback = True
        else:
            outcome = _classify_empty_result(
                site=site,
                title=title,
                body_text=body_text,
                html=html_after,
                response_status=response_status,
                count_primary=selector_primary_count,
                count_alt=selector_alt_count,
                listing_signals=listing_signals,
            )
            if outcome.code != "empty_legit":
                await _save_debug_artifacts(
                    page=page,
                    debug_dir=debug_dir,
                    site=site,
                    reason=outcome.code,
                    logger=logger,
                )
            logger.info(
                "Fetched site=%s url=%s tier=%s code=%s listings=0",
                site,
                search_url,
                outcome.tier,
                outcome.code,
            )
            return [], outcome
    logger.info("Fetched site=%s url=%s listings=%s", site, search_url, len(cards))
    metrics = _build_extraction_metrics(
        site=site,
        cards=cards,
        fallback_used=used_fallback,
        selector_primary_count=selector_primary_count,
        selector_alt_count=selector_alt_count,
    )
    if cards:
        outcome = FetchOutcome(
            tier="healthy",
            code="ok",
            http_status=response_status,
            listings=len(cards),
            detail=(
                f"quality={metrics.quality} title_missing={metrics.missing_title_pct}% "
                f"location_missing={metrics.missing_location_pct}% agency_missing={metrics.missing_agency_pct}%"
            ),
            from_fallback=used_fallback,
            extraction_quality=metrics.quality,
        )
        if metrics.quality == "fallback_only":
            outcome.tier = "degraded"
            outcome.code = "fallback_dominant"
            outcome.parse_issue = True
        elif metrics.quality == "poor":
            outcome.tier = "degraded"
            outcome.code = "partial_success_degraded"
            outcome.parse_issue = True
        elif metrics.quality == "partial":
            outcome.extraction_quality = "partial"
        return cards, outcome
    return [], FetchOutcome(tier="healthy", code="empty_legit", http_status=response_status)


def _normalize_browser_channel(value: str | None) -> str | None:
    raw = (value or "").strip().lower()
    if raw in {"", "auto", "chromium"}:
        return None
    if raw in {"chrome", "msedge"}:
        return raw
    raise ValueError("browser_channel must be one of: auto|chromium|chrome|msedge")


async def fetch_live_once(
    *,
    search_urls: list[str],
    extraction: ExtractionFields,
    max_per_site: int,
    headless: bool,
    wait_after_goto_ms: int,
    nav_timeout_ms: int,
    captcha_mode: CaptchaMode,
    captcha_wait_sec: int,
    profile_dir: str | None,
    debug_dir: str | None,
    browser_channel: str | None,
    site_guard_enabled: bool,
    site_guard_state_path: str | None,
    guard_jitter_min_sec: int,
    guard_jitter_max_sec: int,
    guard_base_cooldown_sec: int,
    guard_max_cooldown_sec: int,
    channel_rotation_mode: str,
    guard_ignore_cooldown: bool,
    logger,
) -> list[ListingRecord]:
    if not search_urls:
        return []
    out: list[ListingRecord] = []
    debug_path = Path(debug_dir).expanduser() if debug_dir else None
    channel = _normalize_browser_channel(browser_channel)
    if channel_rotation_mode not in {"off", "round_robin"}:
        raise ValueError("channel_rotation_mode must be one of: off|round_robin")
    guard_state_path = Path(site_guard_state_path).expanduser() if site_guard_state_path else None
    guard_state = _load_guard_state(guard_state_path) if (site_guard_enabled and guard_state_path is not None) else None
    jitter_min = max(0, int(guard_jitter_min_sec))
    jitter_max = max(jitter_min, int(guard_jitter_max_sec))
    base_cooldown = max(60, int(guard_base_cooldown_sec))
    max_cooldown = max(base_cooldown, int(guard_max_cooldown_sec))
    outcomes_seen: list[FetchOutcome] = []

    async with async_playwright() as pw:
        browser = None
        context = None
        launch_error: Exception | None = None
        selected_channel: str | None = None
        channel_candidates = _rotated_channel_candidates(
            requested_channel=channel,
            rotation_mode=channel_rotation_mode,
            state=guard_state,
        )
        if channel_rotation_mode == "round_robin":
            logger.info(
                "Site guard channel rotation candidates: %s",
                ",".join(_channel_to_label(x) for x in channel_candidates),
            )
        for candidate in channel_candidates:
            try:
                if profile_dir:
                    p_base = Path(profile_dir).expanduser()
                    channel_label = _channel_to_label(candidate)
                    p = _profile_dir_for_channel(p_base, channel_label)
                    p.mkdir(parents=True, exist_ok=True)
                    launch_persistent_kwargs = {
                        "user_data_dir": str(p),
                        "headless": headless,
                        "args": ["--disable-blink-features=AutomationControlled"],
                        "locale": "it-IT",
                        "timezone_id": "Europe/Rome",
                        "extra_http_headers": {"Accept-Language": "it-IT,it;q=0.9,en;q=0.8"},
                        "viewport": {"width": 1366, "height": 900},
                    }
                    if candidate is not None:
                        launch_persistent_kwargs["channel"] = candidate
                    context = await pw.chromium.launch_persistent_context(**launch_persistent_kwargs)
                    logger.info("Using persistent browser profile: %s channel=%s", p, candidate or "chromium")
                else:
                    launch_kwargs = {
                        "headless": headless,
                        "args": ["--disable-blink-features=AutomationControlled"],
                    }
                    if candidate is not None:
                        launch_kwargs["channel"] = candidate
                    browser = await pw.chromium.launch(**launch_kwargs)
                    context = await browser.new_context(
                        locale="it-IT",
                        timezone_id="Europe/Rome",
                        extra_http_headers={"Accept-Language": "it-IT,it;q=0.9,en;q=0.8"},
                        viewport={"width": 1366, "height": 900},
                    )
                    logger.info("Using ephemeral browser context. channel=%s", candidate or "chromium")
                selected_channel = candidate
                break
            except Exception as exc:
                launch_error = exc
                logger.warning("Browser channel launch failed. channel=%s details=%s", _channel_to_label(candidate), exc)
                if context is not None:
                    try:
                        await context.close()
                    except Exception:
                        pass
                if browser is not None:
                    try:
                        await browser.close()
                    except Exception:
                        pass
                context = None
                browser = None
        if context is None:
            if launch_error is not None:
                raise launch_error
            raise RuntimeError("Unable to start browser context.")

        if guard_state is not None and guard_state_path is not None:
            guard_state["last_channel"] = _channel_to_label(selected_channel)
            _save_guard_state(guard_state_path, guard_state)

        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            for url in search_urls:
                site = _site_key_from_url(url)
                if site_guard_enabled and guard_state is not None and guard_state_path is not None:
                    now = _utc_now()
                    rem = _cooldown_remaining_sec(guard_state, site, now)
                    if rem > 0 and not guard_ignore_cooldown:
                        logger.warning(
                            "Site guard cooldown active. site=%s remaining_sec=%s skip_url=%s",
                            site,
                            rem,
                            url,
                        )
                        logger.info(
                            "Cooldown skip hint. site=%s use --guard-ignore-cooldown for one forced run or --guard-reset-state to clear guard state.",
                            site,
                        )
                        cooldown_outcome = FetchOutcome(
                            tier="cooling",
                            code="cooldown_active",
                            detail=f"remaining_sec={rem}",
                        )
                        decision = _apply_guard_outcome(
                            state=guard_state,
                            site=site,
                            outcome=cooldown_outcome,
                            now=now,
                            base_sec=base_cooldown,
                            max_sec=max_cooldown,
                            channel_label=_channel_to_label(selected_channel),
                        )
                        _save_guard_state(guard_state_path, guard_state)
                        outcomes_seen.append(cooldown_outcome)
                        _log_guard_decision(
                            logger=logger,
                            site=site,
                            url=url,
                            outcome=cooldown_outcome,
                            decision=decision,
                            entry=_site_state(guard_state, site),
                        )
                        if debug_path is not None and decision.transition:
                            _save_guard_event_artifact(
                                debug_dir=debug_path,
                                site=site,
                                event=f"{cooldown_outcome.tier}_{cooldown_outcome.code}",
                                payload={
                                    "site": site,
                                    "url": url,
                                    "outcome": asdict(cooldown_outcome),
                                    "decision": asdict(decision),
                                    "state": dict(_site_state(guard_state, site)),
                                },
                                logger=logger,
                            )
                        continue
                    if rem > 0 and guard_ignore_cooldown:
                        logger.info("Forced live run while cooldown is active. site=%s remaining_sec=%s url=%s", site, rem, url)
                if site_guard_enabled and jitter_max > 0:
                    delay = random.uniform(jitter_min, jitter_max)
                    if delay > 0:
                        logger.info("Site guard jitter delay. site=%s delay_sec=%.2f", site, delay)
                        await asyncio.sleep(delay)
                try:
                    cards: list[dict] = []
                    outcome = FetchOutcome(tier="healthy", code="empty_legit")
                    metrics: ExtractionMetrics | None = None
                    drift: DriftDiagnostic | None = None
                    for attempt in (1, 2):
                        cards, outcome = await _extract_for_url(
                            page=page,
                            search_url=url,
                            extraction=extraction,
                            max_per_site=max_per_site,
                            wait_after_goto_ms=wait_after_goto_ms,
                            nav_timeout_ms=nav_timeout_ms,
                            captcha_mode=captcha_mode,
                            captcha_wait_sec=captcha_wait_sec,
                            headless=headless,
                            debug_dir=debug_path,
                            logger=logger,
                        )
                        if cards or not outcome.retryable or attempt == 2:
                            break
                        retry_sleep = random.uniform(2.0, 4.0)
                        logger.info(
                            "Transient live outcome. Retrying once conservatively. site=%s tier=%s code=%s delay_sec=%.2f url=%s",
                            site,
                            outcome.tier,
                            outcome.code,
                            retry_sleep,
                            url,
                        )
                        await asyncio.sleep(retry_sleep)
                    logger.info(
                        "Fetch URL result. site=%s tier=%s code=%s listings=%s url=%s",
                        site,
                        outcome.tier,
                        outcome.code,
                        len(cards) if cards else outcome.listings,
                        url,
                    )
                    if cards or outcome.code in {"empty_legit", "parse_issue", "empty_suspicious"}:
                        metrics = _build_extraction_metrics(
                            site=site,
                            cards=cards,
                            fallback_used=outcome.from_fallback,
                        )
                        prior_entry = _site_state(guard_state, site) if guard_state is not None else None
                        drift = _detect_parser_drift(metrics=metrics, prior=prior_entry, outcome=outcome)
                        if metrics.cards_count > 0:
                            _log_extraction_metrics(logger=logger, site=site, url=url, metrics=metrics, drift=drift)
                        elif drift.triggered:
                            logger.info(
                                "Parser drift signal. site=%s reason=%s detail=%s outcome=%s url=%s",
                                site,
                                drift.reason,
                                drift.detail,
                                outcome.code,
                                url,
                            )
                        if drift.triggered and outcome.tier == "healthy":
                            outcome.tier = "degraded"
                            outcome.code = "parser_drift"
                            outcome.parse_issue = True
                            outcome.detail = (
                                f"{outcome.detail} drift_reason={drift.reason} drift_detail={drift.detail}"
                            ).strip()
                    outcomes_seen.append(outcome)
                    if site_guard_enabled and guard_state is not None and guard_state_path is not None:
                        decision = _apply_guard_outcome(
                            state=guard_state,
                            site=site,
                            outcome=outcome,
                            now=_utc_now(),
                            base_sec=base_cooldown,
                            max_sec=max_cooldown,
                            channel_label=_channel_to_label(selected_channel),
                        )
                        _save_guard_state(guard_state_path, guard_state)
                        entry = _site_state(guard_state, site)
                        if metrics is not None:
                            _store_extraction_metrics(entry=entry, metrics=metrics)
                            _save_guard_state(guard_state_path, guard_state)
                        _log_guard_decision(
                            logger=logger,
                            site=site,
                            url=url,
                            outcome=outcome,
                            decision=decision,
                            entry=entry,
                        )
                        if debug_path is not None and (
                            decision.recovered
                            or decision.cooldown_sec > 0
                            or (decision.transition and outcome.tier in {"suspect", "degraded", "blocked", "cooling"})
                        ):
                            _save_guard_event_artifact(
                                debug_dir=debug_path,
                                site=site,
                                event=f"{outcome.tier}_{outcome.code}",
                                payload={
                                    "site": site,
                                    "url": url,
                                    "outcome": asdict(outcome),
                                    "decision": asdict(decision),
                                    "state": dict(entry),
                                },
                                logger=logger,
                            )
                        if metrics is not None and drift is not None and drift.triggered:
                            _save_parser_diagnostic_artifact(
                                debug_dir=debug_path,
                                site=site,
                                event=drift.artifact_event or "parser_drift",
                                url=url,
                                outcome=outcome,
                                metrics=metrics,
                                drift=drift,
                                logger=logger,
                            )
                    for card in cards:
                        out.append(
                            ListingRecord(
                                site=card["site"],
                                search_url=url,
                                ad_id=card["ad_id"],
                                url=card["url"],
                                title=card["title"],
                                price=card["price"],
                                location=card["location"],
                                agency=card["agency"],
                                payload={"source": "live_fetch"},
                            )
                        )
                except LiveFetchBlocked as exc:
                    outcome = FetchOutcome(
                        tier="blocked",
                        code=exc.code,
                        detail=_normalize(str(exc)),
                        hard_block=exc.code == "hard_block",
                        challenge_visible=exc.code == "challenge_visible",
                    )
                    outcomes_seen.append(outcome)
                    logger.warning("Live fetch blocked. site=%s code=%s url=%s details=%s", site, exc.code, url, exc)
                    if site_guard_enabled and guard_state is not None and guard_state_path is not None:
                        decision = _apply_guard_outcome(
                            state=guard_state,
                            site=site,
                            outcome=outcome,
                            now=_utc_now(),
                            base_sec=base_cooldown,
                            max_sec=max_cooldown,
                            channel_label=_channel_to_label(selected_channel),
                        )
                        _save_guard_state(guard_state_path, guard_state)
                        _log_guard_decision(
                            logger=logger,
                            site=site,
                            url=url,
                            outcome=outcome,
                            decision=decision,
                            entry=_site_state(guard_state, site),
                        )
                        if debug_path is not None:
                            _save_guard_event_artifact(
                                debug_dir=debug_path,
                                site=site,
                                event=f"{outcome.tier}_{outcome.code}",
                                payload={
                                    "site": site,
                                    "url": url,
                                    "outcome": asdict(outcome),
                                    "decision": asdict(decision),
                                    "state": dict(_site_state(guard_state, site)),
                                },
                                logger=logger,
                            )
                except PlaywrightTimeout as exc:
                    outcome = _classify_runtime_exception(exc)
                    outcomes_seen.append(outcome)
                    logger.warning("Timeout on url=%s", url)
                    if site_guard_enabled and guard_state is not None and guard_state_path is not None:
                        decision = _apply_guard_outcome(
                            state=guard_state,
                            site=site,
                            outcome=outcome,
                            now=_utc_now(),
                            base_sec=base_cooldown,
                            max_sec=max_cooldown,
                            channel_label=_channel_to_label(selected_channel),
                        )
                        _save_guard_state(guard_state_path, guard_state)
                        _log_guard_decision(
                            logger=logger,
                            site=site,
                            url=url,
                            outcome=outcome,
                            decision=decision,
                            entry=_site_state(guard_state, site),
                        )
                        if debug_path is not None:
                            _save_guard_event_artifact(
                                debug_dir=debug_path,
                                site=site,
                                event=f"{outcome.tier}_{outcome.code}",
                                payload={
                                    "site": site,
                                    "url": url,
                                    "outcome": asdict(outcome),
                                    "decision": asdict(decision),
                                    "state": dict(_site_state(guard_state, site)),
                                },
                                logger=logger,
                            )
                except Exception as exc:
                    outcome = _classify_runtime_exception(exc)
                    outcomes_seen.append(outcome)
                    logger.error("Live fetch error on url=%s details=%s", url, exc)
                    if site_guard_enabled and guard_state is not None and guard_state_path is not None:
                        decision = _apply_guard_outcome(
                            state=guard_state,
                            site=site,
                            outcome=outcome,
                            now=_utc_now(),
                            base_sec=base_cooldown,
                            max_sec=max_cooldown,
                            channel_label=_channel_to_label(selected_channel),
                        )
                        _save_guard_state(guard_state_path, guard_state)
                        _log_guard_decision(
                            logger=logger,
                            site=site,
                            url=url,
                            outcome=outcome,
                            decision=decision,
                            entry=_site_state(guard_state, site),
                        )
                        if debug_path is not None:
                            _save_guard_event_artifact(
                                debug_dir=debug_path,
                                site=site,
                                event=f"{outcome.tier}_{outcome.code}",
                                payload={
                                    "site": site,
                                    "url": url,
                                    "outcome": asdict(outcome),
                                    "decision": asdict(decision),
                                    "state": dict(_site_state(guard_state, site)),
                                },
                                logger=logger,
                            )
        finally:
            if context is not None:
                await context.close()
            if browser is not None:
                await browser.close()
    if outcomes_seen:
        tier_counts = {tier: 0 for tier in ("healthy", "suspect", "degraded", "blocked", "cooling")}
        code_counts: dict[str, int] = {}
        for item in outcomes_seen:
            tier_counts[item.tier] = tier_counts.get(item.tier, 0) + 1
            code_counts[item.code] = code_counts.get(item.code, 0) + 1
        code_summary = ", ".join(f"{code}={count}" for code, count in sorted(code_counts.items()))
        logger.info(
            "Live fetch outcome summary. urls=%s healthy=%s suspect=%s degraded=%s blocked=%s cooling=%s listings=%s codes=%s",
            len(outcomes_seen),
            tier_counts.get("healthy", 0),
            tier_counts.get("suspect", 0),
            tier_counts.get("degraded", 0),
            tier_counts.get("blocked", 0),
            tier_counts.get("cooling", 0),
            len(out),
            code_summary,
        )
    return out
