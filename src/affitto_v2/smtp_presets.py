from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SmtpPreset:
    provider_id: str
    label: str
    smtp_host: str
    smtp_port: int
    security_mode: str
    help_text: str = ""


_SMTP_PRESETS: dict[str, SmtpPreset] = {
    "gmail": SmtpPreset(
        provider_id="gmail",
        label="Gmail",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        security_mode="starttls",
        help_text="Usa l'indirizzo completo come username e una app password quando richiesta.",
    ),
    "outlook": SmtpPreset(
        provider_id="outlook",
        label="Outlook / Microsoft 365",
        smtp_host="smtp.office365.com",
        smtp_port=587,
        security_mode="starttls",
        help_text=(
            "Richiede SMTP AUTH dove consentito. Su alcuni tenant/account Microsoft puo essere necessario OAuth."
        ),
    ),
    "brevo": SmtpPreset(
        provider_id="brevo",
        label="Brevo",
        smtp_host="smtp-relay.brevo.com",
        smtp_port=587,
        security_mode="starttls",
        help_text="Usa la SMTP key del provider; mittente o dominio devono essere verificati.",
    ),
    "mailjet": SmtpPreset(
        provider_id="mailjet",
        label="Mailjet",
        smtp_host="in-v3.mailjet.com",
        smtp_port=587,
        security_mode="starttls",
        help_text="Usa API key come username e secret key come password; sender/domain verificati.",
    ),
    "smtp2go": SmtpPreset(
        provider_id="smtp2go",
        label="SMTP2GO",
        smtp_host="mail.smtp2go.com",
        smtp_port=587,
        security_mode="starttls",
        help_text="Usa le credenziali SMTP del dashboard SMTP2GO.",
    ),
    "resend": SmtpPreset(
        provider_id="resend",
        label="Resend",
        smtp_host="smtp.resend.com",
        smtp_port=465,
        security_mode="ssl_tls",
        help_text="Usa username 'resend' e API key come password; dominio o sender verificati.",
    ),
    "custom": SmtpPreset(
        provider_id="custom",
        label="Custom SMTP",
        smtp_host="",
        smtp_port=587,
        security_mode="starttls",
        help_text="Configura host, porta e modalita di sicurezza manualmente.",
    ),
}


def get_smtp_preset(provider_id: str) -> SmtpPreset | None:
    return _SMTP_PRESETS.get((provider_id or "").strip().lower())


def list_smtp_presets() -> list[SmtpPreset]:
    return [preset for _, preset in sorted(_SMTP_PRESETS.items(), key=lambda item: item[0])]

