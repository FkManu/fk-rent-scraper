from __future__ import annotations

import json
import logging
import os
import sys
import threading
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


def setup_logging(
    logger_name: str,
    log_level: str,
    log_file: Path,
    publisher: LiveLogPublisher | None = None,
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

    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        filename=log_file,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logger.level)
    file_handler.setFormatter(JsonFormatter())
    logger.addHandler(file_handler)

    if publisher is not None:
        live_handler = LiveStreamHandler(publisher, level=logger.level)
        logger.addHandler(live_handler)

    logger.propagate = False
    return logger
