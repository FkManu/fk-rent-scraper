from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from .models import AppConfig, build_default_config


class ConfigError(RuntimeError):
    pass


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def save_config(config: AppConfig, path: Path) -> None:
    payload = config.model_dump_json(indent=2)
    _atomic_write(path, payload + "\n")


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON config at {path}: {exc}") from exc
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"Config validation failed: {exc}") from exc


def load_or_create_config(path: Path) -> AppConfig:
    if path.exists():
        return load_config(path)
    config = build_default_config()
    save_config(config, path)
    return config
