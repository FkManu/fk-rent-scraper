from __future__ import annotations

import asyncio
import hashlib
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
from camoufox.utils import launch_options as camoufox_launch_options
from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

from ..db import Database, ListingRecord
from ..models import CaptchaMode, ExtractionFields
from .render_context import install_render_context_init_script
from .browser import bootstrap as browser_bootstrap
from .browser import factory as browser_factory
from .browser.session_policy import get_session_policy
from .guard import state_machine as guard_state_machine
from .sites import idealista as idealista_site
from .sites import immobiliare as immobiliare_site

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

_IDEALISTA_AGENCY_ATTR_SELECTORS = idealista_site.AGENCY_ATTR_SELECTORS
_IDEALISTA_AGENCY_TEXT_SELECTORS = idealista_site.AGENCY_TEXT_SELECTORS
_IDEALISTA_PRIVATE_ONLY_DETAIL_MAX_CHECKS = idealista_site.PRIVATE_ONLY_MAX_CHECKS
_IDEALISTA_PRIVATE_ONLY_DETAIL_DELAY_MS = idealista_site.PRIVATE_ONLY_DELAY_MS
_IDEALISTA_PRIVATE_ONLY_DETAIL_BATCH_PAUSE_EVERY = idealista_site.PRIVATE_ONLY_BATCH_PAUSE_EVERY
_IDEALISTA_PRIVATE_ONLY_DETAIL_BATCH_PAUSE_MS = idealista_site.PRIVATE_ONLY_BATCH_PAUSE_MS
_HTTP_NETWORK_STATUSES = {408, 425, 500, 502, 503, 504, 522, 524}
_DEFAULT_SESSION_POLICY = get_session_policy("immobiliare")
_INTERACTION_PACING_GAMMA_SHAPE = _DEFAULT_SESSION_POLICY.pacing_gamma_shape
_INTERACTION_PACING_GAMMA_SCALE = _DEFAULT_SESSION_POLICY.pacing_gamma_scale
_STATIC_RESOURCE_BOOTSTRAP_URLS = _DEFAULT_SESSION_POLICY.bootstrap_urls
_STATIC_RESOURCE_BOOTSTRAP_TIMEOUT_MS = _DEFAULT_SESSION_POLICY.bootstrap_timeout_ms

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
_CAMOUFOX_PERSONA_VERSION = 1
_CAMOUFOX_PERSONA_WINDOWS = (
    {
        "label": "desktop_fhd_balanced",
        "screen": (1920, 1080),
        "windows": ((1760, 990), (1680, 960), (1600, 900)),
    },
    {
        "label": "desktop_fhd_compact",
        "screen": (1920, 1080),
        "windows": ((1540, 900), (1480, 860), (1440, 840)),
    },
    {
        "label": "desktop_fhd_wide",
        "screen": (1920, 1080),
        "windows": ((1820, 1020), (1740, 980), (1660, 940)),
    },
)
_GUARD_STATE_VERSION = 7
_BROWSER_MODE_MANAGED_STABLE = "managed_stable"
_HARD_BLOCK_PROFILE_RESET_SITES = {"idealista", "immobiliare"}
_PROFILE_ROTATION_MAX_AGE_SEC: dict[str, int] = {
    "immobiliare": 24 * 3600,
}


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
    profile_age_sec: int
    profile_generation: int
    cooldown_profile_generation: int | None
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
class CamoufoxPersona:
    version: int
    persona_id: str
    seed: int
    site: str
    channel_label: str
    profile_generation: int
    created_utc: str
    screen_label: str
    screen_width: int
    screen_height: int
    window_width: int
    window_height: int
    humanize_max_sec: float
    history_length: int
    font_spacing_seed: int
    canvas_aa_offset: int
    launch_options: dict[str, object]


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
    forced_cooldown: bool = False
    destroy_persistent_profile: bool = False


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
    return idealista_site.classify_publisher_kind(body_text)


def _classify_idealista_publisher_kind_from_signals(
    *,
    body_text: str,
    has_professional_profile_link: bool,
) -> str:
    return idealista_site.classify_publisher_kind_from_signals(
        body_text=body_text,
        has_professional_profile_link=has_professional_profile_link,
    )


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


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


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
    return raw


def _channel_to_label(channel: str | None) -> str:
    return _normalize_channel_label(channel)


def _camoufox_persona_path(profile_root: Path) -> Path:
    return profile_root / "camoufox_persona.json"


def _camoufox_persona_seed(*, site: str, channel_label: str, profile_generation: int) -> int:
    raw = f"{site}|{channel_label}|{profile_generation}|camoufox-persona-v{_CAMOUFOX_PERSONA_VERSION}"
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def _camoufox_screen_constraints(*, width: int = 1920, height: int = 1080) -> Screen:
    return Screen(
        min_width=width,
        max_width=width,
        min_height=height,
        max_height=height,
    )


def _camoufox_persona_from_payload(payload: dict[str, object]) -> CamoufoxPersona | None:
    try:
        launch_options = payload.get("launch_options")
        if not isinstance(launch_options, dict):
            return None
        persona = CamoufoxPersona(
            version=int(payload.get("version") or 0),
            persona_id=str(payload.get("persona_id") or "").strip(),
            seed=int(payload.get("seed") or 0),
            site=str(payload.get("site") or "").strip(),
            channel_label=str(payload.get("channel_label") or "").strip(),
            profile_generation=int(payload.get("profile_generation") or 0),
            created_utc=str(payload.get("created_utc") or "").strip(),
            screen_label=str(payload.get("screen_label") or "").strip(),
            screen_width=int(payload.get("screen_width") or 0),
            screen_height=int(payload.get("screen_height") or 0),
            window_width=int(payload.get("window_width") or 0),
            window_height=int(payload.get("window_height") or 0),
            humanize_max_sec=float(payload.get("humanize_max_sec") or 0.0),
            history_length=int(payload.get("history_length") or 0),
            font_spacing_seed=int(payload.get("font_spacing_seed") or 0),
            canvas_aa_offset=int(payload.get("canvas_aa_offset") or 0),
            launch_options=launch_options,
        )
    except (TypeError, ValueError):
        return None
    if (
        persona.version != _CAMOUFOX_PERSONA_VERSION
        or not persona.persona_id
        or not persona.site
        or not persona.channel_label
        or not persona.created_utc
        or not persona.screen_label
        or persona.screen_width <= 0
        or persona.screen_height <= 0
        or persona.window_width <= 0
        or persona.window_height <= 0
        or persona.humanize_max_sec <= 0
        or persona.history_length <= 0
        or not persona.launch_options
    ):
        return None
    return persona


def _build_camoufox_persona(
    *,
    site: str,
    channel_label: str,
    profile_generation: int,
    executable_path: Path | None,
    now: datetime,
) -> CamoufoxPersona:
    resolved_executable_path = executable_path if executable_path is not None and executable_path.exists() else None
    seed = _camoufox_persona_seed(
        site=site,
        channel_label=channel_label,
        profile_generation=profile_generation,
    )
    rng = random.Random(seed)
    screen_profile = _CAMOUFOX_PERSONA_WINDOWS[rng.randrange(len(_CAMOUFOX_PERSONA_WINDOWS))]
    screen_width, screen_height = screen_profile["screen"]
    window_width, window_height = rng.choice(screen_profile["windows"])
    humanize_max_sec = round(rng.uniform(0.95, 1.45), 2)
    history_length = rng.randint(2, 5)
    font_spacing_seed = rng.randint(0, 1_073_741_823)
    canvas_aa_offset = rng.randint(-18, 18)
    config = {
        "timezone": _CAMOUFOX_DEFAULT_TIMEZONE,
        "window.history.length": history_length,
        "fonts:spacing_seed": font_spacing_seed,
        "canvas:aaOffset": canvas_aa_offset,
        "canvas:aaCapOffset": True,
    }
    launch_options = camoufox_launch_options(
        headless=False,
        humanize=humanize_max_sec,
        locale=_CAMOUFOX_DEFAULT_LOCALE,
        os=_CAMOUFOX_DEFAULT_OS,
        screen=_camoufox_screen_constraints(width=screen_width, height=screen_height),
        window=(window_width, window_height),
        config=config,
        executable_path=resolved_executable_path,
        i_know_what_im_doing=True,
    )
    return CamoufoxPersona(
        version=_CAMOUFOX_PERSONA_VERSION,
        persona_id=f"{site}-{channel_label}-g{profile_generation:03d}-{seed % 10000:04d}",
        seed=seed,
        site=site,
        channel_label=channel_label,
        profile_generation=profile_generation,
        created_utc=now.isoformat(),
        screen_label=str(screen_profile["label"]),
        screen_width=screen_width,
        screen_height=screen_height,
        window_width=window_width,
        window_height=window_height,
        humanize_max_sec=humanize_max_sec,
        history_length=history_length,
        font_spacing_seed=font_spacing_seed,
        canvas_aa_offset=canvas_aa_offset,
        launch_options=launch_options,
    )


def _load_or_create_camoufox_persona(
    *,
    site: str,
    channel_label: str,
    profile_generation: int,
    profile_root: Path,
    executable_path: Path | None,
    logger,
) -> CamoufoxPersona:
    persona_path = _camoufox_persona_path(profile_root)
    if persona_path.exists():
        try:
            raw = json.loads(persona_path.read_text(encoding="utf-8"))
        except Exception:
            raw = None
        if isinstance(raw, dict):
            persona = _camoufox_persona_from_payload(raw)
            if (
                persona is not None
                and persona.site == site
                and persona.channel_label == channel_label
                and persona.profile_generation == profile_generation
            ):
                return persona
            logger.info(
                "Camoufox persona file invalid or stale. site=%s channel=%s generation=%s file=%s",
                site,
                channel_label,
                profile_generation,
                persona_path,
            )
    persona = _build_camoufox_persona(
        site=site,
        channel_label=channel_label,
        profile_generation=profile_generation,
        executable_path=executable_path,
        now=_utc_now(),
    )
    _write_json_atomic(persona_path, asdict(persona))
    logger.info(
        "Created Camoufox persona. site=%s channel=%s generation=%s persona=%s screen=%sx%s window=%sx%s humanize_max_sec=%s file=%s",
        site,
        channel_label,
        profile_generation,
        persona.persona_id,
        persona.screen_width,
        persona.screen_height,
        persona.window_width,
        persona.window_height,
        persona.humanize_max_sec,
        persona_path,
    )
    return persona


def _label_to_channel(label: str) -> str | None:
    _normalize_channel_label(label)
    return None


def _new_guard_site_entry() -> dict[str, object]:
    return {
        "strikes": 0,
        "cooldown_until_utc": "",
        "cooldown_profile_generation": "",
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
        "profile_generation": 0,
        "profile_created_utc": "",
        "profile_rotated_utc": "",
        "profile_quarantine_reason": "",
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


def _profile_generation(entry: dict) -> int:
    try:
        value = int(entry.get("profile_generation") or 0)
    except (TypeError, ValueError):
        value = 0
    return max(0, value)


def _ensure_site_profile_tracking(entry: dict, now: datetime) -> bool:
    changed = False
    generation = _profile_generation(entry)
    if generation != entry.get("profile_generation"):
        entry["profile_generation"] = generation
        changed = True
    created_at = _parse_utc_iso(str(entry.get("profile_created_utc") or ""))
    if created_at is None:
        entry["profile_created_utc"] = now.isoformat()
        changed = True
    return changed


def _site_profile_age_sec(entry: dict, now: datetime) -> int:
    created_at = _parse_utc_iso(str(entry.get("profile_created_utc") or ""))
    if created_at is None:
        return 0
    return max(0, int((now - created_at).total_seconds()))


def _site_profile_rotation_age_cap_sec(site: str) -> int:
    return max(0, int(_PROFILE_ROTATION_MAX_AGE_SEC.get(site, 0) or 0))


def _rotate_site_profile(entry: dict, *, now: datetime, reason: str) -> tuple[int, int]:
    previous_generation = _profile_generation(entry)
    next_generation = previous_generation + 1
    entry["profile_generation"] = next_generation
    entry["profile_created_utc"] = now.isoformat()
    entry["profile_rotated_utc"] = now.isoformat()
    entry["profile_quarantine_reason"] = reason
    return (previous_generation, next_generation)


def _maybe_rotate_site_profile(*, state: dict, site: str, now: datetime, logger) -> bool:
    entry = _site_state(state, site)
    changed = _ensure_site_profile_tracking(entry, now)
    age_cap_sec = _site_profile_rotation_age_cap_sec(site)
    if age_cap_sec <= 0:
        return changed
    profile_age_sec = _site_profile_age_sec(entry, now)
    if profile_age_sec < age_cap_sec:
        return changed
    previous_generation, next_generation = _rotate_site_profile(
        entry,
        now=now,
        reason="profile_age_cap",
    )
    logger.info(
        "Preemptive site profile rotation. site=%s previous_generation=%s next_generation=%s profile_age_sec=%s age_cap_sec=%s",
        site,
        previous_generation,
        next_generation,
        profile_age_sec,
        age_cap_sec,
    )
    return True


def _site_profile_generation(state: dict | None, site: str) -> int:
    if state is None:
        return 0
    return _profile_generation(_site_state(state, site))


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


def _cooldown_profile_generation(entry: dict) -> int | None:
    raw = entry.get("cooldown_profile_generation")
    if raw in ("", None):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return max(0, value)


def _cooldown_remaining_sec(state: dict, site: str, now: datetime) -> int:
    entry = _site_state(state, site)
    until = _parse_utc_iso(str(entry.get("cooldown_until_utc") or ""))
    if until is None:
        return 0
    cooldown_generation = _cooldown_profile_generation(entry)
    if cooldown_generation is not None and _profile_generation(entry) != cooldown_generation:
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
    return guard_state_machine.state_transition_label(entry=entry, outcome=outcome)


def _risk_pause_reason(*, outcome: FetchOutcome, decision: GuardDecision) -> str:
    return guard_state_machine.risk_pause_reason(outcome=outcome, decision=decision)


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
    return guard_state_machine.build_telemetry_snapshot(
        telemetry_cls=TelemetrySnapshot,
        site=site,
        entry=entry,
        outcome=outcome,
        decision=decision,
        now=now,
        browser_mode=browser_mode,
        channel_label=channel_label,
        identity_switch=identity_switch,
        attempt_stats=attempt_stats,
        manual_assist_used=manual_assist_used,
        session_age_sec=_session_age_sec(entry, now),
        profile_age_sec=_site_profile_age_sec(entry, now),
        profile_generation=_profile_generation(entry),
        cooldown_profile_generation=_cooldown_profile_generation(entry),
        assist_entry_mode=assist_entry_mode,
    )


def _log_site_guard_telemetry(*, logger, snapshot: TelemetrySnapshot, url: str) -> None:
    logger.info(
        "Site guard telemetry. site=%s browser_mode=%s state=%s retry_count=%s detail_touch_count=%s "
        "identity_switch=%s risk_pause_reason=%s session_age_sec=%s profile_age_sec=%s "
        "profile_generation=%s cooldown_generation=%s cooldown_origin=%s url=%s",
        snapshot.site,
        snapshot.browser_mode,
        snapshot.state_transition,
        snapshot.retry_count,
        snapshot.detail_touch_count,
        snapshot.identity_switch,
        snapshot.risk_pause_reason or "none",
        snapshot.session_age_sec,
        snapshot.profile_age_sec,
        snapshot.profile_generation,
        snapshot.cooldown_profile_generation if snapshot.cooldown_profile_generation is not None else "none",
        snapshot.cooldown_origin or "none",
        url,
    )


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
    return guard_state_machine.advance_run_state(
        entry=entry,
        outcome=outcome,
        decision=decision,
        run_risk=run_risk,
        mark_assist_required=_mark_assist_required,
    )


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


async def _dispose_blocked_profile_if_needed(
    *,
    decision: GuardDecision,
    session_slots: dict[str, BrowserSessionSlot],
    profile_dir: str | None,
    site: str,
    channel_label: str,
    entry: dict,
    logger,
) -> int:
    if not decision.destroy_persistent_profile or not profile_dir:
        return 0
    cooldown_generation = _cooldown_profile_generation(entry)
    if cooldown_generation is None:
        return 0
    doomed_root = _session_profile_root(
        profile_dir,
        site,
        channel_label,
        profile_generation=cooldown_generation,
    )
    doomed_owner = _session_owner_key(site=site, channel_label=channel_label, profile_root=doomed_root)
    removed = await _prune_site_session_slots(
        session_slots,
        site=site,
        preserve_owner="",
    )
    browser_factory.destroy_persistent_profile_root(
        profile_root=doomed_root,
        base_dir=profile_dir,
        logger=logger,
        site=site,
    )
    logger.info(
        "Blocked profile disposition applied. site=%s channel=%s destroyed_generation=%s doomed_owner=%s removed_slots=%s",
        site,
        channel_label,
        cooldown_generation,
        doomed_owner,
        removed,
    )
    return removed


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
    return guard_state_machine.apply_guard_outcome(
        decision_cls=GuardDecision,
        state=state,
        site=site,
        outcome=outcome,
        now=now,
        base_sec=base_sec,
        max_sec=max_sec,
        channel_label=channel_label,
        site_state=_site_state,
        profile_generation=_profile_generation,
        rotate_site_profile=_rotate_site_profile,
        is_warmup_entry=_is_warmup_entry,
        blocked_family_from_outcome=_blocked_family_from_outcome,
        interstitial_probe_delay_sec=_interstitial_probe_delay_sec,
        hard_block_profile_reset_sites=_HARD_BLOCK_PROFILE_RESET_SITES,
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
    if (
        outcome.tier == "blocked"
        and str(entry.get("last_block_family") or "") == "hard_block"
        and snapshot.cooldown_profile_generation is not None
        and snapshot.cooldown_profile_generation != snapshot.profile_generation
    ):
        logger.warning(
            "Profile identity rotated. site=%s channel=%s trigger=%s previous_generation=%s "
            "next_generation=%s cooldown_sec=%s quarantine_reason=%s url=%s",
            site,
            entry.get("last_attempt_channel") or entry.get("last_valid_channel") or "unknown",
            outcome.code,
            snapshot.cooldown_profile_generation,
            snapshot.profile_generation,
            decision.cooldown_sec,
            entry.get("profile_quarantine_reason") or "none",
            url,
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
        _log_site_guard_telemetry(logger=logger, snapshot=snapshot, url=url)
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
        _log_site_guard_telemetry(logger=logger, snapshot=snapshot, url=url)
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
        _log_site_guard_telemetry(logger=logger, snapshot=snapshot, url=url)
        return snapshot
    log = logger.warning if outcome.tier in {"suspect", "blocked"} or decision.cooldown_sec > 0 else logger.info
    log(
        "Site guard outcome. site=%s channel=%s tier=%s code=%s action=%s strikes=%s cooldown_sec=%s "
        "block_family=%s profile_generation=%s cooldown_generation=%s url=%s",
        site,
        entry.get("last_attempt_channel") or entry.get("last_valid_channel") or "unknown",
        outcome.tier,
        outcome.code,
        decision.action,
        entry.get("strikes"),
        decision.cooldown_sec,
        entry.get("last_block_family") or "none",
        snapshot.profile_generation,
        snapshot.cooldown_profile_generation if snapshot.cooldown_profile_generation is not None else "none",
        url,
    )
    _log_site_guard_telemetry(logger=logger, snapshot=snapshot, url=url)
    return snapshot


def _site_policy(site: str) -> object:
    return get_session_policy(site)


def _channel_candidates(*, requested_channel: str | None) -> list[str | None]:
    return [requested_channel]


async def apply_interaction_pacing(
    *,
    logger=None,
    reason: str = "interaction",
    site: str = "immobiliare",
    clip_min_sec: float | None = None,
    clip_max_sec: float | None = None,
) -> float:
    return await browser_bootstrap.apply_interaction_pacing(
        logger=logger,
        reason=reason,
        policy=_site_policy(site),
        clip_min_sec=clip_min_sec,
        clip_max_sec=clip_max_sec,
        random_module=random,
        sleep_func=asyncio.sleep,
    )


async def bootstrap_static_resources_cache(context, *, logger, site: str = "immobiliare") -> None:
    await browser_bootstrap.bootstrap_static_resources_cache(
        context,
        logger=logger,
        policy=_site_policy(site),
        pacing_func=apply_interaction_pacing,
    )


async def _close_browser_handles(*, context, browser, logger=None, site: str = "immobiliare") -> None:
    await browser_factory.close_browser_handles(
        context=context,
        browser=browser,
        logger=logger,
        policy=_site_policy(site),
        pacing_func=apply_interaction_pacing,
    )


async def _close_browser_slots(slots: dict[str, BrowserSessionSlot]) -> None:
    await browser_factory.close_browser_slots(slots, policy_by_site=_site_policy, pacing_func=apply_interaction_pacing)


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
    return await browser_factory.prune_site_session_slots(
        slots,
        site=site,
        preserve_owner=preserve_owner,
        policy_by_site=_site_policy,
        pacing_func=apply_interaction_pacing,
    )


def _resolve_channel_executable_path(label: str) -> Path | None:
    if _normalize_channel_label(label) != _DEFAULT_BROWSER_LABEL:
        return None
    try:
        return Path(camoufox_launch_path())
    except Exception:
        return None


def _camoufox_launch_kwargs(
    *,
    headless: bool,
    executable_path: Path | None,
    persistent_profile_dir: Path | None = None,
    persona: CamoufoxPersona | None = None,
) -> dict[str, object]:
    if persona is not None:
        launch_kwargs = json.loads(json.dumps(persona.launch_options))
        launch_kwargs["headless"] = headless
        if persistent_profile_dir is not None:
            launch_kwargs["persistent_context"] = True
            launch_kwargs["user_data_dir"] = str(persistent_profile_dir)
        if executable_path is not None:
            launch_kwargs["executable_path"] = str(executable_path)
        return launch_kwargs
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
    guard_state: dict | None,
    headless: bool,
    logger,
) -> tuple[object | None, object, object, str]:
    launch_error: Exception | None = None
    browser = None
    context = None
    page = None
    policy = _site_policy(site)
    channel_candidates = _channel_candidates(requested_channel=requested_channel)
    for candidate in channel_candidates:
        channel_label = _channel_to_label(candidate)
        executable_path = _resolve_channel_executable_path(channel_label)
        profile_generation = _site_profile_generation(guard_state, site)
        try:
            if profile_dir:
                p_base = Path(profile_dir).expanduser()
                p = _session_profile_root(
                    str(p_base),
                    site,
                    channel_label,
                    profile_generation=profile_generation,
                ) or _profile_dir_for_site_channel(
                    p_base,
                    site,
                    channel_label,
                    profile_generation=profile_generation,
                )
                p.mkdir(parents=True, exist_ok=True)
                persona = _load_or_create_camoufox_persona(
                    site=site,
                    channel_label=channel_label,
                    profile_generation=profile_generation,
                    profile_root=p,
                    executable_path=executable_path,
                    logger=logger,
                )
                launch_persistent_kwargs = _camoufox_launch_kwargs(
                    headless=headless,
                    executable_path=executable_path,
                    persistent_profile_dir=p,
                    persona=persona,
                )
                launch_persistent_kwargs["user_agent"] = policy.user_agent
                context = await AsyncNewBrowser(pw, **launch_persistent_kwargs)
                logger.info(
                    "Launch path acquired fresh identity. site=%s launch_path=fresh policy_site=%s profile=%s channel=%s generation=%s launcher=%s persona=%s user_agent=%s screen=%sx%s window=%sx%s humanize_max_sec=%s",
                    site,
                    policy.site,
                    p,
                    channel_label,
                    profile_generation,
                    "camoufox_path" if executable_path is not None else "camoufox_default",
                    persona.persona_id,
                    policy.user_agent,
                    persona.screen_width,
                    persona.screen_height,
                    persona.window_width,
                    persona.window_height,
                    persona.humanize_max_sec,
                )
            else:
                launch_kwargs = _camoufox_launch_kwargs(
                    headless=headless,
                    executable_path=executable_path,
                )
                browser = await AsyncNewBrowser(pw, **launch_kwargs)
                try:
                    context = await browser.new_context(user_agent=policy.user_agent)
                except TypeError:
                    context = await browser.new_context()
                logger.info(
                    "Launch path acquired fresh identity. site=%s launch_path=fresh policy_site=%s channel=%s launcher=%s user_agent=%s",
                    site,
                    policy.site,
                    channel_label,
                    "camoufox_path" if executable_path is not None else "camoufox_default",
                    policy.user_agent,
                )
            await install_render_context_init_script(context, hardware=policy.hardware, logger=logger)
            await bootstrap_static_resources_cache(context, logger=logger, site=site)
            page = context.pages[0] if context.pages else await context.new_page()
            logger.info(
                "Launch path prepared page. site=%s channel=%s pages=%s bootstrap_completed=%s",
                site,
                channel_label,
                len(context.pages),
                True,
            )
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
            await _close_browser_handles(context=context, browser=browser, logger=logger, site=site)
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


def _profile_dir_for_site_channel(
    base_dir: Path,
    site: str,
    channel_label: str,
    profile_generation: int = 0,
) -> Path:
    site_root = _profile_dir_for_site(base_dir, site)
    generation = max(0, int(profile_generation or 0))
    if generation > 0:
        site_root = site_root / f"gen-{generation:03d}"
    return _profile_dir_for_channel(site_root, channel_label)


def _session_profile_root(
    profile_dir: str | None,
    site: str,
    channel_label: str,
    profile_generation: int = 0,
) -> Path | None:
    if not profile_dir:
        return None
    return _profile_dir_for_site_channel(
        Path(profile_dir).expanduser(),
        site,
        channel_label,
        profile_generation=profile_generation,
    )


def _session_owner_key(*, site: str, channel_label: str, profile_root: Path | None) -> str:
    profile_part = str(profile_root) if profile_root is not None else "ephemeral"
    return f"{site}|{channel_label}|{profile_part}"


def _session_identity(
    *,
    site: str,
    channel_label: str,
    profile_dir: str | None,
    profile_generation: int = 0,
) -> tuple[str, Path | None]:
    profile_root = _session_profile_root(
        profile_dir,
        site,
        channel_label,
        profile_generation=profile_generation,
    )
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
    blocked_params = set(immobiliare_site.SEARCH_PARAM_BLOCKLIST)
    if "idealista.it" in host:
        blocked_params = set(idealista_site.SEARCH_PARAM_BLOCKLIST)
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
        patterns = immobiliare_site.LISTING_PATTERNS
        base = immobiliare_site.BASE_URL
    else:
        patterns = idealista_site.LISTING_PATTERNS
        base = idealista_site.BASE_URL

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


async def _accept_cookies_if_present(page, *, site: str, logger=None) -> None:
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
                await apply_interaction_pacing(logger=logger, reason=f"accept_cookies:selector:{selector}", site=site)
                await node.first.click(timeout=1200)
                if logger is not None:
                    logger.debug("Accepted cookies via selector. selector=%s", selector)
                await page.wait_for_timeout(250)
                return
        except Exception:
            continue
    labels = ["Accetta", "Accetta tutto", "Accept all", "Consenti", "Si, accetto", "Accetto"]
    for label in labels:
        try:
            btn = page.get_by_role("button", name=label)
            if await btn.count() > 0:
                await apply_interaction_pacing(logger=logger, reason=f"accept_cookies:label:{label}", site=site)
                await btn.first.click(timeout=1200)
                if logger is not None:
                    logger.debug("Accepted cookies via label. label=%s", label)
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
                await apply_interaction_pacing(logger=logger, reason=f"dismiss_intrusive_popups:selector:{selector}", site=site)
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
                await apply_interaction_pacing(logger=logger, reason=f"dismiss_intrusive_popups:label:{label}", site=site)
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
            btn = await page.query_selector(", ".join(immobiliare_site.LIST_SWITCH_SELECTORS))
            if btn:
                await apply_interaction_pacing(logger=logger, reason="prepare_site_view:immobiliare_switch_to_list", site=site)
                await btn.click(timeout=1500)
                logger.debug("Applied immobiliare list switch before extraction.")
                await page.wait_for_load_state("domcontentloaded", timeout=nav_timeout_ms)
                await page.wait_for_timeout(500)
        except Exception:
            logger.debug("List switch not applied for immobiliare.")
        await _wait_for_any_selector(
            page,
            list(immobiliare_site.PREPARE_WAIT_SELECTORS),
            timeout_ms=min(15000, nav_timeout_ms),
        )
        await _gentle_scroll(
            page,
            steps=4,
            delay_ms=260,
            selectors=list(immobiliare_site.SCROLL_SELECTORS),
        )
    elif site == "idealista":
        await _wait_for_any_selector(
            page,
            list(idealista_site.PREPARE_WAIT_SELECTORS),
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


def _coerce_detail_touch_count(*, value: object, site: str, logger) -> int:
    if type(value) is int:
        return max(0, value)
    try:
        coerced = int(value or 0)
    except (TypeError, ValueError):
        logger.warning(
            "Non-integer detail touch count returned. site=%s value_type=%s value=%r coerced=0",
            site,
            type(value).__name__,
            value,
        )
        return 0
    logger.warning(
        "Non-integer detail touch count returned. site=%s value_type=%s value=%r coerced=%s",
        site,
        type(value).__name__,
        value,
        max(0, coerced),
    )
    return max(0, coerced)


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
        return 0

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
            await apply_interaction_pacing(
                logger=logger,
                reason=f"idealista_private_only_detail_verification:goto:{card.get('ad_id') or index}",
                site="idealista",
            )
            await page.goto(card["url"], timeout=nav_timeout_ms)
            await page.wait_for_load_state("domcontentloaded", timeout=nav_timeout_ms)
            await page.wait_for_timeout(random.randint(*_IDEALISTA_PRIVATE_ONLY_DETAIL_DELAY_MS))
            await _accept_cookies_if_present(page, site="idealista", logger=logger)
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

            professional_profile_links = await page.locator(idealista_site.DETAIL_PRO_LINK_SELECTOR).count()
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
    host = (urlparse(search_url).hostname or "").lower()
    site = "idealista" if "idealista.it" in host else "immobiliare"
    if request_url != search_url:
        logger.info("Sanitized search URL for navigation. host=%s", (urlparse(search_url).hostname or "").lower())
    await apply_interaction_pacing(logger=logger, reason=f"extract_for_url:goto:{request_url}", site=site)
    response = await page.goto(request_url, timeout=nav_timeout_ms)
    response_status = response.status if response is not None else 0
    await page.wait_for_load_state("domcontentloaded", timeout=nav_timeout_ms)
    await page.wait_for_timeout(wait_after_goto_ms)
    await _accept_cookies_if_present(page, site=site, logger=logger)
    selector_primary_count = 0
    selector_alt_count = 0

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
        return [], FetchOutcome(tier="degraded", code="unsupported_site", http_status=0, detail=search_url), attempt_stats

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
        detail_touch_count = await _verify_idealista_private_only_candidates(
            page=page,
            cards=cards,
            nav_timeout_ms=nav_timeout_ms,
            detail_budget_remaining=detail_budget_remaining,
            db=listing_cache_db,
            search_url=search_url,
            logger=logger,
        )
        attempt_stats.detail_touch_count = _coerce_detail_touch_count(
            value=detail_touch_count,
            site=site,
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
    if raw == _DEFAULT_BROWSER_LABEL:
        return _DEFAULT_BROWSER_LABEL
    raise ValueError("browser_channel must be one of: auto|camoufox")


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
                    preferred_candidates = _channel_candidates(requested_channel=channel)
                    launch_candidates = preferred_candidates
                    preferred_label = _channel_to_label(launch_candidates[0])
                    profile_generation = _site_profile_generation(guard_state, site)
                    preferred_session_owner, _ = _session_identity(
                        site=site,
                        channel_label=preferred_label,
                        profile_dir=profile_dir,
                        profile_generation=profile_generation,
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
                        if _maybe_rotate_site_profile(state=guard_state, site=site, now=now, logger=logger):
                            _save_guard_state(guard_state_path, guard_state)
                            entry = _site_state(guard_state, site)
                            profile_generation = _site_profile_generation(guard_state, site)
                            preferred_session_owner, _ = _session_identity(
                                site=site,
                                channel_label=preferred_label,
                                profile_dir=profile_dir,
                                profile_generation=profile_generation,
                            )
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
                        delay = await apply_interaction_pacing(
                            logger=logger,
                            reason="site_guard_launch_delay",
                            site=site,
                            clip_min_sec=jitter_min,
                            clip_max_sec=jitter_max,
                        )
                        if delay > 0:
                            logger.info(
                                "Site guard launch pacing. site=%s delay_sec=%.2f clip_min_sec=%s clip_max_sec=%s",
                                site,
                                delay,
                                jitter_min,
                                jitter_max,
                            )

                    slot = session_slots.get(preferred_session_owner)
                    if slot is None:
                        previous_channel_label = selected_channel_label
                        browser, context, page, selected_channel_label = await _launch_browser_session(
                            pw=pw,
                            site=site,
                            profile_dir=profile_dir,
                            requested_channel=channel,
                            guard_state=guard_state,
                            headless=headless,
                            logger=logger,
                        )
                        active_session_owner, profile_root = _session_identity(
                            site=site,
                            channel_label=selected_channel_label,
                            profile_dir=profile_dir,
                            profile_generation=_site_profile_generation(guard_state, site),
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
                            "Launch path reused mature identity. site=%s launch_path=reused channel=%s owner=%s slot_reuse_count=%s same_site_profile_reuse_count=%s cross_site_session_reuse_count=%s",
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
                        site_session_replace_count += await _dispose_blocked_profile_if_needed(
                            decision=decision,
                            session_slots=session_slots,
                            profile_dir=profile_dir,
                            site=site,
                            channel_label=selected_channel_label or _DEFAULT_BROWSER_LABEL,
                            entry=entry,
                            logger=logger,
                        )
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
                        entry = _site_state(guard_state, site)
                        site_session_replace_count += await _dispose_blocked_profile_if_needed(
                            decision=decision,
                            session_slots=session_slots,
                            profile_dir=profile_dir,
                            site=site,
                            channel_label=selected_channel_label or _DEFAULT_BROWSER_LABEL,
                            entry=entry,
                            logger=logger,
                        )
                        snapshot = _log_guard_decision(
                            logger=logger,
                            site=site,
                            url=url,
                            outcome=outcome,
                            decision=decision,
                            entry=entry,
                            browser_mode=browser_mode,
                            identity_switch=identity_switch_count,
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
                                            "state": dict(entry),
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
                        entry = _site_state(guard_state, site)
                        site_session_replace_count += await _dispose_blocked_profile_if_needed(
                            decision=decision,
                            session_slots=session_slots,
                            profile_dir=profile_dir,
                            site=site,
                            channel_label=selected_channel_label or _DEFAULT_BROWSER_LABEL,
                            entry=entry,
                            logger=logger,
                        )
                        snapshot = _log_guard_decision(
                            logger=logger,
                            site=site,
                            url=url,
                            outcome=outcome,
                            decision=decision,
                            entry=entry,
                            browser_mode=browser_mode,
                            identity_switch=identity_switch_count,
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
                                            "state": dict(entry),
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
                        entry = _site_state(guard_state, site)
                        site_session_replace_count += await _dispose_blocked_profile_if_needed(
                            decision=decision,
                            session_slots=session_slots,
                            profile_dir=profile_dir,
                            site=site,
                            channel_label=selected_channel_label or _DEFAULT_BROWSER_LABEL,
                            entry=entry,
                            logger=logger,
                        )
                        snapshot = _log_guard_decision(
                            logger=logger,
                            site=site,
                            url=url,
                            outcome=outcome,
                            decision=decision,
                            entry=entry,
                            browser_mode=browser_mode,
                            identity_switch=identity_switch_count,
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
                                            "state": dict(entry),
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
                await _close_browser_handles(context=context, browser=browser, site=active_session_site or "immobiliare")
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
