from __future__ import annotations

import asyncio
import json
import os
import random
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from browserforge.fingerprints import Screen
from camoufox.async_api import AsyncNewBrowser
from camoufox.exceptions import CamoufoxNotInstalled
from camoufox.pkgman import launch_path as camoufox_launch_path
from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

from ..db import Database, ListingRecord
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

_LIVE_DEBUG_RETENTION_SEC = 72 * 3600
_LIVE_DEBUG_MAX_FILES = 120

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

_IDEALISTA_AGENCY_ATTR_SELECTORS = (
    'figure[class*="listingCardAgencyLogo"] img',
    'img[class*="listingCardAgencyLogo"]',
    'a[href*="/pro/"] img[alt]',
    'img[alt*="Agenzia"]',
    'img[alt*="Immobiliare"]',
)

_IDEALISTA_AGENCY_TEXT_SELECTORS = (
    '[class*="advertiser"] [class*="name"]',
    '[data-testid="company-name"]',
    '.item-info [class*="item-brand"]',
    '.item-info [class*="company"]',
    'a[href*="/agenzie-immobiliari/"]',
    'a[href*="/pro/"]',
)
_IDEALISTA_PRIVATE_ONLY_DETAIL_MAX_CHECKS = 15
_IDEALISTA_PRIVATE_ONLY_DETAIL_DELAY_MS = (900, 1800)
_IDEALISTA_PRIVATE_ONLY_DETAIL_BATCH_PAUSE_EVERY = 4
_IDEALISTA_PRIVATE_ONLY_DETAIL_BATCH_PAUSE_MS = (1600, 3200)
_HTTP_NETWORK_STATUSES = {408, 425, 500, 502, 503, 504, 522, 524}

_HARD_BLOCK_PATTERNS = (
    re.compile(r"uso\s+improprio", re.IGNORECASE),
    re.compile(r"accesso.{0,40}bloccat", re.IGNORECASE),
    re.compile(r"difficolt[aà].{0,40}accedere", re.IGNORECASE),
    re.compile(r"contatta.{0,30}assistenza", re.IGNORECASE),
    re.compile(r"team\s+di\s+idealista", re.IGNORECASE),
)
_HARD_BLOCK_ID_RE = re.compile(r"\bID\s*:\s*([A-Za-z0-9-]{8,})\b", re.IGNORECASE)
_DEFAULT_BROWSER_LABEL = "camoufox"
_CHANNEL_LABELS = (_DEFAULT_BROWSER_LABEL,)
_CAMOUFOX_DEFAULT_LOCALE = "it-IT"
_CAMOUFOX_DEFAULT_OS = "windows"
_CAMOUFOX_DEFAULT_TIMEZONE = "Europe/Rome"
_LEGACY_BROWSER_CHANNEL_ALIASES = {
    "camoufox": _DEFAULT_BROWSER_LABEL,
    "firefox": _DEFAULT_BROWSER_LABEL,
    "chromium": _DEFAULT_BROWSER_LABEL,
    "chrome": _DEFAULT_BROWSER_LABEL,
    "msedge": _DEFAULT_BROWSER_LABEL,
}
_SITE_DEFAULT_CHANNELS: dict[str, tuple[str, ...]] = {
    "idealista": (_DEFAULT_BROWSER_LABEL,),
    "immobiliare": (_DEFAULT_BROWSER_LABEL,),
}
_GUARD_STATE_VERSION = 6
_BROWSER_MODE_MANAGED_STABLE = "managed_stable"
_BROWSER_MODE_REAL_BROWSER_ASSISTED = "real_browser_assisted"
_ASSIST_ENTRY_CDP_BOOTSTRAP = "cdp_bootstrap"
_ASSIST_ENTRY_CDP_RECOVERY = "cdp_recovery"


@dataclass(slots=True)
class RiskBudget:
    page_budget: int
    detail_budget: int
    identity_budget: int
    retry_budget: int
    cooldown_budget: int
    manual_assist_threshold: int


@dataclass(slots=True)
class FetchAttemptStats:
    retry_count: int = 0
    detail_touch_count: int = 0


@dataclass(slots=True)
class TelemetrySnapshot:
    site: str
    browser_mode: str
    channel_label: str
    identity_switch: int
    session_age_sec: int
    detail_touch_count: int
    retry_count: int
    risk_pause_reason: str
    outcome_tier: str
    outcome_code: str
    cooldown_origin: str
    manual_assist_used: bool
    state_transition: str
    assist_entry_mode: str = ""


@dataclass(slots=True)
class RunRiskState:
    pages_used: int = 0
    detail_used: int = 0
    retries_used: int = 0
    cooldown_used: int = 0
    stop_requested: bool = False
    stop_reason: str = ""
    current_state: str = "warmup"
    degraded_streak: int = 0
    challenge_count: int = 0
    assist_required: bool = False
    assist_reason: str = ""
    site_owner_replace_counts: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class BrowserSessionSlot:
    owner_key: str
    site: str
    channel_label: str
    profile_root: str
    browser: object | None
    context: object
    page: object
    reuse_count: int = 0
    created_monotonic: float = field(default_factory=time.monotonic)
    last_used_monotonic: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class LiveFetchServiceRuntime:
    playwright: object | None = None
    session_slots: dict[str, BrowserSessionSlot] = field(default_factory=dict)


@dataclass(slots=True)
class LiveFetchRunReport:
    listings: list[ListingRecord]
    run_state: str
    run_state_site: str
    assist_required: bool
    assist_reason: str
    stop_requested: bool
    stop_reason: str
    retry_count: int = 0
    detail_touch_count: int = 0
    identity_switch_count: int = 0
    same_site_profile_reuse_count: int = 0
    cross_site_session_reuse_count: int = 0
    site_session_replace_count: int = 0
    cooldown_count: int = 0
    site_outcome_tiers: dict[str, str] = field(default_factory=dict)


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


def _classify_idealista_publisher_kind(body_text: str) -> str:
    haystack = _normalize(body_text).lower()
    if not haystack:
        return ""

    anchors = (
        "persona che pubblica l'annuncio",
        "annuncio pubblicato da",
        "contatta l'inserzionista",
    )
    for anchor in anchors:
        idx = haystack.find(anchor)
        if idx < 0:
            continue
        window = haystack[idx : idx + 240]
        if re.search(r"\bprofessionista\b", window):
            return "professionista"
        if re.search(r"\bprivato\b", window):
            return "privato"

    professional_hits = len(re.findall(r"\bprofessionista\b", haystack))
    private_hits = len(re.findall(r"\bprivato\b", haystack))
    if professional_hits >= 2 and private_hits == 0:
        return "professionista"
    if private_hits >= 2 and professional_hits == 0:
        return "privato"
    return ""


def _classify_idealista_publisher_kind_from_signals(
    *,
    body_text: str,
    has_professional_profile_link: bool,
) -> str:
    if has_professional_profile_link:
        return "professionista"
    return _classify_idealista_publisher_kind(body_text)


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


def _normalize_channel_label(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return _DEFAULT_BROWSER_LABEL
    return _LEGACY_BROWSER_CHANNEL_ALIASES.get(raw, raw)


def _channel_to_label(channel: str | None) -> str:
    return _normalize_channel_label(channel)


def _label_to_channel(label: str) -> str | None:
    normalized = _normalize_channel_label(label)
    return None if normalized == _DEFAULT_BROWSER_LABEL else normalized


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
        "last_attempt_channel": "",
        "last_block_family": "",
        "last_block_code": "",
        "warmup_active": True,
        "warmup_started_utc": "",
        "warmup_completed_utc": "",
        "warmup_failures": 0,
        "warmup_last_failures": 0,
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
        "probe_after_utc": "",
        "probe_attempts": 0,
    }


def _load_guard_state(path: Path) -> dict:
    default = {"version": _GUARD_STATE_VERSION, "last_channel": _DEFAULT_BROWSER_LABEL, "sites": {}}
    try:
        if not path.exists():
            return default
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return default
        sites = raw.get("sites", {})
        if not isinstance(sites, dict):
            sites = {}
        last_channel = _normalize_channel_label(raw.get("last_channel"))
        if last_channel not in _CHANNEL_LABELS:
            last_channel = _DEFAULT_BROWSER_LABEL
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


def _prune_debug_artifacts(
    *,
    debug_dir: Path,
    logger,
    now_epoch: float | None = None,
    retention_sec: int = _LIVE_DEBUG_RETENTION_SEC,
    max_files: int = _LIVE_DEBUG_MAX_FILES,
) -> int:
    if not debug_dir.exists():
        return 0
    now_ts = time.time() if now_epoch is None else float(now_epoch)
    candidates: list[tuple[float, Path]] = []
    for path in debug_dir.iterdir():
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        candidates.append((float(stat.st_mtime), path))
    if not candidates:
        return 0

    removed = 0
    stale_cutoff = now_ts - max(0, int(retention_sec))
    for mtime, path in list(candidates):
        if mtime >= stale_cutoff:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    if removed:
        candidates = [(mtime, path) for mtime, path in candidates if path.exists()]

    max_count = max(1, int(max_files))
    if len(candidates) > max_count:
        candidates.sort(key=lambda item: item[0], reverse=True)
        for _, path in candidates[max_count:]:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass

    if removed:
        logger.info(
            "Pruned live debug artifacts. removed=%s dir=%s retention_sec=%s max_files=%s",
            removed,
            debug_dir,
            retention_sec,
            max_count,
        )
    return removed


def service_runtime_site_slot_snapshot(
    runtime: LiveFetchServiceRuntime,
    *,
    now_monotonic: float | None = None,
) -> dict[str, dict[str, object]]:
    now_value = time.monotonic() if now_monotonic is None else float(now_monotonic)
    summary: dict[str, dict[str, object]] = {}
    for slot in runtime.session_slots.values():
        try:
            reuse_count = int(getattr(slot, "reuse_count", 0) or 0)
        except (TypeError, ValueError):
            reuse_count = 0
        try:
            created_monotonic = float(getattr(slot, "created_monotonic", now_value) or now_value)
        except (TypeError, ValueError):
            created_monotonic = now_value
        entry = summary.setdefault(
            slot.site,
            {
                "site": slot.site,
                "owner_count": 0,
                "max_reuse_count": 0,
                "max_age_sec": 0,
                "channel_label": slot.channel_label,
            },
        )
        entry["owner_count"] = int(entry["owner_count"]) + 1
        entry["max_reuse_count"] = max(int(entry["max_reuse_count"]), reuse_count)
        age_sec = max(0, int(now_value - created_monotonic))
        entry["max_age_sec"] = max(int(entry["max_age_sec"]), age_sec)
        if reuse_count >= int(entry["max_reuse_count"]):
            entry["channel_label"] = slot.channel_label
    return summary


def _prune_guard_state_sites(state: dict, search_urls: list[str]) -> list[str]:
    sites = state.get("sites")
    if not isinstance(sites, dict):
        state["sites"] = {}
        return []
    allowed_sites = {_site_key_from_url(url) for url in search_urls if url}
    if not allowed_sites:
        return []
    removed = sorted(site for site in list(sites) if site not in allowed_sites)
    for site in removed:
        sites.pop(site, None)
    return removed


def _site_state(state: dict, site: str) -> dict:
    sites = state.setdefault("sites", {})
    entry = sites.get(site)
    if not isinstance(entry, dict):
        entry = _new_guard_site_entry()
    for key, value in _new_guard_site_entry().items():
        entry.setdefault(key, value)
    sites[site] = entry
    return entry


def _is_warmup_entry(entry: dict) -> bool:
    raw = entry.get("warmup_active")
    if isinstance(raw, bool):
        return raw
    return not bool(str(entry.get("last_success_utc") or "").strip())


def _guard_phase_label(entry: dict) -> str:
    return "warmup" if _is_warmup_entry(entry) else "stable"


def _is_datadome_interstitial(*, current_url: str = "", html: str = "", body_text: str = "") -> bool:
    haystack = "\n".join([current_url, html, body_text]).lower()
    return "geo.captcha-delivery.com/interstitial" in haystack or "captcha-delivery.com/interstitial" in haystack


def _blocked_family_from_outcome(outcome: FetchOutcome) -> str:
    if outcome.code == "interstitial_datadome":
        return "interstitial"
    if outcome.code in {"hard_block", "hard_block_http_status"} or outcome.hard_block:
        return "hard_block"
    if outcome.challenge_visible:
        return "challenge"
    if outcome.tier == "blocked":
        return "blocked"
    return ""


def _cooldown_remaining_sec(state: dict, site: str, now: datetime) -> int:
    entry = _site_state(state, site)
    until = _parse_utc_iso(str(entry.get("cooldown_until_utc") or ""))
    if until is None:
        return 0
    delta = int((until - now).total_seconds())
    return delta if delta > 0 else 0


def _build_default_risk_budget(*, search_urls: list[str], extraction: ExtractionFields) -> RiskBudget:
    return RiskBudget(
        page_budget=max(1, len(search_urls)),
        detail_budget=_IDEALISTA_PRIVATE_ONLY_DETAIL_MAX_CHECKS if extraction.private_only_ads else 0,
        identity_budget=0,
        retry_budget=1,
        cooldown_budget=1,
        manual_assist_threshold=1,
    )


def _interstitial_probe_delay_sec(*, base_sec: int, cooldown_sec: int) -> int:
    if cooldown_sec <= 0:
        return 0
    baseline = max(600, min(1200, max(1, base_sec // 2)))
    return min(cooldown_sec, baseline)


def _is_interstitial_probe_due(entry: dict, now: datetime) -> bool:
    if str(entry.get("last_block_family") or "").strip().lower() != "interstitial":
        return False
    due_at = _parse_utc_iso(str(entry.get("probe_after_utc") or ""))
    if due_at is None:
        return False
    return due_at <= now


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


def _session_age_sec(entry: dict, now: datetime) -> int:
    candidates = (
        _parse_utc_iso(str(entry.get("warmup_started_utc") or "")),
        _parse_utc_iso(str(entry.get("last_success_utc") or "")),
        _parse_utc_iso(str(entry.get("last_attempt_utc") or "")),
    )
    for candidate in candidates:
        if candidate is not None:
            return max(0, int((now - candidate).total_seconds()))
    return 0


def _state_transition_label(*, entry: dict, outcome: FetchOutcome) -> str:
    if outcome.tier == "cooling":
        return "cooldown"
    if outcome.tier == "healthy":
        return _guard_phase_label(entry)
    if outcome.tier == "suspect":
        return "suspect"
    if outcome.tier == "degraded":
        return "degraded"
    if outcome.challenge_visible or outcome.code in {"interstitial_datadome", "challenge_visible"}:
        return "challenge_seen"
    if outcome.tier == "blocked":
        return "blocked"
    return outcome.tier or "unknown"


def _risk_pause_reason(*, outcome: FetchOutcome, decision: GuardDecision) -> str:
    if outcome.code == "cooldown_active" or decision.action == "skip_due_cooldown":
        return "cooldown_active"
    if outcome.code == "interstitial_datadome":
        return "challenge_seen_first" if decision.cooldown_sec > 0 else "challenge_seen"
    if outcome.code == "challenge_visible":
        return "challenge_seen"
    if "cooldown" in decision.action and outcome.tier == "suspect":
        return "suspect_cooldown"
    if "cooldown" in decision.action and outcome.tier == "degraded":
        return "degraded_cooldown"
    if "cooldown" in decision.action and outcome.tier == "blocked":
        return "blocked_cooldown"
    if outcome.tier == "suspect":
        return "suspect_observe"
    return ""


def _record_site_outcome_tier(site_tiers: dict[str, str], site: str, outcome: FetchOutcome) -> None:
    severity = {"healthy": 0, "suspect": 1, "degraded": 2, "cooling": 3, "blocked": 4}
    current = str(site_tiers.get(site, "") or "")
    current_score = severity.get(current, -1)
    next_tier = str(outcome.tier or "healthy")
    next_score = severity.get(next_tier, -1)
    if next_score >= current_score:
        site_tiers[site] = next_tier


def _build_telemetry_snapshot(
    *,
    site: str,
    entry: dict,
    outcome: FetchOutcome,
    decision: GuardDecision,
    now: datetime,
    browser_mode: str,
    channel_label: str,
    identity_switch: int,
    attempt_stats: FetchAttemptStats,
    manual_assist_used: bool,
    assist_entry_mode: str = "",
) -> TelemetrySnapshot:
    return TelemetrySnapshot(
        site=site,
        browser_mode=browser_mode,
        channel_label=channel_label,
        identity_switch=identity_switch,
        session_age_sec=_session_age_sec(entry, now),
        detail_touch_count=attempt_stats.detail_touch_count,
        retry_count=attempt_stats.retry_count,
        risk_pause_reason=_risk_pause_reason(outcome=outcome, decision=decision),
        outcome_tier=outcome.tier,
        outcome_code=outcome.code,
        cooldown_origin=str(entry.get("last_block_family") or ""),
        manual_assist_used=manual_assist_used,
        state_transition=_state_transition_label(entry=entry, outcome=outcome),
        assist_entry_mode=assist_entry_mode,
    )


def _allow_alternate_browser_retry(
    *,
    cards: list[dict],
    outcome: FetchOutcome,
    requested_channel: str | None,
    rotation_mode: str,
    alternate_candidates: list[str | None],
    risk_budget: RiskBudget,
    identity_switch_count: int,
) -> tuple[bool, str]:
    if cards:
        return (False, "cards_present")
    if outcome.tier != "blocked" or outcome.code not in {"interstitial_datadome", "challenge_visible"}:
        return (False, "outcome_not_retryable")
    if requested_channel is not None or rotation_mode != "round_robin":
        return (False, "browser_rotation_not_auto")
    if not alternate_candidates:
        return (False, "no_alternate_candidates")
    if identity_switch_count >= risk_budget.identity_budget:
        return (False, "identity_budget_exhausted")
    return (True, "")


def _remaining_detail_budget(*, risk_budget: RiskBudget, run_risk: RunRiskState) -> int:
    return max(0, risk_budget.detail_budget - run_risk.detail_used)


def _allow_transient_retry(
    *,
    outcome: FetchOutcome,
    risk_budget: RiskBudget,
    run_risk: RunRiskState,
) -> tuple[bool, str]:
    if not outcome.retryable:
        return (False, "outcome_not_retryable")
    if run_risk.retries_used >= risk_budget.retry_budget:
        return (False, "retry_budget_exhausted")
    return (True, "")


def _mark_assist_required(run_risk: RunRiskState, reason: str) -> None:
    run_risk.assist_required = True
    run_risk.assist_reason = run_risk.assist_reason or reason
    run_risk.current_state = "assist_required"
    run_risk.stop_requested = True
    run_risk.stop_reason = run_risk.stop_reason or reason


def _advance_run_state(
    *,
    entry: dict,
    outcome: FetchOutcome,
    decision: GuardDecision,
    run_risk: RunRiskState,
) -> tuple[str, str]:
    previous_state = run_risk.current_state
    if run_risk.assist_required:
        run_risk.current_state = "assist_required"
        return (previous_state, run_risk.current_state)

    if outcome.code in {"interstitial_datadome", "challenge_visible"} or outcome.challenge_visible:
        run_risk.challenge_count += 1
        run_risk.degraded_streak = 0
        run_risk.current_state = "challenge_seen"
        if run_risk.challenge_count >= 2:
            _mark_assist_required(run_risk, "challenge_repeat")
        return (previous_state, run_risk.current_state)

    if outcome.tier == "healthy":
        run_risk.degraded_streak = 0
        run_risk.challenge_count = 0
        run_risk.current_state = _guard_phase_label(entry)
        return (previous_state, run_risk.current_state)

    if outcome.tier == "suspect":
        run_risk.current_state = "suspect"
        return (previous_state, run_risk.current_state)

    if outcome.tier == "degraded":
        run_risk.degraded_streak += 1
        run_risk.current_state = "degraded"
        if run_risk.degraded_streak >= 2:
            _mark_assist_required(run_risk, "persistent_degraded")
        return (previous_state, run_risk.current_state)

    if outcome.tier == "cooling":
        run_risk.current_state = "cooldown"
        return (previous_state, run_risk.current_state)

    if outcome.tier == "blocked":
        run_risk.current_state = "blocked"
        return (previous_state, run_risk.current_state)

    return (previous_state, run_risk.current_state)


def _consume_cooldown_budget(
    *,
    outcome: FetchOutcome,
    decision: GuardDecision,
    risk_budget: RiskBudget,
    run_risk: RunRiskState,
) -> bool:
    if outcome.tier != "cooling" and decision.cooldown_sec <= 0:
        return False
    run_risk.cooldown_used += 1
    if run_risk.cooldown_used > risk_budget.cooldown_budget:
        _mark_assist_required(run_risk, "cooldown_budget_exceeded")
        return True
    return False


def _log_run_risk_state(*, logger, site: str, url: str, previous_state: str, run_risk: RunRiskState) -> None:
    if previous_state == run_risk.current_state and not run_risk.assist_required:
        return
    logger.warning(
        "Run risk state. site=%s state=%s previous_state=%s assist_required=%s assist_reason=%s stop_requested=%s stop_reason=%s url=%s",
        site,
        run_risk.current_state,
        previous_state or "none",
        run_risk.assist_required,
        run_risk.assist_reason or "none",
        run_risk.stop_requested,
        run_risk.stop_reason or "none",
        url,
    )


def _register_site_session_replace(run_risk: RunRiskState, *, site: str, replaced_slots: int) -> tuple[int, str]:
    if replaced_slots <= 0:
        return (0, run_risk.current_state)
    current = int(run_risk.site_owner_replace_counts.get(site, 0))
    current += replaced_slots
    run_risk.site_owner_replace_counts[site] = current
    if current >= 2:
        _mark_assist_required(run_risk, "same_site_owner_churn")
        return (current, run_risk.current_state)
    if not run_risk.assist_required:
        run_risk.current_state = "suspect"
    return (current, run_risk.current_state)


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
    if _is_datadome_interstitial(html=html, body_text=body_text):
        return FetchOutcome(
            tier="blocked",
            code="interstitial_datadome",
            http_status=response_status,
            detail=detail,
            challenge_visible=True,
        )
    if response_status in _HTTP_BLOCK_STATUSES:
        return FetchOutcome(
            tier="blocked",
            code="hard_block_http_status",
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
    was_warmup = _is_warmup_entry(entry)
    transition = previous_tier != outcome.tier or previous_code != outcome.code

    entry["warmup_active"] = was_warmup
    if was_warmup and not str(entry.get("warmup_started_utc") or "").strip():
        entry["warmup_started_utc"] = now.isoformat()
    entry["last_attempt_utc"] = now.isoformat()
    entry["last_outcome_tier"] = outcome.tier
    entry["last_outcome_code"] = outcome.code
    entry["last_outcome_detail"] = (outcome.detail or "")[:240]
    blocked_family = _blocked_family_from_outcome(outcome)

    if outcome.tier == "cooling":
        return GuardDecision(
            action="skip_due_cooldown",
            transition=transition,
            previous_tier=previous_tier,
            previous_code=previous_code,
        )

    entry["last_attempt_channel"] = channel_label
    entry["last_block_family"] = blocked_family
    entry["last_block_code"] = outcome.code if blocked_family else ""

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
        entry["last_block_family"] = ""
        entry["last_block_code"] = ""
        entry["probe_after_utc"] = ""
        entry["probe_attempts"] = 0
        warmup_failures = int(entry.get("warmup_failures") or 0)
        if was_warmup:
            entry["warmup_last_failures"] = warmup_failures
        entry["warmup_failures"] = 0
        if was_warmup:
            entry["warmup_active"] = False
            entry["warmup_completed_utc"] = now.isoformat()
        entry["strikes"] = 0 if success_streak >= 2 else max(0, previous_strikes - 1)
        if was_problematic:
            entry["last_recovery_utc"] = now.isoformat()
        return GuardDecision(
            action=(
                "warmup_recovered"
                if was_warmup and was_problematic
                else "warmup_exit_success"
                if was_warmup
                else "recovered"
                if was_problematic
                else "healthy"
            ),
            transition=transition,
            recovered=was_problematic,
            previous_tier=previous_tier,
            previous_code=previous_code,
        )

    entry["consecutive_successes"] = 0
    entry["consecutive_failures"] = int(entry.get("consecutive_failures") or 0) + 1
    entry["last_reason"] = outcome.code
    if was_warmup:
        entry["warmup_failures"] = int(entry.get("warmup_failures") or 0) + 1

    if outcome.tier == "blocked":
        blocks = int(entry.get("consecutive_blocks") or 0) + 1
        entry["consecutive_blocks"] = blocks
        entry["consecutive_suspect"] = 0
        if was_warmup and int(entry.get("warmup_failures") or 0) <= 1:
            entry["strikes"] = 0
            entry["cooldown_until_utc"] = ""
            return GuardDecision(
                action="warmup_observe_blocked",
                transition=transition,
                previous_tier=previous_tier,
                previous_code=previous_code,
            )
        strikes = previous_strikes + 1 if not was_warmup else max(1, previous_strikes + 1)
        if was_warmup:
            cooldown = min(max_sec, max(120, base_sec // 3) * min(3, strikes))
            action = "warmup_cooldown_block"
        else:
            cooldown = min(max_sec, base_sec * (2 ** max(0, strikes - 1)))
            action = "apply_cooldown_block"
        entry["strikes"] = strikes
        entry["cooldown_until_utc"] = (now + timedelta(seconds=cooldown)).isoformat()
        if blocked_family == "interstitial":
            probe_delay = _interstitial_probe_delay_sec(base_sec=base_sec, cooldown_sec=cooldown)
            entry["probe_after_utc"] = (now + timedelta(seconds=probe_delay)).isoformat() if probe_delay > 0 else ""
            entry["probe_attempts"] = 0
        else:
            entry["probe_after_utc"] = ""
            entry["probe_attempts"] = 0
        return GuardDecision(
            action=action,
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
            if was_warmup:
                cooldown = min(max_sec, max(60, base_sec // 4) * min(3, suspect_streak - 1))
                action = "warmup_cooldown_suspect"
            else:
                cooldown = min(max_sec, max(90, base_sec // 3) * min(3, suspect_streak - 1))
                action = "apply_cooldown_suspect"
            entry["strikes"] = max(previous_strikes, 1)
            entry["cooldown_until_utc"] = (now + timedelta(seconds=cooldown)).isoformat()
            return GuardDecision(
                action=action,
                cooldown_sec=cooldown,
                transition=transition,
                previous_tier=previous_tier,
                previous_code=previous_code,
            )
        return GuardDecision(
            action="warmup_observe_suspect" if was_warmup else "observe_suspect",
            transition=transition,
            previous_tier=previous_tier,
            previous_code=previous_code,
        )

    entry["consecutive_suspect"] = 0
    if outcome.code in {"timeout_network", "network_issue", "unexpected_error"} and int(entry.get("consecutive_failures") or 0) >= 2:
        if was_warmup:
            cooldown = min(max_sec, max(90, base_sec // 5) * min(3, int(entry.get("consecutive_failures") or 0) - 1))
            action = "warmup_cooldown_degraded"
        else:
            cooldown = min(max_sec, max(120, base_sec // 4) * min(3, int(entry.get("consecutive_failures") or 0) - 1))
            action = "apply_cooldown_degraded"
        entry["strikes"] = max(previous_strikes, 1)
        entry["cooldown_until_utc"] = (now + timedelta(seconds=cooldown)).isoformat()
        return GuardDecision(
            action=action,
            cooldown_sec=cooldown,
            transition=transition,
            previous_tier=previous_tier,
            previous_code=previous_code,
        )
    return GuardDecision(
        action="warmup_observe_degraded" if was_warmup else "observe_degraded",
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


def _log_guard_decision(
    *,
    logger,
    site: str,
    url: str,
    outcome: FetchOutcome,
    decision: GuardDecision,
    entry: dict,
    browser_mode: str = _BROWSER_MODE_MANAGED_STABLE,
    identity_switch: int = 0,
    attempt_stats: FetchAttemptStats | None = None,
    manual_assist_used: bool = False,
    assist_entry_mode: str = "",
) -> TelemetrySnapshot:
    snapshot = _build_telemetry_snapshot(
        site=site,
        entry=entry,
        outcome=outcome,
        decision=decision,
        now=_utc_now(),
        browser_mode=browser_mode,
        channel_label=str(entry.get("last_attempt_channel") or entry.get("last_valid_channel") or "unknown"),
        identity_switch=identity_switch,
        attempt_stats=attempt_stats or FetchAttemptStats(),
        manual_assist_used=manual_assist_used,
        assist_entry_mode=assist_entry_mode,
    )
    if decision.action in {"warmup_exit_success", "warmup_recovered"}:
        logger.info(
            "Site guard warmup completed. site=%s channel=%s action=%s previous=%s/%s now=%s/%s warmup_failures=%s url=%s",
            site,
            entry.get("last_attempt_channel") or entry.get("last_valid_channel") or "unknown",
            decision.action,
            decision.previous_tier or "n/a",
            decision.previous_code or "n/a",
            outcome.tier,
            outcome.code,
            entry.get("warmup_last_failures", entry.get("warmup_failures")),
            url,
        )
        logger.info(
            "Site guard telemetry. site=%s browser_mode=%s state=%s retry_count=%s detail_touch_count=%s identity_switch=%s risk_pause_reason=%s session_age_sec=%s cooldown_origin=%s url=%s",
            snapshot.site,
            snapshot.browser_mode,
            snapshot.state_transition,
            snapshot.retry_count,
            snapshot.detail_touch_count,
            snapshot.identity_switch,
            snapshot.risk_pause_reason or "none",
            snapshot.session_age_sec,
            snapshot.cooldown_origin or "none",
            url,
        )
        return snapshot
    phase = _guard_phase_label(entry)
    if phase == "warmup":
        log = logger.warning if outcome.tier in {"suspect", "blocked"} or decision.cooldown_sec > 0 else logger.info
        log(
            "Site guard warmup outcome. site=%s channel=%s tier=%s code=%s action=%s warmup_failures=%s strikes=%s cooldown_sec=%s url=%s",
            site,
            entry.get("last_attempt_channel") or "unknown",
            outcome.tier,
            outcome.code,
            decision.action,
            entry.get("warmup_failures"),
            entry.get("strikes"),
            decision.cooldown_sec,
            url,
        )
        if outcome.tier in {"suspect", "blocked"} and decision.cooldown_sec == 0:
            logger.info(
                "Warmup hint. site=%s first-run state detected; retry Run Once before using Reset Site Guard. url=%s",
                site,
                url,
            )
        elif decision.cooldown_sec > 0:
            logger.info(
                "Warmup hint. site=%s first-run still active; a shorter cooldown was applied conservatively. url=%s",
                site,
                url,
            )
        logger.info(
            "Site guard telemetry. site=%s browser_mode=%s state=%s retry_count=%s detail_touch_count=%s identity_switch=%s risk_pause_reason=%s session_age_sec=%s cooldown_origin=%s url=%s",
            snapshot.site,
            snapshot.browser_mode,
            snapshot.state_transition,
            snapshot.retry_count,
            snapshot.detail_touch_count,
            snapshot.identity_switch,
            snapshot.risk_pause_reason or "none",
            snapshot.session_age_sec,
            snapshot.cooldown_origin or "none",
            url,
        )
        return snapshot
    if outcome.tier == "healthy" and decision.recovered:
        logger.info(
            "Site guard recovery. site=%s channel=%s previous=%s/%s now=%s/%s strikes=%s success_streak=%s url=%s",
            site,
            entry.get("last_valid_channel") or entry.get("last_attempt_channel") or "unknown",
            decision.previous_tier or "n/a",
            decision.previous_code or "n/a",
            outcome.tier,
            outcome.code,
            entry.get("strikes"),
            entry.get("consecutive_successes"),
            url,
        )
        logger.info(
            "Site guard telemetry. site=%s browser_mode=%s state=%s retry_count=%s detail_touch_count=%s identity_switch=%s risk_pause_reason=%s session_age_sec=%s cooldown_origin=%s url=%s",
            snapshot.site,
            snapshot.browser_mode,
            snapshot.state_transition,
            snapshot.retry_count,
            snapshot.detail_touch_count,
            snapshot.identity_switch,
            snapshot.risk_pause_reason or "none",
            snapshot.session_age_sec,
            snapshot.cooldown_origin or "none",
            url,
        )
        return snapshot
    log = logger.warning if outcome.tier in {"suspect", "blocked"} or decision.cooldown_sec > 0 else logger.info
    log(
        "Site guard outcome. site=%s channel=%s tier=%s code=%s action=%s strikes=%s cooldown_sec=%s block_family=%s url=%s",
        site,
        entry.get("last_attempt_channel") or entry.get("last_valid_channel") or "unknown",
        outcome.tier,
        outcome.code,
        decision.action,
        entry.get("strikes"),
        decision.cooldown_sec,
        entry.get("last_block_family") or "none",
        url,
    )
    logger.info(
        "Site guard telemetry. site=%s browser_mode=%s state=%s retry_count=%s detail_touch_count=%s identity_switch=%s risk_pause_reason=%s session_age_sec=%s cooldown_origin=%s url=%s",
        snapshot.site,
        snapshot.browser_mode,
        snapshot.state_transition,
        snapshot.retry_count,
        snapshot.detail_touch_count,
        snapshot.identity_switch,
        snapshot.risk_pause_reason or "none",
        snapshot.session_age_sec,
        snapshot.cooldown_origin or "none",
        url,
    )
    return snapshot


def _rotated_channel_candidates(
    *,
    requested_channel: str | None,
    rotation_mode: str,
    state: dict | None,
    site: str = "",
) -> list[str | None]:
    if rotation_mode != "round_robin":
        return [requested_channel]
    if requested_channel is not None:
        return [requested_channel]
    entry = _site_state(state, site) if state is not None and site else None
    base_labels = list(_SITE_DEFAULT_CHANNELS.get(site, (_DEFAULT_BROWSER_LABEL,)))
    global_last = ""
    if state is not None:
        global_last = _normalize_channel_label(state.get("last_channel"))
    if global_last not in _CHANNEL_LABELS:
        global_last = ""
    last_valid = _normalize_channel_label((entry or {}).get("last_valid_channel"))
    if last_valid not in _CHANNEL_LABELS:
        last_valid = ""
    blocked_label = ""
    if entry is not None and str(entry.get("last_block_family") or "").strip().lower() in {
        "interstitial",
        "hard_block",
        "challenge",
        "blocked",
    }:
        blocked_label = _normalize_channel_label(entry.get("last_attempt_channel"))
        if blocked_label not in _CHANNEL_LABELS:
            blocked_label = ""

    labels: list[str] = []
    if last_valid and last_valid != blocked_label:
        labels.append(last_valid)
    for label in base_labels:
        if label != blocked_label:
            labels.append(label)
    if global_last and global_last != blocked_label:
        labels.append(global_last)
    if blocked_label:
        labels.append(blocked_label)
    labels.append(_DEFAULT_BROWSER_LABEL)
    deduped: list[str] = []
    for label in labels:
        if label in _CHANNEL_LABELS and label not in deduped:
            deduped.append(label)
    labels = deduped or [_DEFAULT_BROWSER_LABEL]
    return [_label_to_channel(label) for label in labels]


async def _close_browser_handles(*, context, browser) -> None:
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


async def _close_browser_slots(slots: dict[str, BrowserSessionSlot]) -> None:
    for slot in slots.values():
        await _close_browser_handles(context=slot.context, browser=slot.browser)


async def _ensure_service_runtime(runtime: LiveFetchServiceRuntime):
    if runtime.playwright is None:
        runtime.playwright = await async_playwright().start()
    return runtime.playwright


async def close_live_fetch_service_runtime(runtime: LiveFetchServiceRuntime) -> None:
    if runtime.session_slots:
        await _close_browser_slots(runtime.session_slots)
        runtime.session_slots.clear()
    if runtime.playwright is not None:
        try:
            await runtime.playwright.stop()
        finally:
            runtime.playwright = None


async def recycle_live_fetch_site_runtime(runtime: LiveFetchServiceRuntime, site: str) -> int:
    if not site.strip():
        return 0
    if not runtime.session_slots:
        return 0
    return await _prune_site_session_slots(runtime.session_slots, site=site, preserve_owner="")


def _site_slot_keys(slots: dict[str, BrowserSessionSlot], site: str, preserve_owner: str = "") -> list[str]:
    keys: list[str] = []
    for owner_key, slot in slots.items():
        if slot.site != site:
            continue
        if preserve_owner and owner_key == preserve_owner:
            continue
        keys.append(owner_key)
    return keys


async def _prune_site_session_slots(
    slots: dict[str, BrowserSessionSlot],
    *,
    site: str,
    preserve_owner: str,
) -> int:
    removed = 0
    for owner_key in _site_slot_keys(slots, site, preserve_owner):
        slot = slots.pop(owner_key, None)
        if slot is None:
            continue
        await _close_browser_handles(context=slot.context, browser=slot.browser)
        removed += 1
    return removed


def _filter_available_channel_candidates(candidates: list[str | None]) -> tuple[list[str | None], list[str]]:
    skipped_labels: list[str] = []
    filtered_candidates: list[str | None] = []
    for candidate in candidates:
        label = _channel_to_label(candidate)
        if _is_channel_available(label):
            filtered_candidates.append(candidate)
        else:
            skipped_labels.append(label)
    return (filtered_candidates or candidates), skipped_labels


def _alternate_browser_retry_candidates(
    channel_candidates: list[str | None],
    *,
    current_label: str,
) -> list[str | None]:
    labels: list[str] = []
    for candidate in channel_candidates:
        label = _channel_to_label(candidate)
        if label == current_label:
            continue
        if label in _CHANNEL_LABELS and label not in labels:
            labels.append(label)
    return [_label_to_channel(label) for label in labels]


def _resolve_channel_executable_path(label: str) -> Path | None:
    if _normalize_channel_label(label) != _DEFAULT_BROWSER_LABEL:
        return None
    try:
        return Path(camoufox_launch_path())
    except Exception:
        return None


def _camoufox_screen_constraints() -> Screen:
    return Screen(
        min_width=1920,
        max_width=1920,
        min_height=1080,
        max_height=1080,
    )


def _camoufox_launch_kwargs(
    *,
    headless: bool,
    executable_path: Path | None,
    persistent_profile_dir: Path | None = None,
) -> dict[str, object]:
    launch_kwargs: dict[str, object] = {
        "headless": headless,
        "humanize": True,
        "locale": _CAMOUFOX_DEFAULT_LOCALE,
        "os": _CAMOUFOX_DEFAULT_OS,
        "screen": _camoufox_screen_constraints(),
        # The scraper targets Italian housing portals, so we keep the Intl timezone
        # aligned with the default locale/profile instead of leaking a generic host value.
        "config": {"timezone": _CAMOUFOX_DEFAULT_TIMEZONE},
        "i_know_what_im_doing": True,
    }
    if persistent_profile_dir is not None:
        launch_kwargs["persistent_context"] = True
        launch_kwargs["user_data_dir"] = str(persistent_profile_dir)
    if executable_path is not None:
        launch_kwargs["executable_path"] = str(executable_path)
    return launch_kwargs


async def _launch_browser_session(
    *,
    pw,
    site: str,
    profile_dir: str | None,
    requested_channel: str | None,
    rotation_mode: str,
    guard_state: dict | None,
    headless: bool,
    logger,
    candidate_override: list[str | None] | None = None,
) -> tuple[object | None, object, object, str]:
    launch_error: Exception | None = None
    browser = None
    context = None
    page = None
    channel_candidates = (
        list(candidate_override)
        if candidate_override is not None
        else _rotated_channel_candidates(
            requested_channel=requested_channel,
            rotation_mode=rotation_mode,
            state=guard_state,
            site=site,
        )
    )
    if requested_channel is None and rotation_mode == "round_robin":
        channel_candidates, skipped_labels = _filter_available_channel_candidates(channel_candidates)
        if skipped_labels:
            logger.info(
                "Auto browser channel unavailable on host. site=%s skipped=%s",
                site,
                ",".join(skipped_labels),
            )
            logger.info(
                "Site guard channel candidates. site=%s candidates=%s",
                site,
                ",".join(_channel_to_label(x) for x in channel_candidates),
            )
    for candidate in channel_candidates:
        channel_label = _channel_to_label(candidate)
        executable_path = _resolve_channel_executable_path(channel_label)
        try:
            if profile_dir:
                p_base = Path(profile_dir).expanduser()
                p = _session_profile_root(str(p_base), site, channel_label) or _profile_dir_for_site_channel(p_base, site, channel_label)
                p.mkdir(parents=True, exist_ok=True)
                launch_persistent_kwargs = _camoufox_launch_kwargs(
                    headless=headless,
                    executable_path=executable_path,
                    persistent_profile_dir=p,
                )
                context = await AsyncNewBrowser(pw, **launch_persistent_kwargs)
                logger.info(
                    "Using persistent Camoufox profile. site=%s profile=%s channel=%s launcher=%s",
                    site,
                    p,
                    channel_label,
                    "camoufox_path" if executable_path is not None else "camoufox_default",
                )
            else:
                launch_kwargs = _camoufox_launch_kwargs(
                    headless=headless,
                    executable_path=executable_path,
                )
                browser = await AsyncNewBrowser(pw, **launch_kwargs)
                context = await browser.new_context()
                logger.info(
                    "Using ephemeral Camoufox context. site=%s channel=%s launcher=%s",
                    site,
                    channel_label,
                    "camoufox_path" if executable_path is not None else "camoufox_default",
                )
            page = context.pages[0] if context.pages else await context.new_page()
            return browser, context, page, channel_label
        except Exception as exc:
            launch_error = exc
            details = str(exc)
            missing_camoufox = isinstance(exc, CamoufoxNotInstalled) or "camoufox fetch" in details.lower()
            if missing_camoufox:
                logger.info(
                    "Camoufox browser not installed. site=%s channel=%s hint=python -m camoufox fetch",
                    site,
                    channel_label,
                )
            else:
                logger.warning(
                    "Browser channel launch failed. site=%s channel=%s details=%s",
                    site,
                    channel_label,
                    details.splitlines()[0] if details else repr(exc),
                )
            await _close_browser_handles(context=context, browser=browser)
            context = None
            browser = None
            page = None
    if launch_error is not None:
        raise launch_error
    raise RuntimeError(f"Unable to start browser context for site={site}.")


def _is_channel_available(label: str) -> bool:
    return _resolve_channel_executable_path(label) is not None


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
    Keep isolated user-data dirs per browser identity.
    """
    base_name = base_dir.name.strip().lower()
    if base_name == channel_label:
        return base_dir
    if base_name in _CHANNEL_LABELS:
        return base_dir.parent / channel_label
    return base_dir / channel_label


def _profile_dir_for_site(base_dir: Path, site: str) -> Path:
    base_name = base_dir.name.strip().lower()
    site_slug = _slug(site)
    if base_name == site_slug:
        return base_dir
    if base_name in _CHANNEL_LABELS:
        return base_dir.parent / site_slug
    return base_dir / site_slug


def _profile_dir_for_site_channel(base_dir: Path, site: str, channel_label: str) -> Path:
    return _profile_dir_for_channel(_profile_dir_for_site(base_dir, site), channel_label)


def _session_profile_root(profile_dir: str | None, site: str, channel_label: str) -> Path | None:
    if not profile_dir:
        return None
    return _profile_dir_for_site_channel(Path(profile_dir).expanduser(), site, channel_label)


def _session_owner_key(*, site: str, channel_label: str, profile_root: Path | None) -> str:
    profile_part = str(profile_root) if profile_root is not None else "ephemeral"
    return f"{site}|{channel_label}|{profile_part}"


def _session_identity(*, site: str, channel_label: str, profile_dir: str | None) -> tuple[str, Path | None]:
    profile_root = _session_profile_root(profile_dir, site, channel_label)
    return (_session_owner_key(site=site, channel_label=channel_label, profile_root=profile_root), profile_root)


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


def _challenge_auto_wait_sec(*, site: str, captcha_wait_sec: int, flow_code: str) -> int:
    base = min(12, max(6, int(captcha_wait_sec // 2)))
    if flow_code == "interstitial_datadome":
        extra = 2 if site == "idealista" else 0
        return min(14, max(8, base + extra))
    return base


async def _wait_until_verification_cleared(page, *, site: str, timeout_sec: int, logger) -> bool:
    elapsed = 0
    interval = 2
    while elapsed < timeout_sec:
        await asyncio.sleep(interval)
        elapsed += interval
        try:
            body_l = ""
            try:
                body_l = _normalize(await page.locator("body").inner_text()).lower()
            except Exception:
                body_l = ""
            if _is_datadome_interstitial(current_url=page.url, body_text=body_l):
                continue
            if await _has_listing_signals(page, site):
                logger.info("Verification challenge cleared after %s sec.", elapsed)
                return True
            hard_block, block_id = await _is_hard_block_page(page)
            if hard_block:
                suffix = f" block_id={block_id}" if block_id else ""
                logger.warning(
                    "Detected non-interactive hard block while waiting for captcha solve.%s",
                    suffix,
                )
                return False
            if not await _is_likely_captcha(page):
                logger.info("Verification challenge cleared after %s sec.", elapsed)
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
    body_text = ""
    try:
        body_text = await page.locator("body").inner_text()
    except Exception:
        body_text = ""
    if _is_datadome_interstitial(current_url=page.url, html=html or "", body_text=body_text):
        logger.warning(
            "DataDome interstitial detected (%s). url=%s current_url=%s",
            phase,
            search_url,
            page.url,
        )
        if captcha_mode == "stop_and_notify":
            raise LiveFetchBlocked("interstitial_datadome", f"DataDome interstitial detected on {search_url}")
        if not headless:
            auto_wait = _challenge_auto_wait_sec(
                site=site,
                captcha_wait_sec=captcha_wait_sec,
                flow_code="interstitial_datadome",
            )
            logger.info(
                "DataDome interstitial detected (%s). Auto-wait up to %s sec for self-clear.",
                phase,
                auto_wait,
            )
            solved = await _wait_until_verification_cleared(
                page,
                site=site,
                timeout_sec=auto_wait,
                logger=logger,
            )
            if solved:
                return True, "ok"
            logger.warning("DataDome interstitial still active after auto-wait. skip url=%s", search_url)
        return False, "interstitial_datadome"
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
        auto_wait = _challenge_auto_wait_sec(
            site=site,
            captcha_wait_sec=captcha_wait_sec,
            flow_code="challenge_visible",
        )
        logger.info(
            "Captcha/verification challenge detected (%s). Auto-wait up to %s sec for self-clear.",
            phase,
            auto_wait,
        )
        solved = await _wait_until_verification_cleared(
            page,
            site=site,
            timeout_sec=auto_wait,
            logger=logger,
        )
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
        solved = await _wait_until_verification_cleared(
            page,
            site=site,
            timeout_sec=max(10, captcha_wait_sec),
            logger=logger,
        )
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
                (el, payload) => {
                  const {
                    site,
                    idealistaAgencyAttrSelectors,
                    idealistaAgencyTextSelectors,
                  } = payload;
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
                        idealistaAgencyAttrSelectors,
                        "alt",
                      ) ||
                      firstText(idealistaAgencyTextSelectors);
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
                {
                    "site": site,
                    "idealistaAgencyAttrSelectors": list(_IDEALISTA_AGENCY_ATTR_SELECTORS),
                    "idealistaAgencyTextSelectors": list(_IDEALISTA_AGENCY_TEXT_SELECTORS),
                },
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


async def _verify_idealista_private_only_candidates(
    *,
    page,
    cards: list[dict],
    nav_timeout_ms: int,
    detail_budget_remaining: int | None = None,
    db: Database | None = None,
    search_url: str = "",
    logger,
) -> int:
    candidates = [
        card
        for card in cards
        if not _normalize(card.get("agency"))
        and _normalize(card.get("url"))
        and not bool(card.get("_private_only_db_cached"))
    ]
    if not candidates:
        return

    max_checks = min(len(candidates), _IDEALISTA_PRIVATE_ONLY_DETAIL_MAX_CHECKS)
    if detail_budget_remaining is not None:
        max_checks = min(max_checks, max(0, int(detail_budget_remaining)))
    capped = max(0, len(candidates) - max_checks)
    attempted = 0
    verified_private = 0
    flagged_professional = 0
    unresolved = 0
    interrupted = False

    logger.info(
        "Idealista private-only detail verification start. candidates=%s max_checks=%s",
        len(candidates),
        max_checks,
    )

    for index, card in enumerate(candidates[:max_checks], start=1):
        try:
            await page.goto(card["url"], timeout=nav_timeout_ms)
            await page.wait_for_load_state("domcontentloaded", timeout=nav_timeout_ms)
            await page.wait_for_timeout(random.randint(*_IDEALISTA_PRIVATE_ONLY_DETAIL_DELAY_MS))
            await _accept_cookies_if_present(page)
            await _dismiss_intrusive_popups(page, site="idealista", logger=logger)

            html = await page.content()
            if await _is_likely_captcha(page, html):
                interrupted = True
                logger.warning(
                    "Idealista private-only detail verification interrupted by challenge. "
                    "attempted=%s remaining=%s current_url=%s",
                    attempted,
                    max_checks - attempted,
                    page.url,
                )
                break

            professional_profile_links = await page.locator(
                'aside a[href*="/pro/"], [role="complementary"] a[href*="/pro/"], nav a[href*="/pro/"]'
            ).count()
            body_text = await page.locator("body").inner_text()
            attempted += 1
            publisher_kind = _classify_idealista_publisher_kind_from_signals(
                body_text=body_text,
                has_professional_profile_link=professional_profile_links > 0,
            )
            if publisher_kind == "professionista":
                card["agency"] = "Professionista (detail check)"
                if db is not None:
                    db.upsert_private_only_agency(
                        site="idealista",
                        search_url=search_url,
                        ad_id=str(card.get("ad_id") or ""),
                        agency=card["agency"],
                        source="idealista_detail_check",
                    )
                flagged_professional += 1
                logger.info(
                    "Idealista detail verification flagged professional listing. ad_id=%s url=%s",
                    card.get("ad_id") or "",
                    card["url"],
                )
            elif publisher_kind == "privato":
                verified_private += 1
            else:
                unresolved += 1
                logger.info(
                    "Idealista detail verification unresolved listing. ad_id=%s url=%s pro_links=%s",
                    card.get("ad_id") or "",
                    card["url"],
                    professional_profile_links,
                )
        except Exception as exc:
            attempted += 1
            unresolved += 1
            logger.info(
                "Idealista detail verification inconclusive. ad_id=%s url=%s error=%s",
                card.get("ad_id") or "",
                card.get("url") or "",
                type(exc).__name__,
            )

        if index < max_checks and index % _IDEALISTA_PRIVATE_ONLY_DETAIL_BATCH_PAUSE_EVERY == 0:
            await page.wait_for_timeout(random.randint(*_IDEALISTA_PRIVATE_ONLY_DETAIL_BATCH_PAUSE_MS))

    logger.info(
        "Idealista private-only detail verification summary. "
        "candidates=%s attempted=%s flagged_professional=%s verified_private=%s unresolved=%s capped=%s interrupted=%s",
        len(candidates),
        attempted,
        flagged_professional,
        verified_private,
        unresolved,
        capped,
        interrupted,
    )
    return attempted


def _apply_idealista_private_only_db_cache(
    *,
    db: Database | None,
    search_url: str,
    cards: list[dict],
    logger,
) -> None:
    if db is None or not cards:
        return
    candidate_ids = [str(card.get("ad_id") or "").strip() for card in cards if _normalize(card.get("url"))]
    if not candidate_ids:
        return
    cached = db.get_listing_agencies_by_ad_ids(site="idealista", search_url=search_url, ad_ids=candidate_ids)
    if not cached:
        return

    reused_total = 0
    reused_professional = 0
    reused_unknown = 0
    for card in cards:
        ad_id = str(card.get("ad_id") or "").strip()
        if not ad_id or ad_id not in cached:
            continue
        reused_total += 1
        card["_private_only_db_cached"] = True
        cached_agency = cached.get(ad_id, "").strip()
        if cached_agency and not _normalize(card.get("agency")):
            card["agency"] = cached_agency
            reused_professional += 1
        elif not cached_agency:
            reused_unknown += 1

    logger.info(
        "Idealista private-only DB cache reuse. matched=%s reused_professional=%s reused_unknown=%s",
        reused_total,
        reused_professional,
        reused_unknown,
    )


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
    listing_cache_db: Database | None,
    detail_budget_remaining: int | None,
    logger,
) -> tuple[list[dict], FetchOutcome, FetchAttemptStats]:
    attempt_stats = FetchAttemptStats()
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
        return [], FetchOutcome(tier="degraded", code="unsupported_site", http_status=response_status, detail=search_url), attempt_stats

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
        blocked_code = (
            "interstitial_datadome"
            if flow_code == "interstitial_datadome"
            else "hard_block"
            if hard_block or flow_code == "hard_block" or response_status in _HTTP_BLOCK_STATUSES
            else "challenge_visible"
        )
        outcome = FetchOutcome(
            tier="blocked",
            code=blocked_code,
            http_status=response_status,
            detail=f"phase=after_goto url={page.url}",
            challenge_visible=blocked_code in {"challenge_visible", "interstitial_datadome"},
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
        return [], outcome, attempt_stats

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
        blocked_code = (
            "interstitial_datadome"
            if flow_code == "interstitial_datadome"
            else "hard_block"
            if hard_block or flow_code == "hard_block"
            else "challenge_visible"
        )
        outcome = FetchOutcome(
            tier="blocked",
            code=blocked_code,
            http_status=response_status,
            detail=f"phase=after_prepare url={page.url}",
            challenge_visible=blocked_code in {"challenge_visible", "interstitial_datadome"},
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
        return [], outcome, attempt_stats
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
            return [], outcome, attempt_stats
    if site == "idealista" and extraction.private_only_ads and not used_fallback:
        _apply_idealista_private_only_db_cache(
            db=listing_cache_db,
            search_url=search_url,
            cards=cards,
            logger=logger,
        )
        attempt_stats.detail_touch_count = await _verify_idealista_private_only_candidates(
            page=page,
            cards=cards,
            nav_timeout_ms=nav_timeout_ms,
            detail_budget_remaining=detail_budget_remaining,
            db=listing_cache_db,
            search_url=search_url,
            logger=logger,
        )
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
        return cards, outcome, attempt_stats
    return [], FetchOutcome(tier="healthy", code="empty_legit", http_status=response_status), attempt_stats


def _normalize_browser_channel(value: str | None) -> str | None:
    raw = (value or "").strip().lower()
    if raw in {"", "auto"}:
        return None
    if raw in _LEGACY_BROWSER_CHANNEL_ALIASES:
        return _LEGACY_BROWSER_CHANNEL_ALIASES[raw]
    raise ValueError("browser_channel must be one of: auto|camoufox (legacy aliases: firefox|chromium|chrome|msedge)")


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
    artifact_retention_days: int = 0,
    listing_cache_db_path: str | None = None,
    service_runtime: LiveFetchServiceRuntime | None = None,
    logger,
) -> LiveFetchRunReport:
    if not search_urls:
        return LiveFetchRunReport(
            listings=[],
            run_state="warmup",
            run_state_site="",
            assist_required=False,
            assist_reason="",
            stop_requested=False,
            stop_reason="",
        )
    out: list[ListingRecord] = []
    debug_path = Path(debug_dir).expanduser() if debug_dir else None
    if debug_path is not None:
        _prune_debug_artifacts(
            debug_dir=debug_path,
            logger=logger,
            retention_sec=max(0, int(artifact_retention_days)) * 24 * 3600 or _LIVE_DEBUG_RETENTION_SEC,
        )
    channel = _normalize_browser_channel(browser_channel)
    if channel_rotation_mode not in {"off", "round_robin"}:
        raise ValueError("channel_rotation_mode must be one of: off|round_robin")
    guard_state_path = Path(site_guard_state_path).expanduser() if site_guard_state_path else None
    guard_state = _load_guard_state(guard_state_path) if (site_guard_enabled and guard_state_path is not None) else None
    if guard_state is not None and guard_state_path is not None:
        removed_guard_sites = _prune_guard_state_sites(guard_state, search_urls)
        if removed_guard_sites:
            _save_guard_state(guard_state_path, guard_state)
            logger.info("Site guard state pruned stale sites. removed_sites=%s", ",".join(removed_guard_sites))
    listing_cache_db = Database(Path(listing_cache_db_path).expanduser()) if listing_cache_db_path else None
    jitter_min = max(0, int(guard_jitter_min_sec))
    jitter_max = max(jitter_min, int(guard_jitter_max_sec))
    base_cooldown = max(60, int(guard_base_cooldown_sec))
    max_cooldown = max(base_cooldown, int(guard_max_cooldown_sec))
    risk_budget = _build_default_risk_budget(search_urls=search_urls, extraction=extraction)
    browser_mode = _BROWSER_MODE_MANAGED_STABLE
    assist_entry_mode = ""
    retry_count_total = 0
    detail_touch_count_total = 0
    identity_switch_count = 0
    same_site_profile_reuse_count = 0
    cross_site_session_reuse_count = 0
    site_session_replace_count = 0
    manual_assist_used = False
    run_risk = RunRiskState()
    outcomes_seen: list[FetchOutcome] = []
    site_outcome_tiers: dict[str, str] = {}
    run_state_site = ""

    logger.info(
        "Live fetch risk budget. browser_mode=%s page_budget=%s detail_budget=%s identity_budget=%s retry_budget=%s cooldown_budget=%s manual_assist_threshold=%s urls=%s",
        browser_mode,
        risk_budget.page_budget,
        risk_budget.detail_budget,
        risk_budget.identity_budget,
        risk_budget.retry_budget,
        risk_budget.cooldown_budget,
        risk_budget.manual_assist_threshold,
        len(search_urls),
    )

    local_playwright = service_runtime is None
    pw = await async_playwright().start() if local_playwright else await _ensure_service_runtime(service_runtime)
    session_slots: dict[str, BrowserSessionSlot] = {} if service_runtime is None else service_runtime.session_slots
    try:
        browser = None
        context = None
        page = None
        selected_channel_label = ""
        active_session_owner = ""
        active_session_site = ""
        try:
            for url in search_urls:
                if run_risk.pages_used >= risk_budget.page_budget:
                    logger.info(
                        "Page budget exhausted. page_budget=%s pages_used=%s stop_reason=page_budget_exceeded next_url=%s",
                        risk_budget.page_budget,
                        run_risk.pages_used,
                        url,
                    )
                    break
                run_risk.pages_used += 1
                site = _site_key_from_url(url)
                run_state_site = site
                try:
                    preferred_candidates = _rotated_channel_candidates(
                        requested_channel=channel,
                        rotation_mode=channel_rotation_mode,
                        state=guard_state,
                        site=site,
                    )
                    launch_candidates = preferred_candidates
                    if channel is None and channel_rotation_mode == "round_robin":
                        launch_candidates, _ = _filter_available_channel_candidates(preferred_candidates)
                    preferred_label = _channel_to_label(launch_candidates[0])
                    preferred_session_owner, _ = _session_identity(
                        site=site,
                        channel_label=preferred_label,
                        profile_dir=profile_dir,
                    )

                    if site_guard_enabled and guard_state is not None and guard_state_path is not None:
                        entry = _site_state(guard_state, site)
                        if _is_warmup_entry(entry):
                            logger.info(
                                "Site guard warmup active. site=%s warmup_failures=%s last_success=%s url=%s",
                                site,
                                entry.get("warmup_failures"),
                                entry.get("last_success_utc") or "none",
                                url,
                            )
                        now = _utc_now()
                        rem = _cooldown_remaining_sec(guard_state, site, now)
                        probe_due = rem > 0 and _is_interstitial_probe_due(entry, now)
                        if probe_due and not guard_ignore_cooldown:
                            entry["probe_attempts"] = int(entry.get("probe_attempts") or 0) + 1
                            probe_delay = _interstitial_probe_delay_sec(base_sec=base_cooldown, cooldown_sec=rem)
                            entry["probe_after_utc"] = (
                                (now + timedelta(seconds=probe_delay)).isoformat() if probe_delay > 0 else ""
                            )
                            _save_guard_state(guard_state_path, guard_state)
                            logger.info(
                                "Site guard cooldown probe due. site=%s remaining_sec=%s attempts=%s url=%s",
                                site,
                                rem,
                                entry.get("probe_attempts"),
                                url,
                            )
                        if rem > 0 and not guard_ignore_cooldown:
                            if probe_due:
                                logger.info(
                                    "Site guard bypassing cooldown for controlled interstitial probe. site=%s url=%s",
                                    site,
                                    url,
                                )
                            else:
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
                                    channel_label=selected_channel_label or _DEFAULT_BROWSER_LABEL,
                                )
                                _save_guard_state(guard_state_path, guard_state)
                                outcomes_seen.append(cooldown_outcome)
                                _record_site_outcome_tier(site_outcome_tiers, site, cooldown_outcome)
                                snapshot = _log_guard_decision(
                                    logger=logger,
                                    site=site,
                                    url=url,
                                    outcome=cooldown_outcome,
                                    decision=decision,
                                    entry=_site_state(guard_state, site),
                                    browser_mode=browser_mode,
                                    identity_switch=identity_switch_count,
                                    manual_assist_used=manual_assist_used,
                                    assist_entry_mode=assist_entry_mode,
                                )
                                previous_state, _ = _advance_run_state(
                                    entry=_site_state(guard_state, site),
                                    outcome=cooldown_outcome,
                                    decision=decision,
                                    run_risk=run_risk,
                                )
                                _log_run_risk_state(
                                    logger=logger,
                                    site=site,
                                    url=url,
                                    previous_state=previous_state,
                                    run_risk=run_risk,
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
                                            "telemetry": asdict(snapshot),
                                            "run_risk": asdict(run_risk),
                                        },
                                        logger=logger,
                                    )
                                if _consume_cooldown_budget(
                                    outcome=cooldown_outcome,
                                    decision=decision,
                                    risk_budget=risk_budget,
                                    run_risk=run_risk,
                                ):
                                    manual_assist_used = True
                                    logger.warning(
                                        "Risk budget exceeded after cooldown skip. site=%s cooldown_used=%s cooldown_budget=%s stop_reason=%s",
                                        site,
                                        run_risk.cooldown_used,
                                        risk_budget.cooldown_budget,
                                        run_risk.stop_reason,
                                    )
                                    break
                                continue
                        if rem > 0 and guard_ignore_cooldown:
                            logger.info(
                                "Forced live run while cooldown is active. site=%s remaining_sec=%s url=%s",
                                site,
                                rem,
                                url,
                            )
                    if site_guard_enabled and jitter_max > 0:
                        delay = random.uniform(jitter_min, jitter_max)
                        if delay > 0:
                            logger.info("Site guard jitter delay. site=%s delay_sec=%.2f", site, delay)
                            await asyncio.sleep(delay)

                    slot = session_slots.get(preferred_session_owner)
                    if slot is None:
                        previous_channel_label = selected_channel_label
                        browser, context, page, selected_channel_label = await _launch_browser_session(
                            pw=pw,
                            site=site,
                            profile_dir=profile_dir,
                            requested_channel=channel,
                            rotation_mode=channel_rotation_mode,
                            guard_state=guard_state,
                            headless=headless,
                            logger=logger,
                        )
                        active_session_owner, profile_root = _session_identity(
                            site=site,
                            channel_label=selected_channel_label,
                            profile_dir=profile_dir,
                        )
                        slot = BrowserSessionSlot(
                            owner_key=active_session_owner,
                            site=site,
                            channel_label=selected_channel_label,
                            profile_root=str(profile_root) if profile_root is not None else "",
                            browser=browser,
                            context=context,
                            page=page,
                        )
                        session_slots[active_session_owner] = slot
                        pruned_slots = await _prune_site_session_slots(
                            session_slots,
                            site=site,
                            preserve_owner=active_session_owner,
                        )
                        site_session_replace_count += pruned_slots
                        replace_count, owner_state = _register_site_session_replace(
                            run_risk,
                            site=site,
                            replaced_slots=pruned_slots,
                        )
                        if previous_channel_label and selected_channel_label != previous_channel_label:
                            identity_switch_count += 1
                        logger.info(
                            "Session owner acquired. site=%s owner=%s profile_isolated=%s pooled_sessions=%s pruned_same_site_slots=%s site_owner_replace_count=%s owner_state=%s",
                            site,
                            active_session_owner,
                            bool(profile_dir),
                            len(session_slots),
                            pruned_slots,
                            replace_count,
                            owner_state,
                        )
                        if run_risk.assist_required:
                            manual_assist_used = True
                            logger.warning(
                                "Assist required after same-site owner churn. site=%s owner=%s replace_count=%s reason=%s",
                                site,
                                active_session_owner,
                                replace_count,
                                run_risk.assist_reason,
                            )
                            break
                        if guard_state is not None and guard_state_path is not None:
                            guard_state["last_channel"] = selected_channel_label
                            _save_guard_state(guard_state_path, guard_state)
                    else:
                        browser = slot.browser
                        context = slot.context
                        page = slot.page
                        selected_channel_label = slot.channel_label
                        slot.reuse_count += 1
                        slot.last_used_monotonic = time.monotonic()
                        if slot.site == site:
                            same_site_profile_reuse_count += 1
                        elif active_session_site and active_session_site != site:
                            cross_site_session_reuse_count += 1
                        active_session_owner = slot.owner_key
                        logger.info(
                            "Reusing isolated site session. site=%s channel=%s owner=%s slot_reuse_count=%s same_site_profile_reuse_count=%s cross_site_session_reuse_count=%s",
                            site,
                            selected_channel_label,
                            active_session_owner,
                            slot.reuse_count,
                            same_site_profile_reuse_count,
                            cross_site_session_reuse_count,
                        )
                    active_session_site = site

                    cards: list[dict] = []
                    outcome = FetchOutcome(tier="healthy", code="empty_legit")
                    attempt_stats = FetchAttemptStats()
                    url_retry_count = 0
                    metrics: ExtractionMetrics | None = None
                    drift: DriftDiagnostic | None = None
                    for attempt in (1, 2):
                        detail_budget_remaining = _remaining_detail_budget(risk_budget=risk_budget, run_risk=run_risk)
                        if (
                            site == "idealista"
                            and extraction.private_only_ads
                            and detail_budget_remaining <= 0
                        ):
                            logger.info(
                                "Detail budget exhausted. site=%s detail_budget=%s detail_used=%s url=%s",
                                site,
                                risk_budget.detail_budget,
                                run_risk.detail_used,
                                url,
                            )
                        cards, outcome, attempt_stats = await _extract_for_url(
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
                            listing_cache_db=listing_cache_db,
                            detail_budget_remaining=detail_budget_remaining,
                            logger=logger,
                        )
                        run_risk.detail_used += attempt_stats.detail_touch_count
                        detail_touch_count_total += attempt_stats.detail_touch_count
                        if cards or not outcome.retryable or attempt == 2:
                            break
                        allow_retry, retry_reason = _allow_transient_retry(
                            outcome=outcome,
                            risk_budget=risk_budget,
                            run_risk=run_risk,
                        )
                        if not allow_retry:
                            if retry_reason == "retry_budget_exhausted":
                                logger.info(
                                    "Transient retry suppressed by risk budget. site=%s retries_used=%s retry_budget=%s url=%s",
                                    site,
                                    run_risk.retries_used,
                                    risk_budget.retry_budget,
                                    url,
                                )
                            break
                        retry_sleep = random.uniform(2.0, 4.0)
                        url_retry_count += 1
                        run_risk.retries_used += 1
                        retry_count_total += 1
                        logger.info(
                            "Transient live outcome. site=%s channel=%s retrying_once=true tier=%s code=%s delay_sec=%.2f url=%s",
                            site,
                            selected_channel_label or _DEFAULT_BROWSER_LABEL,
                            outcome.tier,
                            outcome.code,
                            retry_sleep,
                            url,
                        )
                        await asyncio.sleep(retry_sleep)
                    attempt_stats.retry_count = url_retry_count
                    alternate_candidates = _alternate_browser_retry_candidates(
                        launch_candidates,
                        current_label=selected_channel_label or _DEFAULT_BROWSER_LABEL,
                    )
                    should_retry_with_alternate, alternate_retry_reason = _allow_alternate_browser_retry(
                        cards=cards,
                        outcome=outcome,
                        requested_channel=channel,
                        rotation_mode=channel_rotation_mode,
                        alternate_candidates=alternate_candidates,
                        risk_budget=risk_budget,
                        identity_switch_count=identity_switch_count,
                    )
                    if should_retry_with_alternate:
                        logger.info(
                            "Blocked live outcome. site=%s channel=%s code=%s retrying_with_alternate_browser=%s url=%s",
                            site,
                            selected_channel_label or _DEFAULT_BROWSER_LABEL,
                            outcome.code,
                            ",".join(_channel_to_label(candidate) for candidate in alternate_candidates),
                            url,
                        )
                        await _close_browser_handles(context=context, browser=browser)
                        browser = None
                        context = None
                        page = None
                        try:
                            previous_channel_label = selected_channel_label or _DEFAULT_BROWSER_LABEL
                            browser, context, page, selected_channel_label = await _launch_browser_session(
                                pw=pw,
                                site=site,
                                profile_dir=profile_dir,
                                requested_channel=channel,
                                rotation_mode=channel_rotation_mode,
                                guard_state=guard_state,
                                headless=headless,
                                logger=logger,
                                candidate_override=alternate_candidates,
                            )
                            active_session_owner, profile_root = _session_identity(
                                site=site,
                                channel_label=selected_channel_label,
                                profile_dir=profile_dir,
                            )
                            session_slots[active_session_owner] = BrowserSessionSlot(
                                owner_key=active_session_owner,
                                site=site,
                                channel_label=selected_channel_label,
                                profile_root=str(profile_root) if profile_root is not None else "",
                                browser=browser,
                                context=context,
                                page=page,
                            )
                            pruned_slots = await _prune_site_session_slots(
                                session_slots,
                                site=site,
                                preserve_owner=active_session_owner,
                            )
                            site_session_replace_count += pruned_slots
                            replace_count, owner_state = _register_site_session_replace(
                                run_risk,
                                site=site,
                                replaced_slots=pruned_slots,
                            )
                            active_session_site = site
                            if selected_channel_label != previous_channel_label:
                                identity_switch_count += 1
                            logger.info(
                                "Alternate owner acquired. site=%s owner=%s pruned_same_site_slots=%s site_owner_replace_count=%s owner_state=%s",
                                site,
                                active_session_owner,
                                pruned_slots,
                                replace_count,
                                owner_state,
                            )
                            if run_risk.assist_required:
                                manual_assist_used = True
                                logger.warning(
                                    "Assist required after alternate same-site owner churn. site=%s owner=%s replace_count=%s reason=%s",
                                    site,
                                    active_session_owner,
                                    replace_count,
                                    run_risk.assist_reason,
                                )
                                break
                            if guard_state is not None and guard_state_path is not None:
                                guard_state["last_channel"] = selected_channel_label
                                _save_guard_state(guard_state_path, guard_state)
                            cards, outcome, attempt_stats = await _extract_for_url(
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
                                listing_cache_db=listing_cache_db,
                                detail_budget_remaining=_remaining_detail_budget(risk_budget=risk_budget, run_risk=run_risk),
                                logger=logger,
                            )
                            attempt_stats.retry_count = url_retry_count
                            run_risk.detail_used += attempt_stats.detail_touch_count
                            detail_touch_count_total += attempt_stats.detail_touch_count
                            logger.info(
                                "Alternate browser retry result. site=%s channel=%s tier=%s code=%s listings=%s url=%s",
                                site,
                                selected_channel_label or _DEFAULT_BROWSER_LABEL,
                                outcome.tier,
                                outcome.code,
                                len(cards) if cards else outcome.listings,
                                url,
                            )
                        except Exception as exc:
                            logger.warning(
                                "Alternate browser retry failed to start. site=%s details=%s",
                                site,
                                str(exc).splitlines()[0] if str(exc) else repr(exc),
                            )
                    elif alternate_retry_reason == "identity_budget_exhausted":
                        logger.info(
                            "Alternate browser retry suppressed by risk budget. site=%s channel=%s code=%s identity_switch=%s identity_budget=%s url=%s",
                            site,
                            selected_channel_label or _DEFAULT_BROWSER_LABEL,
                                outcome.code,
                                identity_switch_count,
                                risk_budget.identity_budget,
                                url,
                            )
                    logger.info(
                        "Fetch URL result. site=%s channel=%s tier=%s code=%s listings=%s retry_count=%s detail_touch_count=%s identity_switch=%s url=%s",
                        site,
                        selected_channel_label or _DEFAULT_BROWSER_LABEL,
                        outcome.tier,
                        outcome.code,
                        len(cards) if cards else outcome.listings,
                        retry_count_total,
                        detail_touch_count_total,
                        identity_switch_count,
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
                    _record_site_outcome_tier(site_outcome_tiers, site, outcome)
                    if site_guard_enabled and guard_state is not None and guard_state_path is not None:
                        decision = _apply_guard_outcome(
                            state=guard_state,
                            site=site,
                            outcome=outcome,
                            now=_utc_now(),
                            base_sec=base_cooldown,
                            max_sec=max_cooldown,
                            channel_label=selected_channel_label or _DEFAULT_BROWSER_LABEL,
                        )
                        _save_guard_state(guard_state_path, guard_state)
                        entry = _site_state(guard_state, site)
                        if metrics is not None:
                            _store_extraction_metrics(entry=entry, metrics=metrics)
                            _save_guard_state(guard_state_path, guard_state)
                        snapshot = _log_guard_decision(
                            logger=logger,
                            site=site,
                            url=url,
                            outcome=outcome,
                            decision=decision,
                            entry=entry,
                            browser_mode=browser_mode,
                            identity_switch=identity_switch_count,
                            attempt_stats=attempt_stats,
                            manual_assist_used=manual_assist_used,
                            assist_entry_mode=assist_entry_mode,
                        )
                        previous_state, _ = _advance_run_state(
                            entry=entry,
                            outcome=outcome,
                            decision=decision,
                            run_risk=run_risk,
                        )
                        _log_run_risk_state(
                            logger=logger,
                            site=site,
                            url=url,
                            previous_state=previous_state,
                            run_risk=run_risk,
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
                                    "telemetry": asdict(snapshot),
                                    "run_risk": asdict(run_risk),
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
                        if _consume_cooldown_budget(
                            outcome=outcome,
                            decision=decision,
                            risk_budget=risk_budget,
                            run_risk=run_risk,
                        ):
                            manual_assist_used = True
                            logger.warning(
                                "Risk budget exceeded after guard decision. site=%s cooldown_used=%s cooldown_budget=%s stop_reason=%s url=%s",
                                site,
                                run_risk.cooldown_used,
                                risk_budget.cooldown_budget,
                                run_risk.stop_reason,
                                url,
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
                    if run_risk.stop_requested:
                        break
                except LiveFetchBlocked as exc:
                    outcome = FetchOutcome(
                        tier="blocked",
                        code=exc.code,
                        detail=_normalize(str(exc)),
                        hard_block=exc.code in {"hard_block", "hard_block_http_status"},
                        challenge_visible=exc.code in {"challenge_visible", "interstitial_datadome"},
                    )
                    outcomes_seen.append(outcome)
                    _record_site_outcome_tier(site_outcome_tiers, site, outcome)
                    logger.warning(
                        "Live fetch blocked. site=%s channel=%s code=%s url=%s details=%s",
                        site,
                        selected_channel_label or _DEFAULT_BROWSER_LABEL,
                        exc.code,
                        url,
                        exc,
                    )
                    if site_guard_enabled and guard_state is not None and guard_state_path is not None:
                        decision = _apply_guard_outcome(
                            state=guard_state,
                            site=site,
                            outcome=outcome,
                            now=_utc_now(),
                            base_sec=base_cooldown,
                            max_sec=max_cooldown,
                            channel_label=selected_channel_label or _DEFAULT_BROWSER_LABEL,
                        )
                        _save_guard_state(guard_state_path, guard_state)
                        snapshot = _log_guard_decision(
                            logger=logger,
                            site=site,
                            url=url,
                            outcome=outcome,
                            decision=decision,
                            entry=_site_state(guard_state, site),
                            browser_mode=browser_mode,
                            identity_switch=identity_switch_count,
                            manual_assist_used=manual_assist_used,
                            assist_entry_mode=assist_entry_mode,
                        )
                        previous_state, _ = _advance_run_state(
                            entry=_site_state(guard_state, site),
                            outcome=outcome,
                            decision=decision,
                            run_risk=run_risk,
                        )
                        _log_run_risk_state(
                            logger=logger,
                            site=site,
                            url=url,
                            previous_state=previous_state,
                            run_risk=run_risk,
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
                                    "telemetry": asdict(snapshot),
                                    "run_risk": asdict(run_risk),
                                },
                                logger=logger,
                            )
                        if _consume_cooldown_budget(
                            outcome=outcome,
                            decision=decision,
                            risk_budget=risk_budget,
                            run_risk=run_risk,
                        ):
                            manual_assist_used = True
                            logger.warning(
                                "Risk budget exceeded after blocked outcome. site=%s cooldown_used=%s cooldown_budget=%s stop_reason=%s url=%s",
                                site,
                                run_risk.cooldown_used,
                                risk_budget.cooldown_budget,
                                run_risk.stop_reason,
                                url,
                            )
                    if run_risk.stop_requested:
                        break
                except PlaywrightTimeout as exc:
                    outcome = _classify_runtime_exception(exc)
                    outcomes_seen.append(outcome)
                    _record_site_outcome_tier(site_outcome_tiers, site, outcome)
                    logger.warning(
                        "Timeout on url=%s site=%s channel=%s",
                        url,
                        site,
                        selected_channel_label or _DEFAULT_BROWSER_LABEL,
                    )
                    if site_guard_enabled and guard_state is not None and guard_state_path is not None:
                        decision = _apply_guard_outcome(
                            state=guard_state,
                            site=site,
                            outcome=outcome,
                            now=_utc_now(),
                            base_sec=base_cooldown,
                            max_sec=max_cooldown,
                            channel_label=selected_channel_label or _DEFAULT_BROWSER_LABEL,
                        )
                        _save_guard_state(guard_state_path, guard_state)
                        snapshot = _log_guard_decision(
                            logger=logger,
                            site=site,
                            url=url,
                            outcome=outcome,
                            decision=decision,
                            entry=_site_state(guard_state, site),
                            browser_mode=browser_mode,
                            identity_switch=identity_switch_count,
                            manual_assist_used=manual_assist_used,
                            assist_entry_mode=assist_entry_mode,
                        )
                        previous_state, _ = _advance_run_state(
                            entry=_site_state(guard_state, site),
                            outcome=outcome,
                            decision=decision,
                            run_risk=run_risk,
                        )
                        _log_run_risk_state(
                            logger=logger,
                            site=site,
                            url=url,
                            previous_state=previous_state,
                            run_risk=run_risk,
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
                                    "telemetry": asdict(snapshot),
                                    "run_risk": asdict(run_risk),
                                },
                                logger=logger,
                            )
                        if _consume_cooldown_budget(
                            outcome=outcome,
                            decision=decision,
                            risk_budget=risk_budget,
                            run_risk=run_risk,
                        ):
                            manual_assist_used = True
                            logger.warning(
                                "Risk budget exceeded after timeout outcome. site=%s cooldown_used=%s cooldown_budget=%s stop_reason=%s url=%s",
                                site,
                                run_risk.cooldown_used,
                                risk_budget.cooldown_budget,
                                run_risk.stop_reason,
                                url,
                            )
                    if run_risk.stop_requested:
                        break
                except Exception as exc:
                    outcome = _classify_runtime_exception(exc)
                    outcomes_seen.append(outcome)
                    _record_site_outcome_tier(site_outcome_tiers, site, outcome)
                    logger.error(
                        "Live fetch error on url=%s site=%s channel=%s details=%s",
                        url,
                        site,
                        selected_channel_label or _DEFAULT_BROWSER_LABEL,
                        exc,
                    )
                    if site_guard_enabled and guard_state is not None and guard_state_path is not None:
                        decision = _apply_guard_outcome(
                            state=guard_state,
                            site=site,
                            outcome=outcome,
                            now=_utc_now(),
                            base_sec=base_cooldown,
                            max_sec=max_cooldown,
                            channel_label=selected_channel_label or _DEFAULT_BROWSER_LABEL,
                        )
                        _save_guard_state(guard_state_path, guard_state)
                        snapshot = _log_guard_decision(
                            logger=logger,
                            site=site,
                            url=url,
                            outcome=outcome,
                            decision=decision,
                            entry=_site_state(guard_state, site),
                            browser_mode=browser_mode,
                            identity_switch=identity_switch_count,
                            manual_assist_used=manual_assist_used,
                            assist_entry_mode=assist_entry_mode,
                        )
                        previous_state, _ = _advance_run_state(
                            entry=_site_state(guard_state, site),
                            outcome=outcome,
                            decision=decision,
                            run_risk=run_risk,
                        )
                        _log_run_risk_state(
                            logger=logger,
                            site=site,
                            url=url,
                            previous_state=previous_state,
                            run_risk=run_risk,
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
                                    "telemetry": asdict(snapshot),
                                    "run_risk": asdict(run_risk),
                                },
                                logger=logger,
                            )
                        if _consume_cooldown_budget(
                            outcome=outcome,
                            decision=decision,
                            risk_budget=risk_budget,
                            run_risk=run_risk,
                        ):
                            manual_assist_used = True
                            logger.warning(
                                "Risk budget exceeded after error outcome. site=%s cooldown_used=%s cooldown_budget=%s stop_reason=%s url=%s",
                                site,
                                run_risk.cooldown_used,
                                risk_budget.cooldown_budget,
                                run_risk.stop_reason,
                                url,
                            )
                    if run_risk.stop_requested:
                        break
        finally:
            if local_playwright and session_slots:
                await _close_browser_slots(session_slots)
            elif local_playwright:
                await _close_browser_handles(context=context, browser=browser)
    finally:
        if local_playwright:
            await pw.stop()
    if outcomes_seen:
        tier_counts = {tier: 0 for tier in ("healthy", "suspect", "degraded", "blocked", "cooling")}
        code_counts: dict[str, int] = {}
        for item in outcomes_seen:
            tier_counts[item.tier] = tier_counts.get(item.tier, 0) + 1
            code_counts[item.code] = code_counts.get(item.code, 0) + 1
        code_summary = ", ".join(f"{code}={count}" for code, count in sorted(code_counts.items()))
        logger.info(
            "Live fetch outcome summary. urls=%s healthy=%s suspect=%s degraded=%s blocked=%s cooling=%s listings=%s retry_count=%s detail_touch_count=%s identity_switch=%s same_site_profile_reuse_count=%s cross_site_session_reuse_count=%s site_session_replace_count=%s cooldown_count=%s browser_mode=%s run_state=%s assist_required=%s assist_reason=%s stop_requested=%s stop_reason=%s codes=%s",
            len(outcomes_seen),
            tier_counts.get("healthy", 0),
            tier_counts.get("suspect", 0),
            tier_counts.get("degraded", 0),
            tier_counts.get("blocked", 0),
            tier_counts.get("cooling", 0),
            len(out),
            retry_count_total,
            detail_touch_count_total,
            identity_switch_count,
            same_site_profile_reuse_count,
            cross_site_session_reuse_count,
            site_session_replace_count,
            run_risk.cooldown_used,
            browser_mode,
            run_risk.current_state,
            run_risk.assist_required,
            run_risk.assist_reason or "none",
            run_risk.stop_requested,
            run_risk.stop_reason or "none",
            code_summary,
        )
    if site_guard_enabled and guard_state is not None:
        warmup_sites = sorted(site for site, entry in (guard_state.get("sites") or {}).items() if isinstance(entry, dict) and _is_warmup_entry(entry))
        if warmup_sites:
            logger.info("Site guard warmup summary. active_sites=%s", ",".join(warmup_sites))
    return LiveFetchRunReport(
        listings=out,
        run_state=run_risk.current_state,
        run_state_site=run_state_site,
        assist_required=run_risk.assist_required,
        assist_reason=run_risk.assist_reason,
        stop_requested=run_risk.stop_requested,
        stop_reason=run_risk.stop_reason,
        retry_count=retry_count_total,
        detail_touch_count=detail_touch_count_total,
        identity_switch_count=identity_switch_count,
        same_site_profile_reuse_count=same_site_profile_reuse_count,
        cross_site_session_reuse_count=cross_site_session_reuse_count,
        site_session_replace_count=site_session_replace_count,
        cooldown_count=run_risk.cooldown_used,
        site_outcome_tiers=dict(site_outcome_tiers),
    )
