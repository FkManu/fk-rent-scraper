from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .config_store import ConfigError
from .db import Database
from .email_profiles import EmailProfileMissingError, EmailProfileUnreadableError, resolve_email_config
from .models import AppConfig, EmailConfig

EmailState = Literal[
    "not_configured",
    "incomplete_placeholder",
    "profile_missing",
    "profile_unreadable",
    "configured_unverified",
    "connection_ok",
    "send_ok",
    "error",
]
EmailTestKind = Literal["connection", "send"]

_EMAIL_TEST_STATUS_KEY = "email:test_status:v1"
_PLACEHOLDER_EMAILS = {
    "sender@example.com",
    "destinatario@example.com",
    "recipient@example.com",
    "your.address@gmail.com",
    "your.sender@gmail.com",
    "no-reply@yourdomain.tld",
}
_PLACEHOLDER_EXACT = {
    "replace_app_password",
    "your_app_password",
    "smtp_password_or_api_key",
    "your_api_key",
    "your_password",
    "<recipient>",
    "<destinatario>",
}


class EmailConfigurationIssue(ConfigError):
    def __init__(self, state: EmailState, detail: str):
        super().__init__(detail)
        self.state = state
        self.detail = detail


@dataclass(frozen=True)
class PreparedEmailConfiguration:
    resolved_config: EmailConfig
    fingerprint: str


@dataclass(frozen=True)
class EmailTestRecord:
    version: int
    fingerprint: str
    kind: EmailTestKind
    outcome: Literal["ok", "error"]
    timestamp_utc: str
    message: str = ""


@dataclass(frozen=True)
class EmailConfigurationStatus:
    state: EmailState
    label: str
    detail: str = ""
    can_test: bool = False
    locally_valid: bool = False
    verified: bool = False
    provider: str = ""
    sender_mode: str = ""
    fingerprint: str = ""
    last_test_kind: str = ""
    last_test_at_utc: str = ""
    last_test_message: str = ""


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _looks_like_placeholder(field_name: str, value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return True
    if text in _PLACEHOLDER_EXACT:
        return True
    if text in _PLACEHOLDER_EMAILS:
        return True
    if text.startswith("replace_") or text.startswith("replace-"):
        return True
    if "your.address" in text or "your.sender" in text or "yourdomain.tld" in text:
        return True
    if field_name in {"from_address", "to_address"} and (
        text.endswith("@example.com") or text.endswith("@example.org") or text.endswith("@example.net")
    ):
        return True
    if field_name == "smtp_host" and ("your-provider" in text or text == "smtp.example.com"):
        return True
    return False


def _placeholder_fields(config: EmailConfig) -> list[str]:
    required_fields = {
        "from_address": config.from_address,
        "to_address": config.to_address,
        "smtp_username": config.smtp_username,
        "app_password": config.app_password,
        "smtp_host": config.smtp_host,
    }
    out: list[str] = []
    for field_name, raw_value in required_fields.items():
        if _looks_like_placeholder(field_name, raw_value):
            out.append(field_name)
    return out


def _fingerprint_email_config(config: EmailConfig) -> str:
    payload = {
        "provider": config.provider,
        "sender_mode": config.sender_mode,
        "sender_profile_id": config.sender_profile_id,
        "from_address": config.from_address,
        "to_address": config.to_address,
        "smtp_username": config.smtp_username,
        "smtp_host": config.smtp_host,
        "smtp_port": config.smtp_port,
        "security_mode": config.security_mode,
        "app_password_sha256": hashlib.sha256(config.app_password.encode("utf-8")).hexdigest(),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def prepare_email_configuration(config: AppConfig, profiles_path: Path) -> PreparedEmailConfiguration:
    if not config.email.enabled:
        raise EmailConfigurationIssue("not_configured", "Canale email disabilitato nella configurazione.")

    try:
        resolved = resolve_email_config(config.email, profiles_path)
    except EmailProfileMissingError as exc:
        raise EmailConfigurationIssue("profile_missing", str(exc)) from exc
    except EmailProfileUnreadableError as exc:
        raise EmailConfigurationIssue("profile_unreadable", str(exc)) from exc
    except ConfigError as exc:
        raise EmailConfigurationIssue("error", str(exc)) from exc

    placeholders = _placeholder_fields(resolved)
    if placeholders:
        raise EmailConfigurationIssue(
            "incomplete_placeholder",
            "Configurazione email incompleta o con placeholder nei campi: " + ", ".join(placeholders),
        )

    return PreparedEmailConfiguration(resolved_config=resolved, fingerprint=_fingerprint_email_config(resolved))


def load_last_email_test_record(db: Database) -> EmailTestRecord | None:
    raw = db.get_state(_EMAIL_TEST_STATUS_KEY, "")
    if not raw.strip():
        return None
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return None
        kind = str(payload.get("kind") or "").strip().lower()
        outcome = str(payload.get("outcome") or "").strip().lower()
        if kind not in {"connection", "send"}:
            return None
        if outcome not in {"ok", "error"}:
            return None
        return EmailTestRecord(
            version=int(payload.get("version") or 1),
            fingerprint=str(payload.get("fingerprint") or ""),
            kind=kind,
            outcome=outcome,
            timestamp_utc=str(payload.get("timestamp_utc") or ""),
            message=str(payload.get("message") or ""),
        )
    except Exception:
        return None


def save_email_test_record(
    db: Database,
    *,
    prepared: PreparedEmailConfiguration,
    kind: EmailTestKind,
    outcome: Literal["ok", "error"],
    message: str,
) -> None:
    record = EmailTestRecord(
        version=1,
        fingerprint=prepared.fingerprint,
        kind=kind,
        outcome=outcome,
        timestamp_utc=_now_utc_iso(),
        message=message.strip(),
    )
    db.set_state(_EMAIL_TEST_STATUS_KEY, json.dumps(asdict(record), ensure_ascii=False))


def invalidate_email_test_state(db: Database) -> None:
    db.set_state(_EMAIL_TEST_STATUS_KEY, "")


def get_email_configuration_status(
    config: AppConfig,
    *,
    profiles_path: Path,
    db: Database | None = None,
) -> EmailConfigurationStatus:
    if not config.email.enabled:
        return EmailConfigurationStatus(
            state="not_configured",
            label="Email non configurata",
            detail="Canale email disabilitato nella configurazione.",
            provider=config.email.provider,
            sender_mode=config.email.sender_mode,
        )

    try:
        prepared = prepare_email_configuration(config, profiles_path)
    except EmailConfigurationIssue as exc:
        labels = {
            "incomplete_placeholder": "Email incompleta / placeholder",
            "profile_missing": "Profilo mittente mancante",
            "profile_unreadable": "Profilo mittente non leggibile",
            "error": "Errore configurazione email",
            "not_configured": "Email non configurata",
        }
        return EmailConfigurationStatus(
            state=exc.state,
            label=labels.get(exc.state, "Errore configurazione email"),
            detail=exc.detail,
            provider=config.email.provider,
            sender_mode=config.email.sender_mode,
        )

    last_test = load_last_email_test_record(db) if db is not None else None
    if last_test is None:
        return EmailConfigurationStatus(
            state="configured_unverified",
            label="Email configurata ma non verificata",
            detail="Configurazione locale valida, ma nessun test eseguito su questa configurazione.",
            can_test=True,
            locally_valid=True,
            provider=prepared.resolved_config.provider,
            sender_mode=config.email.sender_mode,
            fingerprint=prepared.fingerprint,
        )

    if last_test.fingerprint != prepared.fingerprint:
        return EmailConfigurationStatus(
            state="configured_unverified",
            label="Email configurata ma non verificata",
            detail="La configurazione email e cambiata dopo l'ultimo test e deve essere verificata di nuovo.",
            can_test=True,
            locally_valid=True,
            provider=prepared.resolved_config.provider,
            sender_mode=config.email.sender_mode,
            fingerprint=prepared.fingerprint,
            last_test_kind=last_test.kind,
            last_test_at_utc=last_test.timestamp_utc,
            last_test_message=last_test.message,
        )

    if last_test.outcome == "error":
        return EmailConfigurationStatus(
            state="error",
            label="Errore configurazione/test email",
            detail=last_test.message or "Ultimo test email fallito.",
            can_test=True,
            locally_valid=True,
            provider=prepared.resolved_config.provider,
            sender_mode=config.email.sender_mode,
            fingerprint=prepared.fingerprint,
            last_test_kind=last_test.kind,
            last_test_at_utc=last_test.timestamp_utc,
            last_test_message=last_test.message,
        )

    if last_test.kind == "send":
        return EmailConfigurationStatus(
            state="send_ok",
            label="Test invio email OK",
            detail="Ultimo test invio riuscito sulla configurazione corrente.",
            can_test=True,
            locally_valid=True,
            verified=True,
            provider=prepared.resolved_config.provider,
            sender_mode=config.email.sender_mode,
            fingerprint=prepared.fingerprint,
            last_test_kind=last_test.kind,
            last_test_at_utc=last_test.timestamp_utc,
            last_test_message=last_test.message,
        )

    return EmailConfigurationStatus(
        state="connection_ok",
        label="Connessione SMTP OK",
        detail="Ultimo test connessione riuscito sulla configurazione corrente.",
        can_test=True,
        locally_valid=True,
        verified=True,
        provider=prepared.resolved_config.provider,
        sender_mode=config.email.sender_mode,
        fingerprint=prepared.fingerprint,
        last_test_kind=last_test.kind,
        last_test_at_utc=last_test.timestamp_utc,
        last_test_message=last_test.message,
    )
