from __future__ import annotations

from dataclasses import dataclass

import httpx


class TelegramNotificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class TelegramSendResult:
    chat_id: str
    message_id: int | None


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, timeout_seconds: float = 20.0) -> None:
        self.token = (token or "").strip()
        self.chat_id = (chat_id or "").strip()
        self.timeout_seconds = float(timeout_seconds)
        if not self.token or not self.chat_id:
            raise TelegramNotificationError("Telegram token/chat_id are required.")

    def send_message(self, text: str, disable_preview: bool = True, parse_mode: str = "HTML") -> TelegramSendResult:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": str(bool(disable_preview)).lower(),
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(url, data=payload)
        except httpx.RequestError as exc:
            raise TelegramNotificationError(f"Telegram network error: {exc}") from exc

        if response.status_code != 200:
            raise TelegramNotificationError(
                f"Telegram HTTP {response.status_code}: {response.text[:400]}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise TelegramNotificationError("Telegram returned non-JSON response.") from exc

        if not data.get("ok"):
            raise TelegramNotificationError(f"Telegram API error: {data}")
        result = data.get("result") or {}
        return TelegramSendResult(chat_id=self.chat_id, message_id=result.get("message_id"))
