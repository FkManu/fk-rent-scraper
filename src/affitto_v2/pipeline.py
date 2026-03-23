from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from .db import Database, ListingRecord
from .models import AppConfig
from .notifiers import EmailNotifier, TelegramNotifier

NotifyMode = Literal["config", "none", "telegram", "email", "both"]


@dataclass(frozen=True)
class PipelineRunOptions:
    notify_mode: NotifyMode = "config"
    send_real_notifications: bool = False


@dataclass
class PipelineRunResult:
    processed: int = 0
    inserted_new: int = 0
    skipped_duplicate: int = 0
    skipped_blocked_agency: int = 0
    notified_email: int = 0
    email_items_batched: int = 0
    notified_telegram: int = 0
    email_failures: int = 0
    telegram_failures: int = 0
    email_degraded: bool = False
    telegram_degraded: bool = False
    email_degraded_reason: str = ""
    telegram_degraded_reason: str = ""


def _channel_flags(config: AppConfig, notify_mode: NotifyMode) -> tuple[bool, bool]:
    if notify_mode == "config":
        return config.telegram.enabled, config.email.enabled
    if notify_mode == "none":
        return False, False
    if notify_mode == "telegram":
        return True, False
    if notify_mode == "email":
        return False, True
    return True, True


def _needs_location_line(title: str, location: str) -> bool:
    t = " ".join((title or "").lower().split())
    l = " ".join((location or "").lower().split())
    if not l:
        return False
    return l not in t


def _format_email_digest_body(items: list[ListingRecord]) -> str:
    ts_local = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
    site_counts = Counter(item.site for item in items)
    lines = [f"Nuovi annunci rilevati: {len(items)}", f"Generato il: {ts_local}", ""]
    for idx, item in enumerate(items, start=1):
        lines.append(f"{idx}. {item.title or item.ad_id}")
        lines.append(f"   Sito: {item.site}")
        if item.price:
            lines.append(f"   Prezzo: {item.price}")
        if item.agency:
            lines.append(f"   Agenzia: {item.agency}")
        if _needs_location_line(item.title, item.location):
            lines.append(f"   Zona: {item.location}")
        lines.append(f"   URL: {item.url}")
        lines.append("")
    if site_counts:
        summary = ", ".join(f"{site}={count}" for site, count in sorted(site_counts.items()))
        lines.append(f"Riepilogo siti: {summary}")
        lines.append("")
    lines.append("Evento: riepilogo ciclo Affitto v2.")
    return "\n".join(lines)


def _format_telegram_text(item: ListingRecord) -> str:
    parts = []
    if item.title:
        parts.append(f"<b>{item.title}</b>")
    if item.price:
        parts.append(f"Prezzo: {item.price}")
    if item.agency:
        parts.append(f"Agenzia: {item.agency}")
    if item.location:
        parts.append(f"Zona: {item.location}")
    parts.append(item.url)
    return "\n".join(parts)


def process_listings(
    *,
    config: AppConfig,
    db: Database,
    listings: list[ListingRecord],
    logger,
    options: PipelineRunOptions,
    email_notifier: EmailNotifier | None = None,
    telegram_notifier: TelegramNotifier | None = None,
    email_degraded_reason: str = "",
    telegram_degraded_reason: str = "",
) -> PipelineRunResult:
    result = PipelineRunResult()
    telegram_on, email_on = _channel_flags(config, options.notify_mode)
    email_queue: list[tuple[ListingRecord, str]] = []
    logger.info(
        "Pipeline stage start. listings=%s notify_mode=%s send_real_notifications=%s",
        len(listings),
        options.notify_mode,
        options.send_real_notifications,
    )

    if options.send_real_notifications and email_on and email_notifier is None:
        result.email_degraded = True
        result.email_degraded_reason = email_degraded_reason.strip()
        logger.warning(
            "Pipeline continuing without email channel. reason=%s",
            result.email_degraded_reason or "email notifier unavailable",
        )
    if options.send_real_notifications and telegram_on and telegram_notifier is None:
        result.telegram_degraded = True
        result.telegram_degraded_reason = telegram_degraded_reason.strip()
        logger.warning(
            "Pipeline continuing without telegram channel. reason=%s",
            result.telegram_degraded_reason or "telegram notifier unavailable",
        )

    for item in listings:
        result.processed += 1
        blocked, pattern = db.agency_is_blocked(item.agency)
        if blocked:
            result.skipped_blocked_agency += 1
            logger.info("Skip blocked agency. agency=%s pattern=%s", item.agency, pattern)
            continue

        is_new = db.upsert_listing(item)
        if not is_new:
            result.skipped_duplicate += 1
            continue

        result.inserted_new += 1
        dedup_key = item.dedup_key()

        if email_on:
            email_queue.append((item, dedup_key))

        if telegram_on:
            if not options.send_real_notifications:
                logger.info("DRY-RUN telegram notify. chat=%s ad_id=%s", config.telegram.chat_id, item.ad_id)
            elif telegram_notifier is not None:
                try:
                    telegram_notifier.send_message(_format_telegram_text(item))
                except Exception as exc:
                    result.telegram_failures += 1
                    logger.error(
                        "Notification send failed. channel=telegram ad_id=%s error=%s pipeline_continues=True",
                        item.ad_id,
                        exc,
                    )
                else:
                    db.mark_notified(dedup_key, "telegram")
                    result.notified_telegram += 1

    if email_on and email_queue:
        result.email_items_batched = len(email_queue)
        if not options.send_real_notifications:
            ad_ids = [item.ad_id for item, _ in email_queue]
            logger.info(
                "DRY-RUN email digest. to=%s items=%s ad_ids=%s",
                config.email.to_address,
                len(email_queue),
                ",".join(ad_ids),
            )
        elif email_notifier is not None:
            digest_items = [item for item, _ in email_queue]
            subject = f"Nuovi annunci rilevati: {len(digest_items)}"
            try:
                email_notifier.send_message(
                    subject=subject,
                    body_text=_format_email_digest_body(digest_items),
                    to_address=config.email.to_address,
                )
            except Exception as exc:
                result.email_failures += 1
                logger.error(
                    "Notification send failed. channel=email items=%s to=%s error=%s pipeline_continues=True",
                    len(digest_items),
                    config.email.to_address,
                    exc,
                )
            else:
                for _, dedup_key in email_queue:
                    db.mark_notified(dedup_key, "email")
                result.notified_email += 1

    return result
