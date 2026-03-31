from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..db import ListingRecord


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
    canvas_r_offset: int
    canvas_g_offset: int
    canvas_b_offset: int
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


__all__ = [
    "BrowserSessionSlot",
    "CamoufoxPersona",
    "DriftDiagnostic",
    "ExtractionMetrics",
    "FetchAttemptStats",
    "FetchOutcome",
    "GuardDecision",
    "LiveFetchBlocked",
    "LiveFetchRunReport",
    "LiveFetchServiceRuntime",
    "RiskBudget",
    "RunRiskState",
    "TelemetrySnapshot",
]
