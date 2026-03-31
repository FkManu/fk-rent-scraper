from __future__ import annotations

from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from pydantic import BaseModel, Field, field_validator, model_validator

from .smtp_presets import get_smtp_preset

CaptchaMode = Literal["pause_and_notify", "skip_and_notify", "stop_and_notify"]
EmailProvider = Literal["gmail", "outlook", "brevo", "mailjet", "smtp2go", "resend", "custom"]
EmailSenderMode = Literal["custom", "profile"]
SmtpSecurityMode = Literal["starttls", "ssl_tls", "none"]

_ALLOWED_HOSTS = {
    "www.immobiliare.it",
    "immobiliare.it",
    "www.idealista.it",
    "idealista.it",
}


def _strip_tracking_params(url: str) -> str:
    split = urlsplit(url)
    query: list[tuple[str, str]] = []
    for key, value in parse_qsl(split.query, keep_blank_values=True):
        key_l = key.strip().lower()
        if key_l in {"gclid", "fbclid", "msclkid", "dtcookie"}:
            continue
        if key_l.startswith("utm_"):
            continue
        query.append((key, value))
    clean_query = urlencode(query, doseq=True)
    return urlunsplit((split.scheme, split.netloc, split.path, clean_query, split.fragment))


def _is_valid_email(value: str) -> bool:
    if "@" not in value:
        return False
    local, _, domain = value.partition("@")
    return bool(local.strip() and domain.strip() and "." in domain)


def _normalize_provider_id(value: object) -> str:
    return str(value or "gmail").strip().lower() or "gmail"


def _normalize_sender_mode(value: object) -> str:
    return str(value or "custom").strip().lower() or "custom"


def _normalize_security_mode(value: object) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "ssl": "ssl_tls",
        "ssl/tls": "ssl_tls",
        "tls_ssl": "ssl_tls",
        "plain": "none",
    }
    return aliases.get(text, text)


def _coerce_optional_int(value: object) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_bool(value: object) -> bool | None:
    if value in {None, ""}:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _resolve_security_mode(
    *,
    provider: str,
    raw_security_mode: object,
    legacy_use_starttls: object,
    smtp_port: object,
) -> str:
    normalized = _normalize_security_mode(raw_security_mode)
    if normalized:
        return normalized

    preset = get_smtp_preset(provider)
    port = _coerce_optional_int(smtp_port)
    legacy_flag = _coerce_optional_bool(legacy_use_starttls)
    if legacy_flag is True:
        return "starttls"
    if legacy_flag is False:
        if port == 465:
            return "ssl_tls"
        if provider == "custom":
            return "none"
        if preset is not None:
            return preset.security_mode
        return "starttls"

    if port == 465:
        return "ssl_tls"
    if preset is not None:
        return preset.security_mode
    return "starttls"


def _apply_provider_defaults_to_payload(raw: dict[str, object]) -> dict[str, object]:
    provider = _normalize_provider_id(raw.get("provider", "gmail"))
    sender_mode = _normalize_sender_mode(raw.get("sender_mode", "custom"))
    security_mode = _resolve_security_mode(
        provider=provider,
        raw_security_mode=raw.get("security_mode"),
        legacy_use_starttls=raw.get("use_starttls"),
        smtp_port=raw.get("smtp_port"),
    )

    data = dict(raw)
    data["provider"] = provider
    data["sender_mode"] = sender_mode
    data["security_mode"] = security_mode

    preset = get_smtp_preset(provider)
    host = str(data.get("smtp_host") or "").strip()
    port = _coerce_optional_int(data.get("smtp_port"))

    if provider != "custom" and preset is not None:
        if not host:
            data["smtp_host"] = preset.smtp_host
        if port is None or port <= 0:
            data["smtp_port"] = preset.smtp_port
    else:
        data["smtp_host"] = host
        if port is None or port <= 0:
            data["smtp_port"] = 465 if security_mode == "ssl_tls" else 587

    return data


class ExtractionFields(BaseModel):
    extract_price: bool = True
    extract_zone: bool = True
    extract_agency: bool = True
    private_only_ads: bool = False

    @model_validator(mode="after")
    def _apply_private_only_requirements(self) -> "ExtractionFields":
        # Private-only filtering depends on agency detection; keep the config coherent
        # even when it is edited manually outside the GUI.
        if self.private_only_ads:
            self.extract_agency = True
        return self


class TelegramConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""
    target_type: Literal["channel", "private", "group"] = "channel"

    @field_validator("bot_token", "chat_id", mode="before")
    @classmethod
    def _trim_fields(cls, value: object) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def _validate_when_enabled(self) -> "TelegramConfig":
        if self.enabled and (not self.bot_token or not self.chat_id):
            raise ValueError("Telegram is enabled but bot_token/chat_id are missing.")
        return self


class EmailConfig(BaseModel):
    enabled: bool = False
    provider: EmailProvider = "gmail"
    sender_mode: EmailSenderMode = "custom"
    sender_profile_id: str = "default_sender"
    from_address: str = ""
    to_address: str = ""
    smtp_username: str = ""
    app_password: str = ""
    smtp_host: str = ""
    smtp_port: int = 0
    security_mode: SmtpSecurityMode = "starttls"
    use_starttls: bool | None = Field(default=None, exclude=True, repr=False)

    @model_validator(mode="before")
    @classmethod
    def _normalize_payload(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return _apply_provider_defaults_to_payload(value)

    @field_validator(
        "sender_profile_id",
        "from_address",
        "to_address",
        "smtp_username",
        "app_password",
        "smtp_host",
        "security_mode",
        mode="before",
    )
    @classmethod
    def _trim_text(cls, value: object) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def _apply_provider_defaults(self) -> "EmailConfig":
        if self.sender_mode == "profile":
            # When profile mode is active, custom SMTP fields are not used and
            # must be cleared to avoid storing stale secrets in app_config.json.
            self.from_address = ""
            self.smtp_username = ""
            self.app_password = ""
            self.smtp_host = ""
            self.smtp_port = 0
            return self
        preset = get_smtp_preset(self.provider)
        if preset is not None and self.provider != "custom":
            self.smtp_host = self.smtp_host or preset.smtp_host
            self.smtp_port = self.smtp_port or preset.smtp_port
        else:
            self.smtp_host = self.smtp_host.strip()
            self.smtp_port = self.smtp_port or (465 if self.security_mode == "ssl_tls" else 587)
        if not self.smtp_username and self.from_address:
            self.smtp_username = self.from_address
        return self

    @model_validator(mode="after")
    def _validate_when_enabled(self) -> "EmailConfig":
        if not self.enabled:
            return self
        if self.sender_mode == "profile":
            if not self.sender_profile_id:
                raise ValueError("sender_profile_id is required when sender_mode='profile'.")
            if not self.to_address:
                raise ValueError("to_address is required when sender_mode='profile'.")
            if not _is_valid_email(self.to_address):
                raise ValueError("Invalid to_address format.")
            return self
        missing = []
        if not self.from_address:
            missing.append("from_address")
        if not self.to_address:
            missing.append("to_address")
        if not self.app_password:
            missing.append("app_password")
        if not self.smtp_host:
            missing.append("smtp_host")
        if not self.smtp_username:
            missing.append("smtp_username")
        if missing:
            raise ValueError(f"Email is enabled but required fields are missing: {', '.join(missing)}")
        if not _is_valid_email(self.from_address):
            raise ValueError("Invalid from_address format.")
        if not _is_valid_email(self.to_address):
            raise ValueError("Invalid to_address format.")
        if self.smtp_port <= 0:
            raise ValueError("smtp_port must be positive.")
        if self.security_mode == "none" and self.provider != "custom":
            raise ValueError("security_mode='none' is allowed only for provider='custom'.")
        return self


class RuntimeConfig(BaseModel):
    cycle_minutes: int = Field(default=5, ge=3, le=180)
    max_listings_per_page: int = Field(default=30, ge=5, le=100)
    captcha_mode: CaptchaMode = "skip_and_notify"
    auto_restart_on_failure: bool = True


class StorageConfig(BaseModel):
    db_path: str = "data.db"
    retention_days: int = Field(default=15, ge=1, le=365)


class EmailSenderProfile(BaseModel):
    profile_id: str
    provider: EmailProvider = "gmail"
    from_address: str
    smtp_username: str
    app_password: str
    smtp_host: str = ""
    smtp_port: int = 0
    security_mode: SmtpSecurityMode = "starttls"
    use_starttls: bool | None = Field(default=None, exclude=True, repr=False)

    @model_validator(mode="before")
    @classmethod
    def _normalize_payload(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return _apply_provider_defaults_to_payload(value)

    @field_validator(
        "profile_id",
        "from_address",
        "smtp_username",
        "app_password",
        "smtp_host",
        "security_mode",
        mode="before",
    )
    @classmethod
    def _trim_profile_fields(cls, value: object) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def _apply_profile_defaults(self) -> "EmailSenderProfile":
        preset = get_smtp_preset(self.provider)
        if preset is not None and self.provider != "custom":
            self.smtp_host = self.smtp_host or preset.smtp_host
            self.smtp_port = self.smtp_port or preset.smtp_port
        else:
            self.smtp_port = self.smtp_port or (465 if self.security_mode == "ssl_tls" else 587)
        return self

    @model_validator(mode="after")
    def _validate_profile(self) -> "EmailSenderProfile":
        if not self.profile_id:
            raise ValueError("profile_id is required.")
        if not _is_valid_email(self.from_address):
            raise ValueError("Invalid from_address format.")
        if not self.smtp_username:
            raise ValueError("smtp_username is required.")
        if not self.app_password:
            raise ValueError("app_password is required.")
        if not self.smtp_host:
            raise ValueError("smtp_host is required.")
        if self.smtp_port <= 0:
            raise ValueError("smtp_port must be positive.")
        if self.security_mode == "none" and self.provider != "custom":
            raise ValueError("security_mode='none' is allowed only for provider='custom'.")
        return self


class AppConfig(BaseModel):
    version: int = 1
    search_urls: list[str] = Field(default_factory=list)
    extraction: ExtractionFields = Field(default_factory=ExtractionFields)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)

    @field_validator("search_urls")
    @classmethod
    def _validate_urls(cls, values: list[str]) -> list[str]:
        if not values:
            raise ValueError("At least one search URL is required.")
        out: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = _strip_tracking_params(str(raw or "").strip())
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"Invalid URL format: {value}")
            host = (parsed.hostname or "").lower()
            if host not in _ALLOWED_HOSTS:
                raise ValueError(f"Unsupported host for URL: {value}")
            if value not in seen:
                out.append(value)
                seen.add(value)
        return out

    @model_validator(mode="after")
    def _validate_notification_choice(self) -> "AppConfig":
        if not self.telegram.enabled and not self.email.enabled:
            raise ValueError("At least one notification channel must be enabled.")
        return self


def build_default_config() -> AppConfig:
    from .paths import DB_FILE

    return AppConfig(
        search_urls=[
            "https://www.immobiliare.it/search-list/?idContratto=2&idCategoria=1",
        ],
        telegram=TelegramConfig(
            enabled=True,
            bot_token="REPLACE_TELEGRAM_BOT_TOKEN",
            chat_id="REPLACE_TELEGRAM_CHAT_ID",
            target_type="channel",
        ),
        email=EmailConfig(enabled=False, provider="gmail"),
        storage=StorageConfig(db_path=str(DB_FILE)),
    )
