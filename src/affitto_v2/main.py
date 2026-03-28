from __future__ import annotations

import asyncio
import argparse
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from .config_store import ConfigError, load_config, load_or_create_config, save_config
from .db import Database, ListingRecord
from .email_setup import (
    get_email_configuration_status,
    prepare_email_configuration,
    save_email_test_record,
)
from .email_profiles import (
    default_profiles_path,
    load_or_create_profiles,
    upsert_profile,
)
from .logging_live import LiveLogPublisher, setup_logging
from .models import AppConfig, EmailSenderProfile
from .notifiers import (
    EmailNotificationError,
    EmailNotifier,
    TelegramNotificationError,
    TelegramNotifier,
)
from .paths import APP_LOG_FILE, ensure_runtime_dirs, resolve_config_path, resolve_db_path
from .pipeline import PipelineRunOptions, process_listings
from .scrapers import (
    LiveFetchServiceRuntime,
    close_live_fetch_service_runtime,
    fetch_live_once,
    recycle_live_fetch_site_runtime,
    service_runtime_site_slot_snapshot,
)


class RuntimeJobError(RuntimeError):
    pass


@dataclass(frozen=True)
class NotifierBootstrapState:
    email_notifier: EmailNotifier | None = None
    telegram_notifier: TelegramNotifier | None = None
    email_requested: bool = False
    telegram_requested: bool = False
    email_degraded_reason: str = ""
    telegram_degraded_reason: str = ""


@dataclass(frozen=True)
class LiveServicePolicy:
    cadence_sec: int
    max_cycle_sec: int
    max_cycles: int | None = None
    restart_on_failure: bool = True


@dataclass(slots=True)
class LiveServiceState:
    current_state: str = "warmup"
    consecutive_failures: int = 0
    consecutive_overruns: int = 0
    consecutive_backlog_cycles: int = 0
    consecutive_run_degraded_cycles: int = 0
    assist_required: bool = False
    assist_reason: str = ""


@dataclass(frozen=True)
class RuntimeDispositionDecision:
    action: str = "keep"
    site: str = ""
    reason: str = ""


_PREEMPTIVE_SITE_SLOT_RECYCLE_LIMITS: dict[str, dict[str, int]] = {
    "immobiliare": {
        "max_age_sec": 5400,
        "max_reuse_count": 12,
    }
}


def _maybe_preemptive_site_slot_recycle(
    *,
    slot_summary: dict[str, dict[str, object]],
    logger,
) -> RuntimeDispositionDecision:
    if not slot_summary:
        return RuntimeDispositionDecision()
    for site, limits in _PREEMPTIVE_SITE_SLOT_RECYCLE_LIMITS.items():
        snapshot = slot_summary.get(site)
        if not snapshot:
            continue
        age_sec = int(snapshot.get("max_age_sec", 0) or 0)
        reuse_count = int(snapshot.get("max_reuse_count", 0) or 0)
        if age_sec < int(limits.get("max_age_sec", 0) or 0) and reuse_count < int(
            limits.get("max_reuse_count", 0) or 0
        ):
            continue
        reason_parts: list[str] = []
        if age_sec >= int(limits.get("max_age_sec", 0) or 0):
            reason_parts.append("session_age_cap")
        if reuse_count >= int(limits.get("max_reuse_count", 0) or 0):
            reason_parts.append("slot_reuse_cap")
        logger.info(
            "Preemptive site slot recycle candidate. site=%s age_sec=%s reuse_count=%s owner_count=%s channel=%s thresholds=%s",
            site,
            age_sec,
            reuse_count,
            int(snapshot.get("owner_count", 0) or 0),
            str(snapshot.get("channel_label", "") or "unknown"),
            limits,
        )
        return RuntimeDispositionDecision(
            action="recycle_site_slot",
            site=site,
            reason="+".join(reason_parts) or "preventive_recycle",
        )
    return RuntimeDispositionDecision()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Affitto v2 CLI")
    parser.add_argument(
        "command",
        nargs="?",
        default="doctor",
        choices=[
            "init-config",
            "validate-config",
            "init-db",
            "doctor",
            "gui",
            "init-email-profiles",
            "list-email-profiles",
            "upsert-email-profile",
            "email-status",
            "test-email",
            "test-pipeline",
            "fetch-live-once",
            "fetch-live-service",
        ],
        help="Command to run.",
    )
    parser.add_argument("--config", default="", help="Optional config file override.")
    parser.add_argument("--profiles", default="", help="Optional email profiles file override.")
    parser.add_argument("--db", default="", help="Optional sqlite path override.")
    parser.add_argument("--log-level", default="", help="Optional log level override.")

    # Email test
    parser.add_argument("--dry-run", action="store_true", help="For test-email: check SMTP auth only, no send.")
    parser.add_argument("--email-to", default="", help="Override destination address.")
    parser.add_argument("--email-subject", default="Affitto v2 - Test email", help="Custom subject.")
    parser.add_argument("--email-body", default="Messaggio di test inviato da Affitto v2.", help="Custom body.")

    # Sender profile management
    parser.add_argument("--profile-id", default="default_sender", help="Profile id.")
    parser.add_argument(
        "--profile-provider",
        default="gmail",
        help="Profile provider: gmail|outlook|brevo|mailjet|smtp2go|resend|custom.",
    )
    parser.add_argument("--profile-from", default="", help="Profile from address.")
    parser.add_argument("--profile-user", default="", help="Profile smtp username.")
    parser.add_argument("--profile-password", default="", help="Profile app password.")
    parser.add_argument("--profile-host", default="", help="Profile smtp host (optional for preset providers).")
    parser.add_argument("--profile-port", type=int, default=0, help="Profile smtp port (preset default when omitted).")
    parser.add_argument(
        "--profile-security-mode",
        default="",
        help="Profile security mode: starttls|ssl_tls|none. Optional; preset default is used when omitted.",
    )
    parser.add_argument(
        "--profile-starttls",
        default="",
        help="Legacy STARTTLS flag override: true|false. Prefer --profile-security-mode.",
    )

    # Pipeline test + overrides (cascade)
    parser.add_argument(
        "--notify-mode",
        default="config",
        help="Notification mode: config|none|telegram|email|both.",
    )
    parser.add_argument(
        "--send-real-notifications",
        action="store_true",
        help="For pipeline commands: actually send telegram/email instead of dry-run logs.",
    )
    parser.add_argument("--simulate-count", type=int, default=3, help="Number of mock listings.")
    parser.add_argument("--simulate-site", default="idealista", help="Mock site: idealista|immobiliare.")
    parser.add_argument("--simulate-run-id", default="", help="Optional run id to make generated ads unique.")
    parser.add_argument("--simulate-duplicate", action="store_true", help="Append one duplicate listing.")
    parser.add_argument("--simulate-blocked-agency", action="store_true", help="Mark first listing as blocked.")
    parser.add_argument("--blocked-pattern", default=".*testspam.*", help="Regex for blocked agency test.")
    parser.add_argument("--override-cycle-minutes", type=int, default=0, help="Runtime override: cycle minutes.")
    parser.add_argument(
        "--override-max-listings-per-page",
        type=int,
        default=0,
        help="Runtime override: max listings per page.",
    )
    parser.add_argument(
        "--override-captcha-mode",
        default="",
        help="Runtime override: pause_and_notify|skip_and_notify|stop_and_notify.",
    )
    parser.add_argument(
        "--override-extract-fields",
        default="",
        help="Extraction override list: price,zone,agency",
    )
    parser.add_argument(
        "--email-sender-mode",
        default="",
        help="Email sender mode override: custom|profile.",
    )
    parser.add_argument(
        "--email-sender-profile-id",
        default="",
        help="Email sender profile id override (when sender mode is profile).",
    )
    parser.add_argument(
        "--save-overrides",
        action="store_true",
        help="Persist override values into app_config.json.",
    )
    parser.add_argument("--headed", action="store_true", help="Use visible browser window for live fetch.")
    parser.add_argument(
        "--browser-channel",
        default="camoufox",
        help="Browser backend: auto|camoufox (default: camoufox).",
    )
    parser.add_argument("--max-per-site", type=int, default=0, help="Live fetch cap per site.")
    parser.add_argument("--nav-timeout-ms", type=int, default=45000, help="Live fetch navigation timeout.")
    parser.add_argument("--wait-after-goto-ms", type=int, default=1200, help="Live fetch wait after goto.")
    parser.add_argument("--captcha-wait-sec", type=int, default=180, help="Manual captcha wait time when mode=pause_and_notify.")
    parser.add_argument(
        "--profile-dir",
        default="",
        help="Persistent browser profile directory for live fetch (default: runtime/camoufox-profile).",
    )
    parser.add_argument(
        "--save-live-debug",
        action="store_true",
        help="Save HTML/screenshot artifacts when live fetch hits captcha or finds no cards.",
    )
    parser.add_argument(
        "--live-debug-dir",
        default="",
        help="Live debug artifacts directory (default: runtime/debug when enabled).",
    )
    parser.add_argument(
        "--disable-site-guard",
        action="store_true",
        help="Disable anti-block protections (cooldown/jitter/guard state).",
    )
    parser.add_argument(
        "--guard-jitter-min-sec",
        type=int,
        default=2,
        help="Minimum random delay before each site fetch when site guard is enabled.",
    )
    parser.add_argument(
        "--guard-jitter-max-sec",
        type=int,
        default=6,
        help="Maximum random delay before each site fetch when site guard is enabled.",
    )
    parser.add_argument(
        "--guard-base-cooldown-min",
        type=int,
        default=30,
        help="Base cooldown minutes after a block/captcha detection (exponential backoff).",
    )
    parser.add_argument(
        "--guard-max-cooldown-min",
        type=int,
        default=360,
        help="Max cooldown minutes after repeated block/captcha detections.",
    )
    parser.add_argument(
        "--guard-state-file",
        default="",
        help="Site guard state JSON path (default: runtime/site_guard_state.json).",
    )
    parser.add_argument(
        "--guard-reset-state",
        action="store_true",
        help="Reset site-guard strikes/cooldowns before this run.",
    )
    parser.add_argument(
        "--guard-ignore-cooldown",
        action="store_true",
        help="Ignore active site cooldown for this run (still records new strikes).",
    )
    parser.add_argument(
        "--cycle-max-minutes",
        type=int,
        default=10,
        help="For fetch-live-service: hard overrun threshold per cycle in minutes.",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=0,
        help="For fetch-live-service: stop after N cycles (0 = run continuously).",
    )
    parser.add_argument(
        "--service-stop-flag",
        default="",
        help="For fetch-live-service: optional stop-request flag file used for graceful shutdown.",
    )
    return parser


def _resolve_log_level(raw: str) -> str:
    candidate = (raw or os.getenv("AFFITTO_V2_LOG_LEVEL") or "INFO").strip().upper()
    return candidate if candidate in {"DEBUG", "INFO", "WARNING", "ERROR"} else "INFO"


def _flatten_error_text(exc: Exception) -> str:
    return " ".join(str(exc).split()).strip()


def _validate_runtime_config(config_path: Path) -> None:
    config = load_config(config_path)
    if config.runtime.cycle_minutes < 5:
        raise ConfigError("cycle_minutes cannot be lower than 5.")


def _clone_args_without_save_overrides(args: argparse.Namespace) -> argparse.Namespace:
    cloned = argparse.Namespace(**vars(args))
    cloned.save_overrides = False
    return cloned


def _resolve_db_from_config(config_path: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate
    if candidate.parts and candidate.parts[0].lower() == "runtime":
        return (config_path.parent.parent / candidate).resolve()
    return (config_path.parent / candidate).resolve()


def _resolve_profiles_path(config_path: Path, raw: str) -> Path:
    if raw:
        return Path(raw).expanduser()
    return default_profiles_path(config_path)


def _resolve_service_stop_flag_path(raw: str) -> Path | None:
    value = (raw or "").strip()
    if not value:
        return None
    return Path(value).expanduser()


def _clear_service_stop_flag(path: Path | None) -> None:
    if path is None or not path.exists():
        return
    path.unlink()


def _is_service_stop_requested(path: Path | None) -> bool:
    return bool(path is not None and path.exists())


def _sleep_until_next_cycle_or_stop(
    *,
    sleep_sec: float,
    stop_flag_path: Path | None,
    monotonic_fn=time.monotonic,
    sleep_fn=time.sleep,
) -> bool:
    remaining = max(0.0, sleep_sec)
    while remaining > 0:
        if _is_service_stop_requested(stop_flag_path):
            return True
        step = min(1.0, remaining)
        sleep_fn(step)
        remaining -= step
    return _is_service_stop_requested(stop_flag_path)


def _parse_true_false(value: str) -> bool:
    v = (value or "").strip().lower()
    if v in {"true", "1", "yes", "y"}:
        return True
    if v in {"false", "0", "no", "n"}:
        return False
    raise ConfigError(f"Invalid boolean value: {value}")


def _parse_security_mode(value: str) -> str:
    v = (value or "").strip().lower()
    if not v:
        return ""
    aliases = {"ssl": "ssl_tls", "ssl/tls": "ssl_tls", "plain": "none"}
    v = aliases.get(v, v)
    allowed = {"starttls", "ssl_tls", "none"}
    if v not in allowed:
        raise ConfigError(f"Invalid security mode: {value}. Allowed: {', '.join(sorted(allowed))}")
    return v


def _parse_notify_mode(value: str) -> str:
    v = (value or "config").strip().lower()
    allowed = {"config", "none", "telegram", "email", "both"}
    if v not in allowed:
        raise ConfigError(f"Invalid notify mode: {value}. Allowed: {', '.join(sorted(allowed))}")
    return v


def _parse_browser_channel(value: str) -> str:
    v = (value or "camoufox").strip().lower()
    allowed = {"auto", "camoufox"}
    if v not in allowed:
        raise ConfigError(f"Invalid browser channel: {value}. Allowed: {', '.join(sorted(allowed))}")
    return v


def _site_guard_key(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "idealista.it" in host:
        return "idealista"
    if "immobiliare.it" in host:
        return "immobiliare"
    return host or "unknown"


def _reset_site_guard_state(path: Path, search_urls: list[str], logger) -> None:
    sites: dict[str, dict[str, object]] = {}
    for url in search_urls:
        key = _site_guard_key(url)
        if key not in sites:
            sites[key] = {
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
            }
    for entry in sites.values():
        entry["profile_generation"] = 0
        entry["profile_created_utc"] = ""
        entry["profile_rotated_utc"] = ""
        entry["profile_quarantine_reason"] = ""
    payload = {"version": 7, "last_channel": "camoufox", "sites": sites}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("Site guard state reset. file=%s sites=%s", path, len(sites))


def _apply_config_overrides(config: AppConfig, args: argparse.Namespace) -> tuple[AppConfig, list[str]]:
    changed: list[str] = []
    data = config.model_dump()

    if args.override_cycle_minutes > 0:
        data["runtime"]["cycle_minutes"] = args.override_cycle_minutes
        changed.append("runtime.cycle_minutes")
    if args.override_max_listings_per_page > 0:
        data["runtime"]["max_listings_per_page"] = args.override_max_listings_per_page
        changed.append("runtime.max_listings_per_page")
    if args.override_captcha_mode:
        data["runtime"]["captcha_mode"] = args.override_captcha_mode.strip()
        changed.append("runtime.captcha_mode")
    if args.override_extract_fields:
        chosen = {x.strip().lower() for x in args.override_extract_fields.split(",") if x.strip()}
        allowed = {"price", "zone", "agency"}
        invalid = sorted(chosen - allowed)
        if invalid:
            raise ConfigError(f"Invalid extract field(s): {', '.join(invalid)}")
        data["extraction"]["extract_price"] = "price" in chosen
        data["extraction"]["extract_zone"] = "zone" in chosen
        data["extraction"]["extract_agency"] = "agency" in chosen
        changed.append("extraction.*")
    if args.email_to:
        data["email"]["to_address"] = args.email_to.strip()
        changed.append("email.to_address")
    if args.email_sender_mode:
        mode = args.email_sender_mode.strip().lower()
        if mode not in {"custom", "profile"}:
            raise ConfigError("email_sender_mode must be custom|profile.")
        data["email"]["sender_mode"] = mode
        changed.append("email.sender_mode")
    if args.email_sender_profile_id:
        data["email"]["sender_profile_id"] = args.email_sender_profile_id.strip()
        changed.append("email.sender_profile_id")
    if args.notify_mode and args.save_overrides:
        nm = _parse_notify_mode(args.notify_mode)
        if nm == "none":
            data["telegram"]["enabled"] = False
            data["email"]["enabled"] = False
        elif nm == "telegram":
            data["telegram"]["enabled"] = True
            data["email"]["enabled"] = False
        elif nm == "email":
            data["telegram"]["enabled"] = False
            data["email"]["enabled"] = True
        elif nm == "both":
            data["telegram"]["enabled"] = True
            data["email"]["enabled"] = True
        changed.append("notifications.enabled")

    validated = AppConfig.model_validate(data)
    return validated, changed


def _run_email_test(config_path: Path, profiles_path: Path, args: argparse.Namespace, logger) -> None:
    config = load_config(config_path)
    config, changed = _apply_config_overrides(config, args)
    if args.save_overrides and changed:
        save_config(config, config_path)
        logger.info("Saved config overrides: %s", ", ".join(sorted(set(changed))))

    db_path = _resolve_db_from_config(config_path, config.storage.db_path) if not args.db else resolve_db_path(args.db)
    db = Database(db_path)
    db.init_schema()
    prepared = prepare_email_configuration(config, profiles_path)
    notifier = EmailNotifier.from_config(prepared.resolved_config)
    if args.dry_run:
        try:
            notifier.check_connection()
        except EmailNotificationError as exc:
            save_email_test_record(
                db,
                prepared=prepared,
                kind="connection",
                outcome="error",
                message=str(exc),
            )
            raise
        save_email_test_record(
            db,
            prepared=prepared,
            kind="connection",
            outcome="ok",
            message="Test connessione SMTP riuscito.",
        )
        logger.info(
            "SMTP connection test passed. host=%s port=%s security=%s user=%s sender_mode=%s",
            prepared.resolved_config.smtp_host,
            prepared.resolved_config.smtp_port,
            prepared.resolved_config.security_mode,
            prepared.resolved_config.smtp_username,
            config.email.sender_mode,
        )
        return

    try:
        result = notifier.send_message(
            subject=args.email_subject,
            body_text=args.email_body,
            to_address=args.email_to or None,
        )
    except EmailNotificationError as exc:
        save_email_test_record(
            db,
            prepared=prepared,
            kind="send",
            outcome="error",
            message=str(exc),
        )
        raise
    save_email_test_record(
        db,
        prepared=prepared,
        kind="send",
        outcome="ok",
        message=f"Test invio riuscito verso {result.recipient}.",
    )
    logger.info(
        "Test email sent. to=%s subject=%s ts_utc=%s sender_mode=%s",
        result.recipient,
        result.subject,
        result.timestamp_utc,
        config.email.sender_mode,
    )


def _run_email_status(config_path: Path, profiles_path: Path, args: argparse.Namespace, logger) -> None:
    config = load_config(config_path)
    config, changed = _apply_config_overrides(config, args)
    if args.save_overrides and changed:
        save_config(config, config_path)
        logger.info("Saved config overrides: %s", ", ".join(sorted(set(changed))))

    db_path = _resolve_db_from_config(config_path, config.storage.db_path) if not args.db else resolve_db_path(args.db)
    db = Database(db_path)
    db.init_schema()
    status = get_email_configuration_status(config, profiles_path=profiles_path, db=db)
    logger.info(
        "Email status. state=%s label=%s provider=%s sender_mode=%s can_test=%s verified=%s",
        status.state,
        status.label,
        status.provider or config.email.provider,
        status.sender_mode or config.email.sender_mode,
        status.can_test,
        status.verified,
    )
    if status.detail:
        logger.info("Email status detail: %s", status.detail)
    if status.last_test_kind:
        logger.info(
            "Email last test. kind=%s ts_utc=%s message=%s",
            status.last_test_kind,
            status.last_test_at_utc,
            status.last_test_message,
        )


def _cmd_init_email_profiles(profiles_path: Path, logger) -> None:
    profiles = load_or_create_profiles(profiles_path)
    logger.info("Email profiles ready at %s. profiles=%s", profiles_path, len(profiles))


def _cmd_list_email_profiles(profiles_path: Path, logger) -> None:
    profiles = load_or_create_profiles(profiles_path)
    if not profiles:
        logger.info("No email profiles found at %s", profiles_path)
        return
    for profile_id in sorted(profiles.keys()):
        p = profiles[profile_id]
        logger.info(
            "profile=%s provider=%s from=%s smtp=%s:%s security=%s",
            p.profile_id,
            p.provider,
            p.from_address,
            p.smtp_host,
            p.smtp_port,
            p.security_mode,
        )


def _cmd_upsert_email_profile(profiles_path: Path, args: argparse.Namespace, logger) -> None:
    provider = args.profile_provider.strip().lower()
    if provider not in {"gmail", "outlook", "brevo", "mailjet", "smtp2go", "resend", "custom"}:
        raise ConfigError("profile-provider must be gmail|outlook|brevo|mailjet|smtp2go|resend|custom.")
    security_mode = _parse_security_mode(args.profile_security_mode)
    legacy_starttls = None
    if args.profile_starttls.strip():
        legacy_starttls = _parse_true_false(args.profile_starttls)
    profile = EmailSenderProfile(
        profile_id=args.profile_id.strip(),
        provider=provider,
        from_address=args.profile_from,
        smtp_username=args.profile_user,
        app_password=args.profile_password,
        smtp_host=args.profile_host,
        smtp_port=args.profile_port,
        security_mode=security_mode,
        use_starttls=legacy_starttls,
    )
    upsert_profile(profiles_path, profile)
    logger.info(
        "Email profile upserted: id=%s provider=%s smtp=%s:%s security=%s",
        profile.profile_id,
        profile.provider,
        profile.smtp_host,
        profile.smtp_port,
        profile.security_mode,
    )


def _pick_search_url(config: AppConfig, site: str) -> str:
    target = site.strip().lower()
    for url in config.search_urls:
        host = (urlparse(url).hostname or "").lower()
        if target == "idealista" and "idealista.it" in host:
            return url
        if target == "immobiliare" and "immobiliare.it" in host:
            return url
    return config.search_urls[0]


def _build_mock_listings(config: AppConfig, args: argparse.Namespace) -> list[ListingRecord]:
    site = args.simulate_site.strip().lower()
    if site not in {"idealista", "immobiliare"}:
        raise ConfigError("simulate-site must be idealista|immobiliare.")
    count = max(1, int(args.simulate_count))
    search_url = _pick_search_url(config, site)
    run_tag = args.simulate_run_id.strip() or str(int(time.time()))
    out: list[ListingRecord] = []
    for i in range(1, count + 1):
        agency = f"Agency {i}"
        if args.simulate_blocked_agency and i == 1:
            agency = "TestSpam Agency"
        out.append(
            ListingRecord(
                site=site,
                search_url=search_url,
                ad_id=f"{site[:3].upper()}-{run_tag}-{i:04d}",
                url=f"https://www.{site}.it/mock/{run_tag}/{i}",
                title=f"Mock annuncio {site} #{i} [{run_tag}]",
                price=f"{500 + i * 10} EUR/mese",
                location="Torino",
                agency=agency,
                payload={"source": "test-pipeline", "idx": i, "run_tag": run_tag},
            )
        )
    if args.simulate_duplicate and out:
        out.append(out[0])
    return out


def _ensure_channels_for_mode(config: AppConfig, notify_mode: str) -> AppConfig:
    data = config.model_dump()
    changed = False
    if notify_mode in {"email", "both"} and not data["email"]["enabled"]:
        data["email"]["enabled"] = True
        changed = True
    if notify_mode in {"telegram", "both"} and not data["telegram"]["enabled"]:
        data["telegram"]["enabled"] = True
        changed = True
    if changed:
        return AppConfig.model_validate(data)
    return config


def _build_notifiers(
    *,
    config: AppConfig,
    profiles_path: Path,
    notify_mode: str,
    send_real_notifications: bool,
    logger,
) -> NotifierBootstrapState:
    if not send_real_notifications:
        logger.info("Notifier bootstrap skipped. dry_run=True")
        return NotifierBootstrapState()

    email_requested = notify_mode in {"email", "both"} or (notify_mode == "config" and config.email.enabled)
    telegram_requested = notify_mode in {"telegram", "both"} or (notify_mode == "config" and config.telegram.enabled)
    email_notifier = None
    telegram_notifier = None
    email_degraded_reason = ""
    telegram_degraded_reason = ""

    logger.info(
        "Notifier bootstrap start. email_requested=%s telegram_requested=%s",
        email_requested,
        telegram_requested,
    )

    if email_requested:
        try:
            email_config = config
            if not config.email.enabled:
                data = config.model_dump()
                data["email"]["enabled"] = True
                email_config = AppConfig.model_validate(data)
            prepared = prepare_email_configuration(email_config, profiles_path)
            email_notifier = EmailNotifier.from_config(prepared.resolved_config)
            logger.info(
                "Notifier bootstrap ready. channel=email provider=%s sender_mode=%s",
                prepared.resolved_config.provider,
                email_config.email.sender_mode,
            )
        except Exception as exc:
            email_degraded_reason = _flatten_error_text(exc)
            logger.warning(
                "Notifier bootstrap degraded. channel=email reason=%s continue_without_channel=True",
                email_degraded_reason,
            )

    if telegram_requested:
        try:
            telegram_notifier = TelegramNotifier(
                token=config.telegram.bot_token,
                chat_id=config.telegram.chat_id,
            )
            logger.info(
                "Notifier bootstrap ready. channel=telegram target_type=%s",
                config.telegram.target_type,
            )
        except Exception as exc:
            telegram_degraded_reason = _flatten_error_text(exc)
            logger.warning(
                "Notifier bootstrap degraded. channel=telegram reason=%s continue_without_channel=True",
                telegram_degraded_reason,
            )

    if (email_requested or telegram_requested) and email_notifier is None and telegram_notifier is None:
        logger.warning("All requested notification channels unavailable. pipeline_continues=True")

    return NotifierBootstrapState(
        email_notifier=email_notifier,
        telegram_notifier=telegram_notifier,
        email_requested=email_requested,
        telegram_requested=telegram_requested,
        email_degraded_reason=email_degraded_reason,
        telegram_degraded_reason=telegram_degraded_reason,
    )


def _log_pipeline_summary(result, send_real_notifications: bool, logger, prefix: str) -> None:
    logger.info(
        "%s processed=%s new=%s dup=%s blocked=%s private_only_skipped=%s private_only_unknown=%s email_items=%s email_messages=%s email_failures=%s "
        "telegram_sent=%s telegram_failures=%s dry_run=%s",
        prefix,
        result.processed,
        result.inserted_new,
        result.skipped_duplicate,
        result.skipped_blocked_agency,
        result.skipped_private_only,
        result.private_only_allowed_unknown,
        result.email_items_batched,
        result.notified_email,
        result.email_failures,
        result.notified_telegram,
        result.telegram_failures,
        not send_real_notifications,
    )
    if result.email_degraded:
        logger.warning(
            "%s channel degraded. channel=email reason=%s",
            prefix,
            result.email_degraded_reason or "email notifier unavailable",
        )
    if result.telegram_degraded:
        logger.warning(
            "%s channel degraded. channel=telegram reason=%s",
            prefix,
            result.telegram_degraded_reason or "telegram notifier unavailable",
        )
    if result.email_failures or result.telegram_failures:
        logger.warning(
            "%s notification failures detected. email_failures=%s telegram_failures=%s pipeline_continued=True",
            prefix,
            result.email_failures,
            result.telegram_failures,
        )


def _build_live_service_policy(config: AppConfig, args: argparse.Namespace) -> LiveServicePolicy:
    cadence_minutes = int(config.runtime.cycle_minutes)
    if cadence_minutes < 5:
        raise ConfigError("cycle_minutes cannot be lower than 5.")

    max_cycle_minutes = int(args.cycle_max_minutes or 0) or 10
    if max_cycle_minutes < cadence_minutes:
        raise ConfigError("cycle_max_minutes cannot be lower than cycle_minutes.")

    max_cycles = int(args.max_cycles or 0)
    if max_cycles < 0:
        raise ConfigError("max_cycles cannot be negative.")

    return LiveServicePolicy(
        cadence_sec=cadence_minutes * 60,
        max_cycle_sec=max_cycle_minutes * 60,
        max_cycles=max_cycles or None,
        restart_on_failure=bool(config.runtime.auto_restart_on_failure),
    )


def _count_missed_cycle_slots(*, cycle_started_monotonic: float, cycle_finished_monotonic: float, cadence_sec: int) -> int:
    next_slot_monotonic = cycle_started_monotonic + cadence_sec
    if cycle_finished_monotonic <= next_slot_monotonic:
        return 0
    return int((cycle_finished_monotonic - next_slot_monotonic) // cadence_sec) + 1


def _mark_live_service_assist_required(service_state: LiveServiceState, reason: str) -> None:
    service_state.assist_required = True
    service_state.assist_reason = service_state.assist_reason or reason
    service_state.current_state = "assist_required"


def _advance_live_service_state(
    *,
    service_state: LiveServiceState,
    cycle_failed: bool,
    cycle_overrun: bool,
    missed_slots: int,
    run_state: str = "",
    run_assist_required: bool = False,
    run_assist_reason: str = "",
    run_stop_requested: bool = False,
) -> tuple[str, str]:
    previous_state = service_state.current_state
    if service_state.assist_required:
        return (previous_state, service_state.current_state)

    run_degraded = run_state in {"challenge_seen", "degraded", "cooldown", "blocked"} or run_stop_requested
    service_state.consecutive_failures = service_state.consecutive_failures + 1 if cycle_failed else 0
    service_state.consecutive_overruns = service_state.consecutive_overruns + 1 if cycle_overrun else 0
    service_state.consecutive_backlog_cycles = service_state.consecutive_backlog_cycles + 1 if missed_slots > 0 else 0
    service_state.consecutive_run_degraded_cycles = (
        service_state.consecutive_run_degraded_cycles + 1 if run_degraded else 0
    )

    if run_assist_required or run_state == "assist_required":
        _mark_live_service_assist_required(service_state, run_assist_reason or "run_assist_required")
    elif service_state.consecutive_failures >= 2:
        _mark_live_service_assist_required(service_state, "repeated_cycle_failures")
    elif service_state.consecutive_overruns >= 2:
        _mark_live_service_assist_required(service_state, "repeated_cycle_overruns")
    elif cycle_failed or cycle_overrun or missed_slots > 0 or run_degraded:
        service_state.current_state = "degraded"
    else:
        service_state.current_state = "stable"

    return (previous_state, service_state.current_state)


def _log_live_service_state(*, logger, previous_state: str, service_state: LiveServiceState) -> None:
    if previous_state == service_state.current_state and not service_state.assist_required:
        return
    logger.warning(
        "Live service state. state=%s previous_state=%s consecutive_failures=%s consecutive_overruns=%s consecutive_backlog_cycles=%s consecutive_run_degraded_cycles=%s assist_required=%s assist_reason=%s",
        service_state.current_state,
        previous_state or "none",
        service_state.consecutive_failures,
        service_state.consecutive_overruns,
        service_state.consecutive_backlog_cycles,
        service_state.consecutive_run_degraded_cycles,
        service_state.assist_required,
        service_state.assist_reason or "none",
    )


def _decide_runtime_disposition(
    *,
    cycle_failed: bool,
    cycle_report,
    service_state: LiveServiceState,
) -> RuntimeDispositionDecision:
    if cycle_report is not None and bool(getattr(cycle_report, "assist_required", False)):
        return RuntimeDispositionDecision(
            action="stop_service",
            site=str(getattr(cycle_report, "run_state_site", "") or ""),
            reason=str(getattr(cycle_report, "assist_reason", "") or "run_assist_required"),
        )

    if cycle_failed:
        return RuntimeDispositionDecision(action="recycle_runtime", reason="cycle_failure")

    run_state = str(getattr(cycle_report, "run_state", "") or "")
    run_state_site = str(getattr(cycle_report, "run_state_site", "") or "")
    site_outcome_tiers = dict(getattr(cycle_report, "site_outcome_tiers", {}) or {})
    affected_sites = sorted(site for site, tier in site_outcome_tiers.items() if tier in {"degraded", "cooling", "blocked"})
    if run_state in {"cooldown", "blocked"} and run_state_site:
        return RuntimeDispositionDecision(action="recycle_site_slot", site=run_state_site, reason=run_state)

    if len(affected_sites) == 1:
        affected_site = affected_sites[0]
        affected_tier = str(site_outcome_tiers.get(affected_site, "") or "")
        if affected_tier in {"cooling", "blocked"}:
            return RuntimeDispositionDecision(
                action="recycle_site_slot",
                site=affected_site,
                reason=f"site_{affected_tier}",
            )

    if len(affected_sites) > 1:
        return RuntimeDispositionDecision(action="recycle_runtime", reason="multi_site_degraded")

    if service_state.consecutive_run_degraded_cycles >= 2 and run_state_site:
        return RuntimeDispositionDecision(
            action="recycle_site_slot",
            site=run_state_site,
            reason="persistent_run_degraded",
        )

    return RuntimeDispositionDecision()


def _run_test_pipeline(config_path: Path, profiles_path: Path, args: argparse.Namespace, logger) -> None:
    config = load_or_create_config(config_path)
    config, changed = _apply_config_overrides(config, args)
    if args.save_overrides and changed:
        save_config(config, config_path)
        logger.info("Saved config overrides: %s", ", ".join(sorted(set(changed))))

    db_path = _resolve_db_from_config(config_path, config.storage.db_path) if not args.db else resolve_db_path(args.db)
    db = Database(db_path)
    db.init_schema()
    if args.simulate_blocked_agency:
        db.set_blocked_agency_patterns([args.blocked_pattern])
        logger.info("Applied temporary blocked agency pattern: %s", args.blocked_pattern)

    listings = _build_mock_listings(config, args)
    notify_mode = _parse_notify_mode(args.notify_mode)
    logger.info(
        "Starting pipeline test. listings=%s notify_mode=%s send_real_notifications=%s",
        len(listings),
        notify_mode,
        bool(args.send_real_notifications),
    )

    notifier_state = _build_notifiers(
        config=config,
        profiles_path=profiles_path,
        notify_mode=notify_mode,
        send_real_notifications=bool(args.send_real_notifications),
        logger=logger,
    )

    result = process_listings(
        config=config,
        db=db,
        listings=listings,
        logger=logger,
        options=PipelineRunOptions(
            notify_mode=notify_mode, send_real_notifications=bool(args.send_real_notifications)
        ),
        email_notifier=notifier_state.email_notifier,
        telegram_notifier=notifier_state.telegram_notifier,
        email_degraded_reason=notifier_state.email_degraded_reason,
        telegram_degraded_reason=notifier_state.telegram_degraded_reason,
    )
    _log_pipeline_summary(
        result=result,
        send_real_notifications=bool(args.send_real_notifications),
        logger=logger,
        prefix="Pipeline test completed.",
    )


def _run_fetch_live_once(
    config_path: Path,
    profiles_path: Path,
    args: argparse.Namespace,
    logger,
    *,
    service_runtime: LiveFetchServiceRuntime | None = None,
    fetch_runner=None,
):
    config = load_or_create_config(config_path)
    config, changed = _apply_config_overrides(config, args)
    if args.save_overrides and changed:
        save_config(config, config_path)
        logger.info("Saved config overrides: %s", ", ".join(sorted(set(changed))))

    db_path = _resolve_db_from_config(config_path, config.storage.db_path) if not args.db else resolve_db_path(args.db)
    db = Database(db_path)
    db.init_schema()

    notify_mode = _parse_notify_mode(args.notify_mode)

    max_per_site = args.max_per_site if args.max_per_site > 0 else config.runtime.max_listings_per_page
    headless = not bool(args.headed)
    browser_channel = _parse_browser_channel(args.browser_channel)
    profile_dir = args.profile_dir.strip() or str((config_path.parent / "camoufox-profile").resolve())
    debug_dir: str | None = None
    if args.save_live_debug or args.live_debug_dir.strip():
        debug_dir = args.live_debug_dir.strip() or str((config_path.parent / "debug").resolve())
    site_guard_enabled = not bool(args.disable_site_guard)
    guard_state_file = args.guard_state_file.strip() or str((config_path.parent / "site_guard_state.json").resolve())
    guard_state_path = Path(guard_state_file).expanduser()
    guard_jitter_min = max(0, int(args.guard_jitter_min_sec))
    guard_jitter_max = max(guard_jitter_min, int(args.guard_jitter_max_sec))
    guard_base_cooldown_min = max(1, int(args.guard_base_cooldown_min))
    guard_max_cooldown_min = max(guard_base_cooldown_min, int(args.guard_max_cooldown_min))
    guard_ignore_cooldown = bool(args.guard_ignore_cooldown)
    if args.guard_reset_state:
        _reset_site_guard_state(guard_state_path, config.search_urls, logger)
    logger.info(
        "Starting live fetch run. one_shot=True headless=%s browser_channel=%s captcha_mode=%s guard_enabled=%s "
        "guard_ignore_cooldown=%s notify_mode=%s send_real_notifications=%s",
        headless,
        browser_channel,
        config.runtime.captcha_mode,
        site_guard_enabled,
        guard_ignore_cooldown,
        notify_mode,
        bool(args.send_real_notifications),
    )
    fetch_kwargs = {
        "search_urls": config.search_urls,
        "extraction": config.extraction,
        "max_per_site": max_per_site,
        "headless": headless,
        "wait_after_goto_ms": max(100, args.wait_after_goto_ms),
        "nav_timeout_ms": max(1000, args.nav_timeout_ms),
        "captcha_mode": config.runtime.captcha_mode,
        "captcha_wait_sec": max(10, args.captcha_wait_sec),
        "profile_dir": profile_dir,
        "debug_dir": debug_dir,
        "browser_channel": browser_channel,
        "site_guard_enabled": site_guard_enabled,
        "site_guard_state_path": str(guard_state_path),
        "guard_jitter_min_sec": guard_jitter_min,
        "guard_jitter_max_sec": guard_jitter_max,
        "guard_base_cooldown_sec": guard_base_cooldown_min * 60,
        "guard_max_cooldown_sec": guard_max_cooldown_min * 60,
        "guard_ignore_cooldown": guard_ignore_cooldown,
        "artifact_retention_days": config.storage.retention_days,
        "listing_cache_db_path": str(db_path),
        "service_runtime": service_runtime,
        "logger": logger,
    }
    if fetch_runner is None:
        fetch_runner = lambda kwargs: asyncio.run(fetch_live_once(**kwargs))
    try:
        fetch_report = fetch_runner(fetch_kwargs)
    except Exception as exc:
        logger.error("Live fetch stage failed. module=scraping error=%s", _flatten_error_text(exc))
        logger.warning("Live fetch run stopped cleanly before pipeline. one_shot=True")
        raise RuntimeJobError("Live fetch failed.") from exc

    listings = fetch_report.listings
    logger.info("Live fetch stage completed. extracted=%s", len(listings))
    logger.info(
        "Live fetch cycle report. run_state=%s run_state_site=%s assist_required=%s assist_reason=%s stop_requested=%s stop_reason=%s retry_count=%s detail_touch_count=%s identity_switch=%s site_outcome_tiers=%s",
        fetch_report.run_state,
        fetch_report.run_state_site or "none",
        fetch_report.assist_required,
        fetch_report.assist_reason or "none",
        fetch_report.stop_requested,
        fetch_report.stop_reason or "none",
        fetch_report.retry_count,
        fetch_report.detail_touch_count,
        fetch_report.identity_switch_count,
        dict(fetch_report.site_outcome_tiers),
    )
    if not listings:
        logger.info("Live fetch returned zero listings. pipeline will complete without notifications.")

    notifier_state = _build_notifiers(
        config=config,
        profiles_path=profiles_path,
        notify_mode=notify_mode,
        send_real_notifications=bool(args.send_real_notifications),
        logger=logger,
    )
    logger.info("Starting pipeline stage. one_shot=True listings=%s", len(listings))
    result = process_listings(
        config=config,
        db=db,
        listings=listings,
        logger=logger,
        options=PipelineRunOptions(
            notify_mode=notify_mode, send_real_notifications=bool(args.send_real_notifications)
        ),
        email_notifier=notifier_state.email_notifier,
        telegram_notifier=notifier_state.telegram_notifier,
        email_degraded_reason=notifier_state.email_degraded_reason,
        telegram_degraded_reason=notifier_state.telegram_degraded_reason,
    )
    _log_pipeline_summary(
        result=result,
        send_real_notifications=bool(args.send_real_notifications),
        logger=logger,
        prefix="Live pipeline completed.",
    )
    logger.info("Live fetch run finished. one_shot=True clean_shutdown=True")
    return fetch_report


def _run_fetch_live_service(
    config_path: Path,
    profiles_path: Path,
    args: argparse.Namespace,
    logger,
    *,
    monotonic_fn=time.monotonic,
    sleep_fn=time.sleep,
) -> None:
    config = load_or_create_config(config_path)
    config, changed = _apply_config_overrides(config, args)
    if args.save_overrides and changed:
        save_config(config, config_path)
        logger.info("Saved config overrides: %s", ", ".join(sorted(set(changed))))

    policy = _build_live_service_policy(config, args)
    run_args = _clone_args_without_save_overrides(args)
    stop_flag_path = _resolve_service_stop_flag_path(args.service_stop_flag)
    _clear_service_stop_flag(stop_flag_path)
    service_runtime = LiveFetchServiceRuntime()
    service_loop = asyncio.new_event_loop()
    cycle_number = 0
    overrun_count = 0
    failure_count = 0
    missed_cycle_count = 0
    service_state = LiveServiceState()
    next_cycle_monotonic = monotonic_fn()

    logger.info(
        "Starting live fetch service. cadence_sec=%s max_cycle_sec=%s max_cycles=%s auto_restart_on_failure=%s",
        policy.cadence_sec,
        policy.max_cycle_sec,
        policy.max_cycles or "continuous",
        policy.restart_on_failure,
    )

    try:
        asyncio.set_event_loop(service_loop)
        while True:
            if _is_service_stop_requested(stop_flag_path):
                logger.info(
                    "Live fetch service stop requested before cycle start. cycles=%s overrun_count=%s failure_count=%s missed_cycle_count=%s service_state=%s clean_shutdown=True",
                    cycle_number,
                    overrun_count,
                    failure_count,
                    missed_cycle_count,
                    service_state.current_state,
                )
                return

            if policy.max_cycles is not None and cycle_number >= policy.max_cycles:
                logger.info(
                    "Live fetch service finished. cycles=%s overrun_count=%s failure_count=%s missed_cycle_count=%s service_state=%s assist_required=%s assist_reason=%s clean_shutdown=True",
                    cycle_number,
                    overrun_count,
                    failure_count,
                    missed_cycle_count,
                    service_state.current_state,
                    service_state.assist_required,
                    service_state.assist_reason or "none",
                )
                return

            now_monotonic = monotonic_fn()
            sleep_sec = max(0.0, next_cycle_monotonic - now_monotonic)
            if sleep_sec > 0:
                logger.info(
                    "Waiting for next live cycle. cycle=%s sleep_sec=%.3f cadence_sec=%s",
                    cycle_number + 1,
                    sleep_sec,
                    policy.cadence_sec,
                )
                stop_requested = _sleep_until_next_cycle_or_stop(
                    sleep_sec=sleep_sec,
                    stop_flag_path=stop_flag_path,
                    monotonic_fn=monotonic_fn,
                    sleep_fn=sleep_fn,
                )
                if stop_requested:
                    logger.info(
                        "Live fetch service stopped cleanly while waiting for next cycle. cycles=%s overrun_count=%s failure_count=%s missed_cycle_count=%s service_state=%s clean_shutdown=True",
                        cycle_number,
                        overrun_count,
                        failure_count,
                        missed_cycle_count,
                        service_state.current_state,
                    )
                    return

            cycle_started_monotonic = monotonic_fn()
            cycle_number += 1
            cycle_delay_sec = max(0.0, cycle_started_monotonic - next_cycle_monotonic)
            logger.info(
                "Live fetch service cycle started. cycle=%s cycle_delay_sec=%.3f cadence_sec=%s pooled_sessions=%s",
                cycle_number,
                cycle_delay_sec,
                policy.cadence_sec,
                len(service_runtime.session_slots),
            )

            cycle_failed = False
            cycle_report = None
            try:
                cycle_report = _run_fetch_live_once(
                    config_path,
                    profiles_path,
                    run_args,
                    logger,
                    service_runtime=service_runtime,
                    fetch_runner=lambda kwargs: service_loop.run_until_complete(fetch_live_once(**kwargs)),
                )
            except RuntimeJobError:
                cycle_failed = True
                failure_count += 1
                logger.warning(
                    "Live fetch service cycle failed. cycle=%s failure_count=%s auto_restart_on_failure=%s pooled_sessions=%s",
                    cycle_number,
                    failure_count,
                    policy.restart_on_failure,
                    len(service_runtime.session_slots),
                )
                if not policy.restart_on_failure:
                    raise

            cycle_finished_monotonic = monotonic_fn()
            cycle_elapsed_sec = max(0.0, cycle_finished_monotonic - cycle_started_monotonic)
            cycle_overrun = cycle_elapsed_sec > policy.max_cycle_sec
            if cycle_overrun:
                overrun_count += 1
                logger.warning(
                    "Live fetch service cycle exceeded hard threshold. cycle=%s cycle_elapsed_sec=%.3f max_cycle_sec=%s overrun_count=%s",
                    cycle_number,
                    cycle_elapsed_sec,
                    policy.max_cycle_sec,
                    overrun_count,
                )

            missed_slots = _count_missed_cycle_slots(
                cycle_started_monotonic=cycle_started_monotonic,
                cycle_finished_monotonic=cycle_finished_monotonic,
                cadence_sec=policy.cadence_sec,
            )
            if missed_slots:
                missed_cycle_count += missed_slots
                logger.warning(
                    "Live fetch service cycle missed scheduled slots. cycle=%s missed_slots=%s missed_cycle_count=%s cycle_elapsed_sec=%.3f",
                    cycle_number,
                    missed_slots,
                    missed_cycle_count,
                    cycle_elapsed_sec,
                )

            logger.info(
                "Live fetch service cycle finished. cycle=%s cycle_elapsed_sec=%.3f cycle_failed=%s cycle_overrun=%s missed_slots=%s pooled_sessions=%s",
                cycle_number,
                cycle_elapsed_sec,
                cycle_failed,
                cycle_overrun,
                missed_slots,
                len(service_runtime.session_slots),
            )
            previous_state, current_state = _advance_live_service_state(
                service_state=service_state,
                cycle_failed=cycle_failed,
                cycle_overrun=cycle_overrun,
                missed_slots=missed_slots,
                run_state=getattr(cycle_report, "run_state", ""),
                run_assist_required=bool(getattr(cycle_report, "assist_required", False)),
                run_assist_reason=str(getattr(cycle_report, "assist_reason", "") or ""),
                run_stop_requested=bool(getattr(cycle_report, "stop_requested", False)),
            )
            _log_live_service_state(logger=logger, previous_state=previous_state, service_state=service_state)
            logger.info(
                "Live fetch service cycle state. cycle=%s service_state=%s assist_required=%s assist_reason=%s pooled_sessions=%s run_state=%s run_assist_required=%s run_stop_requested=%s",
                cycle_number,
                current_state,
                service_state.assist_required,
                service_state.assist_reason or "none",
                len(service_runtime.session_slots),
                getattr(cycle_report, "run_state", "") or "none",
                bool(getattr(cycle_report, "assist_required", False)),
                bool(getattr(cycle_report, "stop_requested", False)),
            )
            slot_summary = service_runtime_site_slot_snapshot(
                service_runtime,
                now_monotonic=cycle_finished_monotonic,
            )
            if slot_summary:
                logger.info(
                    "Live fetch service pooled slot summary. cycle=%s slots=%s",
                    cycle_number,
                    slot_summary,
                )
            disposition = _decide_runtime_disposition(
                cycle_failed=cycle_failed,
                cycle_report=cycle_report,
                service_state=service_state,
            )
            if disposition.action == "keep":
                disposition = _maybe_preemptive_site_slot_recycle(
                    slot_summary=slot_summary,
                    logger=logger,
                )
            logger.info(
                "Live fetch service runtime disposition. cycle=%s action=%s site=%s reason=%s pooled_sessions=%s",
                cycle_number,
                disposition.action,
                disposition.site or "none",
                disposition.reason or "none",
                len(service_runtime.session_slots),
            )
            if disposition.action == "recycle_site_slot":
                recycled_slots = service_loop.run_until_complete(
                    recycle_live_fetch_site_runtime(service_runtime, disposition.site)
                )
                logger.warning(
                    "Live fetch service recycled site slot. cycle=%s site=%s recycled_slots=%s reason=%s pooled_sessions=%s",
                    cycle_number,
                    disposition.site,
                    recycled_slots,
                    disposition.reason,
                    len(service_runtime.session_slots),
                )
            elif disposition.action == "recycle_runtime":
                service_loop.run_until_complete(close_live_fetch_service_runtime(service_runtime))
                service_runtime = LiveFetchServiceRuntime()
                logger.warning(
                    "Live fetch service recycled shared runtime. cycle=%s reason=%s pooled_sessions=%s",
                    cycle_number,
                    disposition.reason,
                    len(service_runtime.session_slots),
                )

            if service_state.assist_required or disposition.action == "stop_service":
                logger.warning(
                    "Live fetch service stopped for manual review. cycle=%s service_state=%s assist_reason=%s pooled_sessions=%s",
                    cycle_number,
                    service_state.current_state,
                    service_state.assist_reason,
                    len(service_runtime.session_slots),
                )
                raise RuntimeJobError("Live fetch service requires assistance.")
            if _is_service_stop_requested(stop_flag_path):
                logger.info(
                    "Live fetch service stopped cleanly after cycle. cycle=%s overrun_count=%s failure_count=%s missed_cycle_count=%s service_state=%s clean_shutdown=True",
                    cycle_number,
                    overrun_count,
                    failure_count,
                    missed_cycle_count,
                    service_state.current_state,
                )
                return
            next_cycle_monotonic += policy.cadence_sec
    finally:
        try:
            service_loop.run_until_complete(close_live_fetch_service_runtime(service_runtime))
        finally:
            asyncio.set_event_loop(None)
            service_loop.close()
        _clear_service_stop_flag(stop_flag_path)


def run(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = _build_parser()
    args = parser.parse_args(argv)

    ensure_runtime_dirs()
    publisher = LiveLogPublisher()
    logger = setup_logging(
        logger_name="affitto_v2",
        log_level=_resolve_log_level(args.log_level),
        log_file=APP_LOG_FILE,
        publisher=publisher,
        enable_file_logging=args.command != "gui",
    )

    config_path = resolve_config_path(args.config or None)
    profiles_path = _resolve_profiles_path(config_path, args.profiles)
    db_path = resolve_db_path(args.db or None)

    try:
        if args.command == "init-config":
            config = load_or_create_config(config_path)
            logger.info("Config ready at %s", config_path)
            logger.info(
                "Config summary: urls=%s telegram=%s email=%s sender_mode=%s cycle_minutes=%s",
                len(config.search_urls),
                config.telegram.enabled,
                config.email.enabled,
                config.email.sender_mode,
                config.runtime.cycle_minutes,
            )
            return 0

        if args.command == "validate-config":
            _validate_runtime_config(config_path)
            config = load_config(config_path)
            logger.info("Config is valid: %s", config_path)
            logger.info(
                "Validated channels: telegram=%s email=%s sender_mode=%s",
                config.telegram.enabled,
                config.email.enabled,
                config.email.sender_mode,
            )
            return 0

        if args.command == "init-email-profiles":
            _cmd_init_email_profiles(profiles_path, logger)
            return 0

        if args.command == "gui":
            from .gui_app import launch_gui

            launch_gui(config_path=config_path, profiles_path=profiles_path)
            return 0

        if args.command == "list-email-profiles":
            _cmd_list_email_profiles(profiles_path, logger)
            return 0

        if args.command == "upsert-email-profile":
            _cmd_upsert_email_profile(profiles_path, args, logger)
            return 0

        if args.command == "email-status":
            _run_email_status(config_path, profiles_path, args, logger)
            return 0

        if args.command == "test-email":
            _run_email_test(config_path, profiles_path, args, logger)
            return 0

        if args.command == "test-pipeline":
            _run_test_pipeline(config_path, profiles_path, args, logger)
            return 0

        if args.command == "fetch-live-once":
            _run_fetch_live_once(config_path, profiles_path, args, logger)
            return 0

        if args.command == "fetch-live-service":
            _run_fetch_live_service(config_path, profiles_path, args, logger)
            return 0

        db = Database(db_path)
        db.init_schema()

        if args.command == "init-db":
            logger.info("DB schema initialized at %s", db_path)
            return 0

        # doctor
        config = load_or_create_config(config_path)
        db_for_doctor = Database(_resolve_db_from_config(config_path, config.storage.db_path))
        db_for_doctor.init_schema()
        purged = db_for_doctor.purge_old_listings(config.storage.retention_days)
        logger.info("Retention cleanup finished. purged=%s", purged)
        logger.info("Listings count=%s", db_for_doctor.listing_count())
        logger.info("Doctor completed successfully.")
        return 0
    except ConfigError as exc:
        logger.error("Config error: %s", exc)
        return 2
    except RuntimeJobError as exc:
        logger.error("Runtime job error: %s", exc)
        return 5
    except EmailNotificationError as exc:
        logger.error("Email error: %s", exc)
        return 3
    except TelegramNotificationError as exc:
        logger.error("Telegram error: %s", exc)
        return 4
    except Exception as exc:
        logger.exception("Fatal error: %s", exc)
        return 1


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
