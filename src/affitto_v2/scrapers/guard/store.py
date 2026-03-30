from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path


def new_guard_site_entry() -> dict[str, object]:
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


def load_guard_state(*, path: Path, guard_state_version: int, default_browser_label: str, channel_labels, normalize_channel_label) -> dict:
    default = {"version": guard_state_version, "last_channel": default_browser_label, "sites": {}}
    try:
        if not path.exists():
            return default
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return default
        sites = raw.get("sites", {})
        if not isinstance(sites, dict):
            sites = {}
        last_channel = normalize_channel_label(raw.get("last_channel"))
        if last_channel not in channel_labels:
            last_channel = default_browser_label
        return {
            "version": guard_state_version,
            "last_channel": last_channel,
            "sites": sites,
        }
    except Exception:
        return default


def save_guard_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def service_runtime_site_slot_snapshot(runtime, *, now_monotonic: float | None = None) -> dict[str, dict[str, object]]:
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


def prune_guard_state_sites(*, state: dict, search_urls: list[str], site_key_from_url) -> list[str]:
    sites = state.get("sites")
    if not isinstance(sites, dict):
        state["sites"] = {}
        return []
    allowed_sites = {site_key_from_url(url) for url in search_urls if url}
    if not allowed_sites:
        return []
    removed = sorted(site for site in list(sites) if site not in allowed_sites)
    for site in removed:
        sites.pop(site, None)
    return removed


def site_state(state: dict, site: str) -> dict:
    sites = state.setdefault("sites", {})
    entry = sites.get(site)
    if not isinstance(entry, dict):
        entry = new_guard_site_entry()
    for key, value in new_guard_site_entry().items():
        entry.setdefault(key, value)
    sites[site] = entry
    return entry


def profile_generation(entry: dict) -> int:
    try:
        value = int(entry.get("profile_generation") or 0)
    except (TypeError, ValueError):
        value = 0
    return max(0, value)


def ensure_site_profile_tracking(*, entry: dict, now: datetime, parse_utc_iso) -> bool:
    changed = False
    generation = profile_generation(entry)
    if generation != entry.get("profile_generation"):
        entry["profile_generation"] = generation
        changed = True
    created_at = parse_utc_iso(str(entry.get("profile_created_utc") or ""))
    if created_at is None:
        entry["profile_created_utc"] = now.isoformat()
        changed = True
    return changed


def site_profile_age_sec(*, entry: dict, now: datetime, parse_utc_iso) -> int:
    created_at = parse_utc_iso(str(entry.get("profile_created_utc") or ""))
    if created_at is None:
        return 0
    return max(0, int((now - created_at).total_seconds()))


def site_profile_rotation_age_cap_sec(*, site: str, rotation_caps: dict[str, int]) -> int:
    return max(0, int(rotation_caps.get(site, 0) or 0))


def rotate_site_profile(entry: dict, *, now: datetime, reason: str) -> tuple[int, int]:
    previous_generation = profile_generation(entry)
    next_generation = previous_generation + 1
    entry["profile_generation"] = next_generation
    entry["profile_created_utc"] = now.isoformat()
    entry["profile_rotated_utc"] = now.isoformat()
    entry["profile_quarantine_reason"] = reason
    return (previous_generation, next_generation)


def maybe_rotate_site_profile(
    *,
    state: dict,
    site: str,
    now: datetime,
    logger,
    parse_utc_iso,
    rotation_caps: dict[str, int],
) -> bool:
    entry = site_state(state, site)
    changed = ensure_site_profile_tracking(entry=entry, now=now, parse_utc_iso=parse_utc_iso)
    age_cap_sec = site_profile_rotation_age_cap_sec(site=site, rotation_caps=rotation_caps)
    if age_cap_sec <= 0:
        return changed
    profile_age = site_profile_age_sec(entry=entry, now=now, parse_utc_iso=parse_utc_iso)
    if profile_age < age_cap_sec:
        return changed
    previous_generation, next_generation = rotate_site_profile(entry, now=now, reason="profile_age_cap")
    logger.info(
        "Preemptive site profile rotation. site=%s previous_generation=%s next_generation=%s profile_age_sec=%s age_cap_sec=%s",
        site,
        previous_generation,
        next_generation,
        profile_age,
        age_cap_sec,
    )
    return True


def site_profile_generation(state: dict | None, site: str) -> int:
    if state is None:
        return 0
    return profile_generation(site_state(state, site))


def is_warmup_entry(entry: dict) -> bool:
    raw = entry.get("warmup_active")
    if isinstance(raw, bool):
        return raw
    return not bool(str(entry.get("last_success_utc") or "").strip())


def guard_phase_label(entry: dict) -> str:
    return "warmup" if is_warmup_entry(entry) else "stable"


def cooldown_profile_generation(entry: dict) -> int | None:
    raw = entry.get("cooldown_profile_generation")
    if raw in ("", None):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return max(0, value)


def cooldown_remaining_sec(*, state: dict, site: str, now: datetime, parse_utc_iso) -> int:
    entry = site_state(state, site)
    until = parse_utc_iso(str(entry.get("cooldown_until_utc") or ""))
    if until is None:
        return 0
    cooldown_generation_value = cooldown_profile_generation(entry)
    if cooldown_generation_value is not None and profile_generation(entry) != cooldown_generation_value:
        return 0
    delta = int((until - now).total_seconds())
    return delta if delta > 0 else 0


__all__ = [
    "cooldown_profile_generation",
    "cooldown_remaining_sec",
    "ensure_site_profile_tracking",
    "guard_phase_label",
    "is_warmup_entry",
    "load_guard_state",
    "maybe_rotate_site_profile",
    "new_guard_site_entry",
    "profile_generation",
    "prune_guard_state_sites",
    "rotate_site_profile",
    "save_guard_state",
    "service_runtime_site_slot_snapshot",
    "site_profile_age_sec",
    "site_profile_generation",
    "site_profile_rotation_age_cap_sec",
    "site_state",
]
