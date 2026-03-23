from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from .config_store import ConfigError
from .models import EmailConfig, EmailSenderProfile
from .secret_crypto import SecretDecryptionError, protect_text, unprotect_text


class EmailProfilesError(ConfigError):
    pass


class EmailProfileMissingError(EmailProfilesError):
    pass


class EmailProfileUnreadableError(EmailProfilesError):
    pass


def default_profiles_path(config_path: Path) -> Path:
    return config_path.parent / "email_profiles.json"


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def _to_payload(profiles: dict[str, EmailSenderProfile]) -> dict:
    records = []
    for profile in profiles.values():
        item = profile.model_dump()
        item["smtp_username"] = protect_text(item.get("smtp_username", ""))
        item["app_password"] = protect_text(item.get("app_password", ""))
        records.append(item)
    return {
        "version": 1,
        "profiles": records,
    }


def load_profiles(path: Path, *, strict_secrets: bool = True) -> dict[str, EmailSenderProfile]:
    if not path.exists():
        raise EmailProfileMissingError(f"Email profiles file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EmailProfileUnreadableError(f"Invalid email profiles JSON at {path}: {exc}") from exc
    records = raw.get("profiles", [])
    out: dict[str, EmailSenderProfile] = {}
    try:
        for item in records:
            profile = EmailSenderProfile.model_validate(item)
            profile = profile.model_copy(
                update={
                    "smtp_username": unprotect_text(profile.smtp_username, strict=strict_secrets),
                    "app_password": unprotect_text(profile.app_password, strict=strict_secrets),
                }
            )
            out[profile.profile_id] = profile
    except SecretDecryptionError as exc:
        raise EmailProfileUnreadableError(f"Unable to decrypt email profile secret(s) from {path}: {exc}") from exc
    except ValidationError as exc:
        raise EmailProfileUnreadableError(f"Invalid email profile data: {exc}") from exc
    return out


def save_profiles(path: Path, profiles: dict[str, EmailSenderProfile]) -> None:
    payload = json.dumps(_to_payload(profiles), ensure_ascii=False, indent=2) + "\n"
    _atomic_write(path, payload)


def load_or_create_profiles(path: Path) -> dict[str, EmailSenderProfile]:
    if path.exists():
        return load_profiles(path, strict_secrets=False)
    template = EmailSenderProfile(
        profile_id="default_sender",
        provider="gmail",
        from_address="sender@example.com",
        smtp_username="sender@example.com",
        app_password="REPLACE_APP_PASSWORD",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        security_mode="starttls",
    )
    profiles = {template.profile_id: template}
    save_profiles(path, profiles)
    return profiles


def upsert_profile(path: Path, profile: EmailSenderProfile) -> None:
    profiles = load_or_create_profiles(path)
    profiles[profile.profile_id] = profile
    save_profiles(path, profiles)


def secure_profiles_file(path: Path) -> None:
    profiles = load_or_create_profiles(path)
    save_profiles(path, profiles)


def resolve_email_config(email_cfg: EmailConfig, profiles_path: Path) -> EmailConfig:
    if not email_cfg.enabled:
        raise ConfigError("Email notifications are disabled in config.")
    if email_cfg.sender_mode == "custom":
        return email_cfg
    profiles = load_profiles(profiles_path)
    profile = profiles.get(email_cfg.sender_profile_id)
    if profile is None:
        raise EmailProfileMissingError(
            f"Email sender profile '{email_cfg.sender_profile_id}' not found in {profiles_path}."
        )
    return EmailConfig(
        enabled=True,
        provider=profile.provider,
        sender_mode="custom",
        sender_profile_id=profile.profile_id,
        from_address=profile.from_address,
        to_address=email_cfg.to_address,
        smtp_username=profile.smtp_username,
        app_password=profile.app_password,
        smtp_host=profile.smtp_host,
        smtp_port=profile.smtp_port,
        security_mode=profile.security_mode,
    )
