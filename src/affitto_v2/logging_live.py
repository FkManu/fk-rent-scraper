from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class LiveLogEvent:
    ts: str
    level: str
    logger: str
    message: str
    module: str
    function: str
    line: int


class LiveLogPublisher:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[LiveLogEvent], None]] = []

    def subscribe(self, callback: Callable[[LiveLogEvent], None]) -> None:
        with self._lock:
            self._callbacks.append(callback)

    def unsubscribe(self, callback: Callable[[LiveLogEvent], None]) -> None:
        with self._lock:
            self._callbacks = [cb for cb in self._callbacks if cb is not callback]

    def publish(self, event: LiveLogEvent) -> None:
        with self._lock:
            callbacks = list(self._callbacks)
        for callback in callbacks:
            try:
                callback(event)
            except Exception:
                continue


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = {
            "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            event["exc"] = self.formatException(record.exc_info)
        return json.dumps(event, ensure_ascii=False)


class LiveStreamHandler(logging.Handler):
    def __init__(self, publisher: LiveLogPublisher, level: int = logging.INFO):
        super().__init__(level)
        self._publisher = publisher

    def emit(self, record: logging.LogRecord) -> None:
        ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        event = LiveLogEvent(
            ts=ts,
            level=record.levelname,
            logger=record.name,
            message=record.getMessage(),
            module=record.module,
            function=record.funcName,
            line=record.lineno,
        )
        self._publisher.publish(event)


_NULL_STREAM = open(os.devnull, "a", encoding="utf-8")


def _is_windows_lock_error(exc: OSError) -> bool:
    if isinstance(exc, PermissionError):
        return True
    return getattr(exc, "winerror", None) == 32


class SafeRotatingFileHandler(RotatingFileHandler):
    def __init__(
        self,
        *args,
        rollover_retry_count: int = 2,
        rollover_retry_delay_sec: float = 0.2,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._rollover_retry_count = max(0, int(rollover_retry_count))
        self._rollover_retry_delay_sec = max(0.0, float(rollover_retry_delay_sec))
        self._last_rollover_warning_monotonic = 0.0

    def doRollover(self) -> None:
        last_exc: OSError | None = None
        for attempt in range(self._rollover_retry_count + 1):
            try:
                super().doRollover()
                return
            except OSError as exc:
                if not _is_windows_lock_error(exc):
                    raise
                last_exc = exc
                if attempt < self._rollover_retry_count and self._rollover_retry_delay_sec > 0:
                    time.sleep(self._rollover_retry_delay_sec * (attempt + 1))
        self._recover_after_rollover_failure(last_exc)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self.shouldRollover(record):
                try:
                    self.doRollover()
                except OSError as exc:
                    self._recover_after_rollover_failure(exc)
            logging.FileHandler.emit(self, record)
        except Exception:
            self.handleError(record)

    def _recover_after_rollover_failure(self, exc: OSError | None) -> None:
        if self.stream:
            try:
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        self.stream = self._open()
        now = time.monotonic()
        if now - self._last_rollover_warning_monotonic >= 60:
            self._last_rollover_warning_monotonic = now
            try:
                sys.stderr.write(
                    "Affitto log rollover skipped because app.log is locked by another process. "
                    f"Continuing on current file. detail={exc}\n"
                )
                sys.stderr.flush()
            except Exception:
                pass


def setup_logging(
    logger_name: str,
    log_level: str,
    log_file: Path,
    publisher: LiveLogPublisher | None = None,
    enable_file_logging: bool = True,
) -> logging.Logger:
    logger = logging.getLogger(logger_name)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.handlers.clear()

    console_stream = sys.stderr if sys.stderr is not None else _NULL_STREAM
    text_stream = logging.StreamHandler(console_stream)
    text_stream.setLevel(logger.level)
    text_stream.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(text_stream)

    if enable_file_logging:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = SafeRotatingFileHandler(
            filename=log_file,
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
            delay=True,
        )
        file_handler.setLevel(logger.level)
        file_handler.setFormatter(JsonFormatter())
        logger.addHandler(file_handler)

    if publisher is not None:
        live_handler = LiveStreamHandler(publisher, level=logger.level)
        logger.addHandler(live_handler)

    logger.propagate = False
    return logger
