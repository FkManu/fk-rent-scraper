from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "AffittoV2"
GUI_EXE_NAME = "affitto_gui.exe"
CLI_EXE_NAME = "affitto_cli.exe"


def is_frozen_bundle() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_source_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_bundle_root() -> Path:
    return Path(sys.executable).resolve().parent


def get_resource_root() -> Path:
    if is_frozen_bundle():
        return Path(getattr(sys, "_MEIPASS", get_bundle_root())).resolve()
    return get_source_root()


def get_app_root() -> Path:
    return get_bundle_root() if is_frozen_bundle() else get_source_root()


def _default_runtime_dir() -> Path:
    override = os.getenv("AFFITTO_V2_RUNTIME_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if is_frozen_bundle():
        base = os.getenv("LOCALAPPDATA", "").strip() or os.getenv("APPDATA", "").strip()
        if base:
            return Path(base).expanduser() / APP_NAME / "runtime"
        return Path.home() / APP_NAME / "runtime"
    return get_source_root() / "runtime"


APP_ROOT = get_app_root()
RESOURCE_ROOT = get_resource_root()
RUNTIME_DIR = _default_runtime_dir()
LOG_DIR = RUNTIME_DIR / "logs"
CONFIG_FILE = RUNTIME_DIR / "app_config.json"
DB_FILE = RUNTIME_DIR / "data.db"
APP_LOG_FILE = LOG_DIR / "app.log"


def ensure_runtime_dirs() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def resolve_config_path(override: str | None = None) -> Path:
    value = override or os.getenv("AFFITTO_V2_CONFIG")
    return Path(value).expanduser() if value else CONFIG_FILE


def resolve_db_path(override: str | None = None) -> Path:
    value = override or os.getenv("AFFITTO_V2_DB")
    return Path(value).expanduser() if value else DB_FILE
