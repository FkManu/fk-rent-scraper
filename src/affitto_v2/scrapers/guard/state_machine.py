from __future__ import annotations

from datetime import timedelta


RUN_STATE_TABLE = {
    "healthy": "healthy",
    "suspect": "suspect",
    "degraded": "degraded",
    "cooling": "cooldown",
    "blocked": "blocked",
    "challenge": "challenge_seen",
}


def state_transition_label(*, entry: dict, outcome) -> str:
    if outcome.tier == "cooling":
        return "cooldown"
    if outcome.tier == "healthy":
        return "warmup" if bool(entry.get("warmup_active")) else "stable"
    if outcome.tier == "suspect":
        return "suspect"
    if outcome.tier == "degraded":
        return "degraded"
    if outcome.challenge_visible or outcome.code in {"interstitial_datadome", "challenge_visible"}:
        return RUN_STATE_TABLE["challenge"]
    if outcome.tier == "blocked":
        return RUN_STATE_TABLE["blocked"]
    return outcome.tier or "unknown"


def risk_pause_reason(*, outcome, decision) -> str:
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


def build_telemetry_snapshot(
    *,
    telemetry_cls,
    site: str,
    entry: dict,
    outcome,
    decision,
    now,
    browser_mode: str,
    channel_label: str,
    identity_switch: int,
    attempt_stats,
    manual_assist_used: bool,
    session_age_sec,
    profile_age_sec,
    profile_generation,
    cooldown_profile_generation,
    assist_entry_mode: str = "",
):
    return telemetry_cls(
        site=site,
        browser_mode=browser_mode,
        channel_label=channel_label,
        identity_switch=identity_switch,
        session_age_sec=session_age_sec,
        profile_age_sec=profile_age_sec,
        profile_generation=profile_generation,
        cooldown_profile_generation=cooldown_profile_generation,
        detail_touch_count=attempt_stats.detail_touch_count,
        retry_count=attempt_stats.retry_count,
        risk_pause_reason=risk_pause_reason(outcome=outcome, decision=decision),
        outcome_tier=outcome.tier,
        outcome_code=outcome.code,
        cooldown_origin=str(entry.get("last_block_family") or ""),
        manual_assist_used=manual_assist_used,
        state_transition=state_transition_label(entry=entry, outcome=outcome),
        assist_entry_mode=assist_entry_mode,
    )


def advance_run_state(*, entry: dict, outcome, decision, run_risk, mark_assist_required) -> tuple[str, str]:
    previous_state = run_risk.current_state
    if run_risk.assist_required:
        run_risk.current_state = "assist_required"
        return (previous_state, run_risk.current_state)

    if outcome.code in {"interstitial_datadome", "challenge_visible"} or outcome.challenge_visible:
        run_risk.challenge_count += 1
        run_risk.degraded_streak = 0
        run_risk.current_state = RUN_STATE_TABLE["challenge"]
        if run_risk.challenge_count >= 2:
            mark_assist_required(run_risk, "challenge_repeat")
        return (previous_state, run_risk.current_state)

    next_state = RUN_STATE_TABLE.get(outcome.tier, run_risk.current_state)
    if outcome.tier == "healthy":
        run_risk.degraded_streak = 0
        run_risk.challenge_count = 0
        run_risk.current_state = "warmup" if bool(entry.get("warmup_active")) else "stable"
    elif outcome.tier == "suspect":
        run_risk.current_state = next_state
    elif outcome.tier == "degraded":
        run_risk.degraded_streak += 1
        run_risk.current_state = next_state
        if run_risk.degraded_streak >= 2:
            mark_assist_required(run_risk, "persistent_degraded")
    elif outcome.tier == "cooling":
        run_risk.current_state = next_state
    elif outcome.tier == "blocked":
        run_risk.current_state = next_state
    return (previous_state, run_risk.current_state)


def apply_guard_outcome(
    *,
    decision_cls,
    state: dict,
    site: str,
    outcome,
    now,
    base_sec: int,
    max_sec: int,
    channel_label: str,
    site_state,
    profile_generation,
    rotate_site_profile,
    is_warmup_entry,
    blocked_family_from_outcome,
    interstitial_probe_delay_sec,
    hard_block_profile_reset_sites: set[str],
):
    entry = site_state(state, site)
    previous_tier = str(entry.get("last_outcome_tier") or "")
    previous_code = str(entry.get("last_outcome_code") or "")
    previous_strikes = int(entry.get("strikes") or 0)
    was_warmup = is_warmup_entry(entry)
    transition = previous_tier != outcome.tier or previous_code != outcome.code

    entry["warmup_active"] = was_warmup
    if was_warmup and not str(entry.get("warmup_started_utc") or "").strip():
        entry["warmup_started_utc"] = now.isoformat()
    entry["last_attempt_utc"] = now.isoformat()
    entry["last_outcome_tier"] = outcome.tier
    entry["last_outcome_code"] = outcome.code
    entry["last_outcome_detail"] = (outcome.detail or "")[:240]
    blocked_family = blocked_family_from_outcome(outcome)

    if outcome.tier == "cooling":
        return decision_cls(
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
        entry["cooldown_profile_generation"] = ""
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
        return decision_cls(
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
        cooldown_generation = profile_generation(entry)
        destroy_persistent_profile = False
        if blocked_family == "hard_block" and site in hard_block_profile_reset_sites:
            previous_generation, _ = rotate_site_profile(
                entry,
                now=now,
                reason=f"hard_block:{outcome.code or 'hard_block'}",
            )
            cooldown_generation = previous_generation
            destroy_persistent_profile = True
        if was_warmup and int(entry.get("warmup_failures") or 0) <= 1:
            entry["strikes"] = 0
            entry["cooldown_until_utc"] = ""
            entry["cooldown_profile_generation"] = ""
            return decision_cls(
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
        entry["cooldown_profile_generation"] = cooldown_generation
        if blocked_family == "interstitial":
            probe_delay = interstitial_probe_delay_sec(base_sec=base_sec, cooldown_sec=cooldown)
            entry["probe_after_utc"] = (now + timedelta(seconds=probe_delay)).isoformat() if probe_delay > 0 else ""
            entry["probe_attempts"] = 0
        else:
            entry["probe_after_utc"] = ""
            entry["probe_attempts"] = 0
        return decision_cls(
            action=action,
            cooldown_sec=cooldown,
            transition=transition,
            previous_tier=previous_tier,
            previous_code=previous_code,
            destroy_persistent_profile=destroy_persistent_profile,
            forced_cooldown=True,
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
            entry["cooldown_profile_generation"] = profile_generation(entry)
            return decision_cls(
                action=action,
                cooldown_sec=cooldown,
                transition=transition,
                previous_tier=previous_tier,
                previous_code=previous_code,
                forced_cooldown=True,
            )
        return decision_cls(
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
        entry["cooldown_profile_generation"] = profile_generation(entry)
        return decision_cls(
            action=action,
            cooldown_sec=cooldown,
            transition=transition,
            previous_tier=previous_tier,
            previous_code=previous_code,
            forced_cooldown=True,
        )
    return decision_cls(
        action="warmup_observe_degraded" if was_warmup else "observe_degraded",
        transition=transition,
        previous_tier=previous_tier,
        previous_code=previous_code,
    )


__all__ = [
    "RUN_STATE_TABLE",
    "advance_run_state",
    "apply_guard_outcome",
    "build_telemetry_snapshot",
    "risk_pause_reason",
    "state_transition_label",
]
