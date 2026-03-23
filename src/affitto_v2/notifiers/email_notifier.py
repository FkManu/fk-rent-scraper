from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from socket import timeout as SocketTimeout

from ..models import EmailConfig, SmtpSecurityMode


class EmailNotificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class EmailSendResult:
    recipient: str
    subject: str
    timestamp_utc: str


class EmailNotifier:
    def __init__(
        self,
        *,
        smtp_host: str,
        smtp_port: int,
        smtp_username: str,
        app_password: str,
        from_address: str,
        default_to_address: str,
        security_mode: SmtpSecurityMode = "starttls",
        timeout_seconds: float = 20.0,
    ) -> None:
        self.smtp_host = smtp_host.strip()
        self.smtp_port = int(smtp_port)
        self.smtp_username = smtp_username.strip()
        self.app_password = app_password.strip()
        self.from_address = from_address.strip()
        self.default_to_address = default_to_address.strip()
        self.security_mode = security_mode
        self.timeout_seconds = float(timeout_seconds)

    @classmethod
    def from_config(cls, config: EmailConfig, timeout_seconds: float = 20.0) -> "EmailNotifier":
        if not config.enabled:
            raise EmailNotificationError("Email notifications are disabled in config.")
        if config.sender_mode != "custom":
            raise EmailNotificationError("Email config must be resolved to sender_mode='custom' before send.")
        return cls(
            smtp_host=config.smtp_host,
            smtp_port=config.smtp_port,
            smtp_username=config.smtp_username,
            app_password=config.app_password,
            from_address=config.from_address,
            default_to_address=config.to_address,
            security_mode=config.security_mode,
            timeout_seconds=timeout_seconds,
        )

    def _connect(self) -> smtplib.SMTP:
        try:
            if self.security_mode == "ssl_tls":
                context = ssl.create_default_context()
                client = smtplib.SMTP_SSL(
                    self.smtp_host,
                    self.smtp_port,
                    timeout=self.timeout_seconds,
                    context=context,
                )
                client.ehlo()
            else:
                client = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=self.timeout_seconds)
                client.ehlo()
            if self.security_mode == "starttls":
                context = ssl.create_default_context()
                client.starttls(context=context)
                client.ehlo()
            client.login(self.smtp_username, self.app_password)
            return client
        except (smtplib.SMTPException, OSError, SocketTimeout) as exc:
            raise EmailNotificationError(f"SMTP connection/login failed: {exc}") from exc

    def check_connection(self) -> None:
        client = self._connect()
        try:
            client.noop()
        except smtplib.SMTPException as exc:
            raise EmailNotificationError(f"SMTP NOOP failed: {exc}") from exc
        finally:
            try:
                client.quit()
            except Exception:
                pass

    def send_message(
        self,
        *,
        subject: str,
        body_text: str,
        to_address: str | None = None,
    ) -> EmailSendResult:
        recipient = (to_address or self.default_to_address).strip()
        if not recipient:
            raise EmailNotificationError("Recipient address is missing.")
        msg = EmailMessage()
        msg["Subject"] = subject.strip() or "Affitto v2 notification"
        msg["From"] = self.from_address
        msg["To"] = recipient
        msg.set_content(body_text.strip() or "Affitto v2 notification")

        client = self._connect()
        try:
            client.send_message(msg)
        except (smtplib.SMTPException, OSError, SocketTimeout) as exc:
            raise EmailNotificationError(f"SMTP send failed: {exc}") from exc
        finally:
            try:
                client.quit()
            except Exception:
                pass

        return EmailSendResult(
            recipient=recipient,
            subject=msg["Subject"],
            timestamp_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    def send_test_message(self, to_address: str | None = None) -> EmailSendResult:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return self.send_message(
            subject="Affitto v2 - Test email",
            body_text=(
                "Questo e un test del canale email di Affitto v2.\n"
                f"Timestamp UTC: {now}\n"
                "Se stai leggendo questo messaggio, la configurazione SMTP e corretta."
            ),
            to_address=to_address,
        )
