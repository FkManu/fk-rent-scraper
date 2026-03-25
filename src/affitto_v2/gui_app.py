from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from queue import Empty, Queue
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .config_store import ConfigError, load_or_create_config, save_config
from .db import Database
from .email_profiles import default_profiles_path, load_or_create_profiles, secure_profiles_file, upsert_profile
from .email_setup import get_email_configuration_status
from .models import AppConfig, EmailSenderProfile
from .paths import CLI_EXE_NAME, ensure_runtime_dirs, get_app_root, is_frozen_bundle, resolve_config_path
from .secret_crypto import is_encrypted
from .smtp_presets import get_smtp_preset

_LOG_LEVELS = ("ALL", "INFO", "WARNING", "ERROR")
_NOTIFY_MODES = ("telegram", "email", "both")
_EMAIL_PROVIDER_ORDER = ("gmail", "outlook", "brevo", "mailjet", "smtp2go", "resend", "custom")
_SMTP_SECURITY_LABELS = {
    "starttls": "STARTTLS",
    "ssl_tls": "SSL/TLS (implicito)",
    "none": "Nessuna sicurezza",
}
_SMTP_SECURITY_ORDER = ("starttls", "ssl_tls", "none")
_GUI_STATE_VERSION = 1
_LOG_LEVEL_RE = re.compile(r"\|\s*(DEBUG|INFO|WARNING|ERROR)\s*\|")
_SUPPORTED_URL_RE = re.compile(
    r"((?:https?://)?(?:www\.)?(?:idealista\.it|immobiliare\.it)[^\s\"'<>]+)",
    flags=re.IGNORECASE,
)


class GuiUserFacingError(ConfigError):
    def __init__(self, title: str, message: str):
        super().__init__(message)
        self.title = title


def _runtime_dir_from_config(config_path: Path) -> Path:
    return config_path.parent


def _default_gui_state_path(config_path: Path) -> Path:
    return _runtime_dir_from_config(config_path) / "gui_state.json"


def _default_guard_state_path(config_path: Path) -> Path:
    return _runtime_dir_from_config(config_path) / "site_guard_state.json"


def _app_root() -> Path:
    return get_app_root()


def _run_py_path() -> Path:
    return _app_root() / "run.py"


def _cli_executable_path() -> Path:
    return _app_root() / CLI_EXE_NAME


def _normalize_spaces(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _trim_text(value: str) -> str:
    return str(value or "").strip()


def _looks_like_email(value: str) -> bool:
    text = _trim_text(value)
    if "@" not in text:
        return False
    local, _, domain = text.partition("@")
    return bool(local and domain and "." in domain)


def _sanitize_supported_url(value: str) -> str:
    raw = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if not raw:
        return ""
    match = _SUPPORTED_URL_RE.search(raw)
    if not match:
        return ""
    token = match.group(1)
    token = token.strip().strip("[](){}<>\"',;")
    token = token.replace("&amp;", "&").replace(" ", "")
    if token.lower().startswith("https://http://"):
        token = token[len("https://") :]
    if token.lower().startswith("http://https://"):
        token = token[len("http://") :]
    if not token.lower().startswith(("http://", "https://")):
        token = "https://" + token

    # Remove noisy tracking params to keep app_config clean and stable.
    split = urlsplit(token)
    filtered_query: list[tuple[str, str]] = []
    for key, value_q in parse_qsl(split.query, keep_blank_values=True):
        key_l = key.strip().lower()
        if key_l in {"gclid", "fbclid", "msclkid", "dtcookie"}:
            continue
        if key_l.startswith("utm_"):
            continue
        filtered_query.append((key, value_q))
    query = urlencode(filtered_query, doseq=True)
    return urlunsplit((split.scheme, split.netloc, split.path, query, split.fragment))


def _agency_name_to_regex(value: str) -> str:
    text = _normalize_spaces(value)
    if not text:
        return ""
    escaped = re.escape(text).replace(r"\ ", r"\s+")
    return rf"\b{escaped}\b"


def _parse_log_level(line: str) -> str:
    match = _LOG_LEVEL_RE.search(line or "")
    if match:
        return match.group(1)
    return "INFO"


def _resolve_db_from_config(config_path: Path, db_value: str) -> Path:
    candidate = Path(db_value).expanduser()
    if candidate.is_absolute():
        return candidate
    if candidate.parts and candidate.parts[0].lower() == "runtime":
        return (config_path.parent.parent / candidate).resolve()
    return (config_path.parent / candidate).resolve()


def _windows_startup_script_path() -> Path | None:
    appdata = os.getenv("APPDATA", "").strip()
    if not appdata:
        return None
    startup_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return startup_dir / "AffittoV2_GUI.cmd"


def _pythonw_or_python() -> Path:
    exe = Path(sys.executable).resolve()
    pyw = exe.with_name("pythonw.exe")
    return pyw if pyw.exists() else exe


def _load_gui_state(path: Path) -> dict:
    default = {
        "version": _GUI_STATE_VERSION,
        "notify_mode": "both",
        "blocked_agency_names": [],
        "log_filter": "INFO",
        "autostart_enabled": False,
    }
    try:
        if not path.exists():
            return default
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return default
        mode = str(raw.get("notify_mode") or "both").strip().lower()
        if mode not in _NOTIFY_MODES:
            mode = "both"
        names_raw = raw.get("blocked_agency_names", [])
        names = []
        if isinstance(names_raw, list):
            names = [_normalize_spaces(str(x)) for x in names_raw if _normalize_spaces(str(x))]
        log_filter = str(raw.get("log_filter") or "INFO").strip().upper()
        if log_filter not in _LOG_LEVELS:
            log_filter = "INFO"
        return {
            "version": _GUI_STATE_VERSION,
            "notify_mode": mode,
            "blocked_agency_names": names,
            "log_filter": log_filter,
            "autostart_enabled": bool(raw.get("autostart_enabled", False)),
        }
    except Exception:
        return default


def _save_gui_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def _site_guard_key(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "idealista.it" in host:
        return "idealista"
    if "immobiliare.it" in host:
        return "immobiliare"
    return host or "unknown"


def _reset_guard_state(path: Path, search_urls: list[str]) -> None:
    sites: dict[str, dict[str, object]] = {}
    for url in search_urls:
        key = _site_guard_key(url)
        if key not in sites:
            sites[key] = {
                "strikes": 0,
                "cooldown_until_utc": "",
                "last_reason": "",
                "last_outcome_tier": "",
                "last_outcome_code": "",
                "last_outcome_detail": "",
                "last_attempt_utc": "",
                "last_success_utc": "",
                "last_recovery_utc": "",
                "last_valid_channel": "",
                "last_attempt_channel": "",
                "last_block_family": "",
                "last_block_code": "",
                "warmup_active": True,
                "warmup_started_utc": "",
                "warmup_completed_utc": "",
                "warmup_failures": 0,
                "warmup_last_failures": 0,
                "consecutive_successes": 0,
                "consecutive_failures": 0,
                "consecutive_suspect": 0,
                "consecutive_blocks": 0,
                "last_cards_count": 0,
                "last_quality": "",
                "last_fallback_used": False,
                "last_missing_title_pct": 0,
                "last_missing_price_pct": 0,
                "last_missing_location_pct": 0,
                "last_missing_agency_pct": 0,
                "probe_after_utc": "",
                "probe_attempts": 0,
            }
    payload = {"version": 5, "last_channel": "chromium", "sites": sites}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class AffittoGuiApp:
    def __init__(self, root: tk.Tk, config_path: Path, profiles_path: Path):
        self.root = root
        self.config_path = config_path
        self.profiles_path = profiles_path
        self.gui_state_path = _default_gui_state_path(config_path)
        self.guard_state_path = _default_guard_state_path(config_path)
        self.app_root = _app_root()
        self.bundle_mode = is_frozen_bundle()
        self.cli_exe = _cli_executable_path()
        self.run_py = _run_py_path()
        self.gui_state = _load_gui_state(self.gui_state_path)
        self._log_records: deque[tuple[str, str]] = deque(maxlen=4000)
        self._queue: Queue[tuple[str, object]] = Queue()
        self._worker: threading.Thread | None = None
        self._email_test_worker: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._periodic_mode = False
        self._process_lock = threading.Lock()
        self._active_proc: subprocess.Popen[str] | None = None
        self._email_loaded_snapshot: dict[str, str] = {}
        self._email_status = None

        ensure_runtime_dirs()
        self.config = load_or_create_config(self.config_path)
        load_or_create_profiles(self.profiles_path)
        secure_profiles_file(self.profiles_path)

        self._email_provider_labels: dict[str, str] = {}
        self._email_provider_by_label: dict[str, str] = {}
        for provider_id in _EMAIL_PROVIDER_ORDER:
            preset = get_smtp_preset(provider_id)
            label = preset.label if preset is not None else provider_id
            self._email_provider_labels[provider_id] = label
            self._email_provider_by_label[label] = provider_id

        self.notify_mode_var = tk.StringVar(value=self._infer_notify_mode())
        self.idealista_url_var = tk.StringVar(value=self._find_url("idealista.it"))
        self.immobiliare_url_var = tk.StringVar(value=self._find_url("immobiliare.it"))
        self.cycle_minutes_var = tk.IntVar(value=self.config.runtime.cycle_minutes)
        self.max_per_site_var = tk.IntVar(value=min(50, self.config.runtime.max_listings_per_page))
        self.retention_days_var = tk.IntVar(value=self.config.storage.retention_days)
        self.telegram_token_var = tk.StringVar(value=self.config.telegram.bot_token)
        self.telegram_chat_id_var = tk.StringVar(value=self.config.telegram.chat_id)
        self.email_provider_var = tk.StringVar(value="")
        self.email_route_label_var = tk.StringVar(value="")
        self.email_from_var = tk.StringVar(value="")
        self.email_username_var = tk.StringVar(value="")
        self.email_password_var = tk.StringVar(value="")
        self.email_host_var = tk.StringVar(value="")
        self.email_port_var = tk.StringVar(value="")
        self.email_security_mode_var = tk.StringVar(value="")
        self.email_to_var = tk.StringVar(value=self.config.email.to_address)
        self.email_provider_help_var = tk.StringVar(value="")
        self.email_status_label_var = tk.StringVar(value="Stato email: in caricamento...")
        self.email_status_detail_var = tk.StringVar(value="")
        self.email_setup_note_var = tk.StringVar(value="")
        self.notify_mode_note_var = tk.StringVar(value="")
        self.telegram_section_note_var = tk.StringVar(value="")
        self.extract_price_var = tk.BooleanVar(value=self.config.extraction.extract_price)
        self.extract_zone_var = tk.BooleanVar(value=self.config.extraction.extract_zone)
        self.extract_agency_var = tk.BooleanVar(value=self.config.extraction.extract_agency)
        self.private_only_ads_var = tk.BooleanVar(value=self.config.extraction.private_only_ads)
        self.private_only_note_var = tk.StringVar(value="")
        self.blocked_name_var = tk.StringVar(value="")
        self.log_filter_var = tk.StringVar(value=self.gui_state.get("log_filter", "INFO"))
        self.status_var = tk.StringVar(value="Pronto.")
        self.autostart_var = tk.BooleanVar(value=self._is_autostart_enabled())
        self._blocked_names: list[str] = list(self.gui_state.get("blocked_agency_names", []))

        self._build_ui()
        self.private_only_ads_var.trace_add("write", self._on_private_only_changed)
        self._bind_email_form_traces()
        self._refresh_private_only_controls()
        self._load_blocked_names()
        self._load_email_form()
        self._refresh_email_status()
        self.root.after(120, self._drain_queue)

    def _infer_notify_mode(self) -> str:
        saved = str(self.gui_state.get("notify_mode", "")).strip().lower()
        if saved in _NOTIFY_MODES:
            return saved
        if self.config.telegram.enabled and self.config.email.enabled:
            return "both"
        if self.config.telegram.enabled:
            return "telegram"
        if self.config.email.enabled:
            return "email"
        return "both"

    def _find_url(self, host_key: str) -> str:
        for url in self.config.search_urls:
            host = (urlparse(url).hostname or "").lower()
            if host_key in host:
                return url
        return ""

    def _build_ui(self) -> None:
        self.root.title("Affitto v2 - GUI Base")
        self.root.geometry("1260x860")
        self.root.minsize(1100, 760)

        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(main)
        notebook.grid(row=0, column=0, sticky="nsew")

        config_tab = ttk.Frame(notebook, padding=10)
        config_tab.columnconfigure(0, weight=1)
        config_tab.columnconfigure(1, weight=1)
        config_tab.rowconfigure(0, weight=1)
        notebook.add(config_tab, text="Configurazione")

        runtime_tab = ttk.Frame(notebook, padding=10)
        runtime_tab.columnconfigure(0, weight=1)
        notebook.add(runtime_tab, text="Runtime")

        logs_tab = ttk.Frame(notebook, padding=10)
        logs_tab.columnconfigure(0, weight=1)
        logs_tab.rowconfigure(0, weight=1)
        notebook.add(logs_tab, text="Log")

        help_tab = ttk.Frame(notebook, padding=10)
        help_tab.columnconfigure(0, weight=1)
        help_tab.rowconfigure(0, weight=1)
        notebook.add(help_tab, text="Aiuto")

        config_left = ttk.Frame(config_tab)
        config_left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        config_left.columnconfigure(0, weight=1)
        config_tab.rowconfigure(0, weight=1)

        config_right = ttk.Frame(config_tab)
        config_right.grid(row=0, column=1, sticky="nsew")
        config_right.columnconfigure(0, weight=1)

        self._build_urls_frame(config_left).grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self._build_channel_mode_frame(config_left).grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self._build_telegram_frame(config_left).grid(row=2, column=0, sticky="ew")
        self._build_email_frame(config_right).grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self._build_actions_frame(config_right).grid(row=1, column=0, sticky="ew")

        self._build_runtime_frame(runtime_tab).grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self._build_blacklist_frame(runtime_tab).grid(row=1, column=0, sticky="ew")

        self._build_logs_frame(logs_tab).grid(row=0, column=0, sticky="nsew")
        self._build_help_frame(help_tab).grid(row=0, column=0, sticky="nsew")

        status_bar = ttk.Label(main, textvariable=self.status_var, anchor=tk.W, padding=(0, 6, 0, 0))
        status_bar.grid(row=1, column=0, sticky="ew")

    def _build_urls_frame(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="URL Ricerca")
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="Idealista URL").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(frame, textvariable=self.idealista_url_var).grid(row=0, column=1, sticky="ew", padx=8, pady=6)
        ttk.Label(frame, text="Immobiliare URL").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(frame, textvariable=self.immobiliare_url_var).grid(row=1, column=1, sticky="ew", padx=8, pady=6)
        return frame

    def _build_channel_mode_frame(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Canali")
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="Modalita invio").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        mode_box = ttk.Combobox(
            frame,
            textvariable=self.notify_mode_var,
            values=list(_NOTIFY_MODES),
            state="readonly",
            width=12,
        )
        mode_box.grid(row=0, column=1, sticky="w", padx=8, pady=6)
        mode_box.bind("<<ComboboxSelected>>", lambda _e: self._apply_notify_mode_lock())
        ttk.Label(
            frame,
            textvariable=self.notify_mode_note_var,
            foreground="#2f4f4f",
            wraplength=420,
            justify=tk.LEFT,
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))
        return frame

    def _build_telegram_frame(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Telegram")
        frame.columnconfigure(1, weight=1)
        ttk.Label(
            frame,
            textvariable=self.telegram_section_note_var,
            foreground="#7a3e00",
            wraplength=420,
            justify=tk.LEFT,
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 0))
        ttk.Label(frame, text="Telegram Bot Token").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.telegram_token_entry = ttk.Entry(frame, textvariable=self.telegram_token_var)
        self.telegram_token_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=6)
        ttk.Label(frame, text="Telegram Chat ID").grid(row=2, column=0, sticky="w", padx=8, pady=6)
        self.telegram_chat_entry = ttk.Entry(frame, textvariable=self.telegram_chat_id_var)
        self.telegram_chat_entry.grid(row=2, column=1, sticky="ew", padx=8, pady=6)
        return frame

    def _build_email_frame(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Email")
        frame.columnconfigure(1, weight=1)
        ttk.Label(
            frame,
            textvariable=self.email_route_label_var,
            foreground="#0b5394",
            wraplength=520,
            justify=tk.LEFT,
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 2))

        ttk.Label(frame, text="Provider email").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.email_provider_box = ttk.Combobox(
            frame,
            textvariable=self.email_provider_var,
            values=[self._email_provider_labels[provider_id] for provider_id in _EMAIL_PROVIDER_ORDER],
            state="readonly",
            width=26,
        )
        self.email_provider_box.grid(row=1, column=1, sticky="w", padx=8, pady=6)
        self.email_provider_box.bind("<<ComboboxSelected>>", lambda _e: self._on_email_provider_changed())

        ttk.Label(frame, text="Mittente").grid(row=2, column=0, sticky="w", padx=8, pady=6)
        self.email_from_entry = ttk.Entry(frame, textvariable=self.email_from_var)
        self.email_from_entry.grid(row=2, column=1, sticky="ew", padx=8, pady=6)

        ttk.Label(frame, text="Username / API key").grid(row=3, column=0, sticky="w", padx=8, pady=6)
        self.email_username_entry = ttk.Entry(frame, textvariable=self.email_username_var)
        self.email_username_entry.grid(row=3, column=1, sticky="ew", padx=8, pady=6)

        ttk.Label(frame, text="Password / Secret").grid(row=4, column=0, sticky="w", padx=8, pady=6)
        self.email_password_entry = ttk.Entry(frame, textvariable=self.email_password_var, show="*")
        self.email_password_entry.grid(row=4, column=1, sticky="ew", padx=8, pady=6)

        ttk.Label(frame, text="Email destinatario").grid(row=5, column=0, sticky="w", padx=8, pady=6)
        self.email_to_entry = ttk.Entry(frame, textvariable=self.email_to_var)
        self.email_to_entry.grid(row=5, column=1, sticky="ew", padx=8, pady=6)

        self.email_advanced_frame = ttk.LabelFrame(frame, text="SMTP avanzato (Custom SMTP)")
        self.email_advanced_frame.columnconfigure(1, weight=1)
        ttk.Label(
            self.email_advanced_frame,
            text="Compila questi campi solo per Custom SMTP. I provider preset continuano a usare i valori del preset.",
            foreground="#2f4f4f",
            wraplength=500,
            justify=tk.LEFT,
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 2))
        ttk.Label(self.email_advanced_frame, text="Host SMTP").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.email_host_entry = ttk.Entry(self.email_advanced_frame, textvariable=self.email_host_var)
        self.email_host_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=6)
        ttk.Label(self.email_advanced_frame, text="Porta").grid(row=2, column=0, sticky="w", padx=8, pady=6)
        self.email_port_entry = ttk.Entry(self.email_advanced_frame, textvariable=self.email_port_var, width=12)
        self.email_port_entry.grid(row=2, column=1, sticky="w", padx=8, pady=6)
        ttk.Label(self.email_advanced_frame, text="Sicurezza").grid(row=3, column=0, sticky="w", padx=8, pady=6)
        self.email_security_mode_box = ttk.Combobox(
            self.email_advanced_frame,
            textvariable=self.email_security_mode_var,
            values=[_SMTP_SECURITY_LABELS[mode] for mode in _SMTP_SECURITY_ORDER],
            state="readonly",
            width=24,
        )
        self.email_security_mode_box.grid(row=3, column=1, sticky="w", padx=8, pady=6)
        ttk.Label(
            self.email_advanced_frame,
            text="Usa 'Nessuna sicurezza' solo se il relay lo richiede esplicitamente.",
            foreground="#7a3e00",
            wraplength=500,
            justify=tk.LEFT,
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))
        self.email_advanced_frame.grid(row=6, column=0, columnspan=2, sticky="ew", padx=8, pady=(4, 6))

        ttk.Label(
            frame,
            textvariable=self.email_provider_help_var,
            foreground="#2f4f4f",
            wraplength=560,
            justify=tk.LEFT,
        ).grid(row=7, column=0, columnspan=2, sticky="w", padx=8, pady=(2, 2))
        ttk.Label(
            frame,
            textvariable=self.email_setup_note_var,
            foreground="#7a3e00",
            wraplength=560,
            justify=tk.LEFT,
        ).grid(row=8, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 2))
        self.email_status_label = tk.Label(
            frame,
            textvariable=self.email_status_label_var,
            anchor="w",
            justify=tk.LEFT,
            fg="#2f4f4f",
        )
        self.email_status_label.grid(row=9, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 2))
        ttk.Label(
            frame,
            textvariable=self.email_status_detail_var,
            foreground="#444444",
            wraplength=560,
            justify=tk.LEFT,
        ).grid(row=10, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 6))

        email_actions = ttk.Frame(frame)
        email_actions.grid(row=11, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))
        self.email_test_connection_btn = ttk.Button(
            email_actions, text="Test connessione", command=self._test_email_connection
        )
        self.email_test_connection_btn.pack(side=tk.LEFT)
        self.email_test_send_btn = ttk.Button(email_actions, text="Test invio", command=self._test_email_send)
        self.email_test_send_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._apply_notify_mode_lock()
        return frame

    def _build_logs_frame(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        filter_row = ttk.Frame(frame)
        filter_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(filter_row, text="Filtro livello").pack(side=tk.LEFT)
        level_box = ttk.Combobox(
            filter_row,
            textvariable=self.log_filter_var,
            values=list(_LOG_LEVELS),
            state="readonly",
            width=10,
        )
        level_box.pack(side=tk.LEFT, padx=(8, 8))
        level_box.bind("<<ComboboxSelected>>", lambda _e: self._refresh_log_view())
        ttk.Button(filter_row, text="Pulisci Log", command=self._clear_logs).pack(side=tk.LEFT)

        self.log_text = ScrolledText(frame, wrap=tk.WORD, height=22)
        self.log_text.grid(row=1, column=0, sticky="nsew")
        self.log_text.configure(state=tk.DISABLED)
        return frame

    def _build_runtime_frame(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Runtime")
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="Ciclo (minuti, min 5)").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Spinbox(frame, from_=5, to=180, textvariable=self.cycle_minutes_var, width=10).grid(
            row=0, column=1, sticky="w", padx=8, pady=6
        )
        ttk.Label(frame, text="Annunci max per sito (max 50)").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        ttk.Spinbox(frame, from_=5, to=50, textvariable=self.max_per_site_var, width=10).grid(
            row=1, column=1, sticky="w", padx=8, pady=6
        )
        ttk.Label(frame, text="Retention giorni").grid(row=2, column=0, sticky="w", padx=8, pady=6)
        ttk.Spinbox(frame, from_=1, to=365, textvariable=self.retention_days_var, width=10).grid(
            row=2, column=1, sticky="w", padx=8, pady=6
        )
        ttk.Label(frame, text="Campi da estrarre").grid(row=3, column=0, sticky="w", padx=8, pady=6)
        fields = ttk.Frame(frame)
        fields.grid(row=3, column=1, sticky="w", padx=8, pady=6)
        ttk.Checkbutton(fields, text="Prezzo", variable=self.extract_price_var).pack(side=tk.LEFT)
        ttk.Checkbutton(fields, text="Zona", variable=self.extract_zone_var).pack(side=tk.LEFT, padx=(10, 0))
        self.extract_agency_check = ttk.Checkbutton(fields, text="Agenzia", variable=self.extract_agency_var)
        self.extract_agency_check.pack(side=tk.LEFT, padx=(10, 0))
        ttk.Checkbutton(frame, text="Modalita annunci privati", variable=self.private_only_ads_var).grid(
            row=4, column=1, sticky="w", padx=8, pady=(0, 2)
        )
        ttk.Label(
            frame,
            textvariable=self.private_only_note_var,
            foreground="#7a3e00",
            wraplength=780,
            justify=tk.LEFT,
        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))
        ttk.Label(
            frame,
            text=(
                "Impostazioni fisse di stabilita: browser=auto(round_robin), "
                "captcha_mode=skip_and_notify, site_guard=ON, headed=ON."
            ),
            foreground="#2f4f4f",
            wraplength=780,
            justify=tk.LEFT,
        ).grid(row=6, column=0, columnspan=2, sticky="w", padx=8, pady=(2, 8))
        return frame

    def _build_blacklist_frame(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Blacklist Agenzie (nome -> regex)")
        frame.columnconfigure(0, weight=1)
        ttk.Label(
            frame,
            text="Aggiungi solo i nomi da bloccare. La GUI li converte in regex in automatico.",
            foreground="#2f4f4f",
            wraplength=780,
            justify=tk.LEFT,
        ).grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        entry_row = ttk.Frame(frame)
        entry_row.grid(row=1, column=0, sticky="ew", padx=8, pady=(4, 6))
        entry_row.columnconfigure(0, weight=1)
        ttk.Entry(entry_row, textvariable=self.blocked_name_var).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(entry_row, text="Aggiungi", command=self._add_blocked_name).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(entry_row, text="Rimuovi selezionata", command=self._remove_selected_blocked_name).grid(row=0, column=2)
        self.blocked_listbox = tk.Listbox(frame, height=4)
        self.blocked_listbox.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        return frame

    def _build_actions_frame(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Azioni")
        frame.columnconfigure(0, weight=1)
        ttk.Label(
            frame,
            text="Usa questo unico pulsante per salvare configurazione generale, email e profilo mittente attivo.",
            foreground="#2f4f4f",
            wraplength=420,
            justify=tk.LEFT,
        ).grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        ttk.Button(frame, text="Salva Configurazione", command=self._save_configuration).grid(
            row=1, column=0, sticky="ew", padx=8, pady=(4, 6)
        )
        ttk.Button(frame, text="Run Once (reale)", command=self._run_once).grid(
            row=2, column=0, sticky="ew", padx=8, pady=6
        )
        self.start_btn = ttk.Button(frame, text="Start Ciclo Automatico", command=self._start_periodic)
        self.start_btn.grid(row=3, column=0, sticky="ew", padx=8, pady=6)
        self.stop_btn = ttk.Button(frame, text="Stop", command=self._stop_running, state=tk.DISABLED)
        self.stop_btn.grid(row=4, column=0, sticky="ew", padx=8, pady=6)
        ttk.Button(frame, text="Reset Site Guard", command=self._reset_guard).grid(
            row=5, column=0, sticky="ew", padx=8, pady=6
        )
        ttk.Button(frame, text="Reset DB Annunci", command=self._reset_listings_db).grid(
            row=6, column=0, sticky="ew", padx=8, pady=6
        )
        ttk.Separator(frame).grid(row=7, column=0, sticky="ew", padx=8, pady=(8, 6))
        ttk.Checkbutton(frame, text="Avvio automatico GUI (Windows)", variable=self.autostart_var).grid(
            row=8, column=0, sticky="w", padx=8, pady=(4, 2)
        )
        ttk.Button(frame, text="Applica Avvio Automatico", command=self._apply_autostart).grid(
            row=9, column=0, sticky="ew", padx=8, pady=(2, 8)
        )
        return frame

    def _build_help_frame(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Guida Rapida")
        info = (
            "Panoramica rapida\n"
            "1) Incolla gli URL di ricerca.\n"
            "2) Scegli i canali da usare.\n"
            "3) Configura Telegram e/o Email.\n"
            "4) Premi Salva Configurazione.\n"
            "5) Esegui i test.\n"
            "6) Usa Run Once.\n"
            "7) Controlla i Log.\n"
            "8) Solo dopo attiva il ciclo automatico.\n\n"
            "Telegram\n"
            "- Token: crea il bot da @BotFather con /newbot.\n"
            "- Chat ID: scrivi al bot o aggiungilo al canale/gruppo, poi usa getUpdates.\n"
            "- Se non arriva nulla: ricontrolla token, chat ID e accesso del bot.\n\n"
            "Email\n"
            "- Provider preset: Gmail, Outlook, Brevo, Mailjet, SMTP2GO, Resend. Host, porta e sicurezza arrivano dal preset.\n"
            "- Custom SMTP: compila host, porta e sicurezza manualmente.\n"
            "- Gmail spesso richiede una app password. I relay/provider usano di solito username/API key e secret dedicati.\n\n"
            "Test\n"
            "- Prima Salva Configurazione.\n"
            "- Poi Test connessione.\n"
            "- Poi Test invio.\n"
            "- Solo dopo usa Run Once.\n\n"
            "Percorsi\n"
            "- Da sorgente: config, DB e log stanno in runtime/.\n"
            "- Da bundle: il runtime sta di default in %LOCALAPPDATA%/AffittoV2/runtime.\n"
            "- Se serve isolarlo per test, usa la variabile AFFITTO_V2_RUNTIME_DIR.\n\n"
            "Run Once\n"
            "- Fa un solo ciclo completo di fetch, deduplica e notifiche.\n"
            "- Serve per verificare il setup prima del ciclo automatico.\n\n"
            "First run / warmup\n"
            "- Su runtime o VM nuovi il primo contatto con Idealista puo entrare in warmup.\n"
            "- Se il primo Run Once segnala suspect o blocked, ripeti una volta e controlla i log prima di usare Reset Site Guard.\n\n"
            "Ciclo automatico\n"
            "- Attivalo solo dopo test OK e un Run Once pulito.\n"
            "- Usa intervalli realistici: minimo 5 minuti, meglio 10-15 se stai ancora tarando il setup.\n\n"
            "Blacklist\n"
            "- Esclude gli annunci dell'agenzia quando il nome corrisponde.\n"
            "- Inserisci solo il nome dell'agenzia: la GUI costruisce la regex.\n"
            "- Usala per blocchi mirati, non per tentativi casuali.\n\n"
            "Log / problemi comuni\n"
            "- Guarda prima la tab Log.\n"
            "- Se usi il bundle, controlla anche il file app.log dentro il runtime del bundle.\n"
            "- Se un test email fallisce: ricontrolla provider, mittente, credenziali, host/porta/sicurezza.\n"
            "- Se Telegram fallisce: ricontrolla token, chat ID e accesso del bot.\n"
            "- Se Run Once bundle fallisce subito: controlla browser disponibili, stato guard e app.log.\n"
            "- Se un canale notifica fallisce, il runtime continua con gli altri canali quando possibile."
        )
        help_text = ScrolledText(frame, wrap=tk.WORD, height=24)
        help_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        help_text.insert("1.0", info)
        help_text.configure(state=tk.DISABLED)
        return frame

    def _bind_email_form_traces(self) -> None:
        for variable in (self.email_host_var, self.email_port_var, self.email_security_mode_var):
            variable.trace_add("write", self._on_email_advanced_fields_changed)

    def _on_email_advanced_fields_changed(self, *_args) -> None:
        self._refresh_email_provider_help()
        self._refresh_email_form_controls()

    def _active_email_profile_id(self) -> str:
        profile_id = _trim_text(self.config.email.sender_profile_id)
        return profile_id or "default_sender"

    def _selected_email_provider_id(self) -> str:
        return self._email_provider_by_label.get(_trim_text(self.email_provider_var.get()), "gmail")

    def _set_selected_email_provider(self, provider_id: str) -> None:
        label = self._email_provider_labels.get(provider_id, self._email_provider_labels["gmail"])
        self.email_provider_var.set(label)

    def _load_email_profiles_safe(self) -> dict[str, EmailSenderProfile]:
        try:
            return load_or_create_profiles(self.profiles_path)
        except Exception:
            return {}

    def _selected_email_security_mode(self) -> str:
        label = _trim_text(self.email_security_mode_var.get())
        for mode, human_label in _SMTP_SECURITY_LABELS.items():
            if label == human_label:
                return mode
        return "starttls"

    def _set_selected_email_security_mode(self, mode: str) -> None:
        normalized = _trim_text(mode).lower() or "starttls"
        self.email_security_mode_var.set(_SMTP_SECURITY_LABELS.get(normalized, _SMTP_SECURITY_LABELS["starttls"]))

    def _parse_email_port(self, value: str | None = None) -> int | None:
        text = _trim_text(self.email_port_var.get() if value is None else value)
        if not text:
            return None
        try:
            port = int(text)
        except ValueError:
            return None
        return port if 1 <= port <= 65535 else None

    def _stored_custom_transport(self) -> tuple[str, int, str] | None:
        if self.config.email.sender_mode == "profile":
            profile = self._load_email_profiles_safe().get(self._active_email_profile_id())
            if profile is not None and profile.provider == "custom" and profile.smtp_host and profile.smtp_port > 0:
                return profile.smtp_host, profile.smtp_port, profile.security_mode
        if (
            self.config.email.sender_mode == "custom"
            and self.config.email.provider == "custom"
            and self.config.email.smtp_host
            and self.config.email.smtp_port > 0
        ):
            return self.config.email.smtp_host, self.config.email.smtp_port, self.config.email.security_mode
        return None

    def _read_email_form_values(self) -> dict[str, str]:
        provider_id = self.config.email.provider
        from_address = ""
        smtp_username = ""
        app_password = ""
        smtp_host = ""
        smtp_port = ""
        security_mode = "starttls"

        if self.config.email.sender_mode == "profile":
            profile = self._load_email_profiles_safe().get(self._active_email_profile_id())
            if profile is not None:
                provider_id = profile.provider
                from_address = profile.from_address
                smtp_username = "" if is_encrypted(profile.smtp_username) else profile.smtp_username
                app_password = "" if is_encrypted(profile.app_password) else profile.app_password
                if profile.provider == "custom":
                    smtp_host = profile.smtp_host
                    smtp_port = str(profile.smtp_port) if profile.smtp_port > 0 else ""
                    security_mode = profile.security_mode
        else:
            provider_id = self.config.email.provider
            from_address = self.config.email.from_address
            smtp_username = "" if is_encrypted(self.config.email.smtp_username) else self.config.email.smtp_username
            app_password = "" if is_encrypted(self.config.email.app_password) else self.config.email.app_password
            if self.config.email.provider == "custom":
                smtp_host = self.config.email.smtp_host
                smtp_port = str(self.config.email.smtp_port) if self.config.email.smtp_port > 0 else ""
                security_mode = self.config.email.security_mode

        return {
            "provider": provider_id or "gmail",
            "from_address": from_address,
            "smtp_username": smtp_username,
            "app_password": app_password,
            "smtp_host": smtp_host,
            "smtp_port": smtp_port,
            "security_mode": security_mode,
            "to_address": self.config.email.to_address,
        }

    def _current_email_form_snapshot(self) -> dict[str, str]:
        return {
            "provider": self._selected_email_provider_id(),
            "from_address": _trim_text(self.email_from_var.get()),
            "smtp_username": _trim_text(self.email_username_var.get()),
            "app_password": _trim_text(self.email_password_var.get()),
            "smtp_host": _trim_text(self.email_host_var.get()),
            "smtp_port": _trim_text(self.email_port_var.get()),
            "security_mode": self._selected_email_security_mode(),
            "to_address": _trim_text(self.email_to_var.get()),
        }

    def _email_profile_dirty(self) -> bool:
        current = self._current_email_form_snapshot()
        loaded = self._email_loaded_snapshot or {}
        keys = ["provider", "from_address", "smtp_username", "app_password"]
        if current.get("provider") == "custom" or loaded.get("provider") == "custom":
            keys.extend(["smtp_host", "smtp_port", "security_mode"])
        for key in keys:
            if current.get(key, "") != loaded.get(key, ""):
                return True
        return False

    def _email_recipient_dirty(self) -> bool:
        current = self._current_email_form_snapshot()
        loaded = self._email_loaded_snapshot or {}
        return current.get("to_address", "") != loaded.get("to_address", "")

    def _current_custom_transport(self) -> tuple[str, int, str] | None:
        smtp_host = _trim_text(self.email_host_var.get())
        smtp_port = self._parse_email_port()
        security_mode = self._selected_email_security_mode()
        if smtp_host and smtp_port is not None:
            return smtp_host, smtp_port, security_mode
        return None

    def _ensure_custom_transport_defaults(self) -> None:
        if self._selected_email_provider_id() != "custom":
            return
        if self._trimmed_custom_fields_present():
            return
        stored_transport = self._stored_custom_transport()
        if stored_transport is not None:
            smtp_host, smtp_port, security_mode = stored_transport
            self.email_host_var.set(smtp_host)
            self.email_port_var.set(str(smtp_port))
            self._set_selected_email_security_mode(security_mode)
            return
        self.email_port_var.set("587")
        self._set_selected_email_security_mode("starttls")

    def _trimmed_custom_fields_present(self) -> bool:
        return bool(
            _trim_text(self.email_host_var.get())
            or _trim_text(self.email_port_var.get())
        )

    def _load_email_form(self) -> None:
        values = self._read_email_form_values()
        self._set_selected_email_provider(values["provider"])
        self.email_from_var.set(values["from_address"])
        self.email_username_var.set(values["smtp_username"])
        self.email_password_var.set(values["app_password"])
        self.email_host_var.set(values["smtp_host"])
        self.email_port_var.set(values["smtp_port"])
        self._set_selected_email_security_mode(values["security_mode"])
        self.email_to_var.set(values["to_address"])
        self._email_loaded_snapshot = self._current_email_form_snapshot()
        self._refresh_email_provider_path()
        self._refresh_email_provider_help()
        self._refresh_email_form_controls()

    def _refresh_email_provider_path(self) -> None:
        provider_id = self._selected_email_provider_id()
        if provider_id == "custom":
            self.email_route_label_var.set("Percorso attivo: Custom SMTP avanzato.")
            self.email_advanced_frame.grid()
            return
        preset = get_smtp_preset(provider_id)
        if preset is not None:
            security_label = _SMTP_SECURITY_LABELS.get(preset.security_mode, preset.security_mode)
            self.email_route_label_var.set(
                f"Percorso attivo: Provider preset. Host/porta/sicurezza gestiti da {preset.label} "
                f"({preset.smtp_host}:{preset.smtp_port}, {security_label})."
            )
        else:
            self.email_route_label_var.set("Percorso attivo: Provider preset.")
        self.email_advanced_frame.grid_remove()

    def _status_color_for_state(self, state: str) -> str:
        if state in {"connection_ok", "send_ok"}:
            return "#2e7d32"
        if state in {"configured_unverified"}:
            return "#0b5394"
        if state in {"profile_missing", "profile_unreadable", "error", "incomplete_placeholder"}:
            return "#b22222"
        return "#555555"

    def _refresh_email_status(self):
        try:
            db_path = _resolve_db_from_config(self.config_path, self.config.storage.db_path)
            db = Database(db_path)
            db.init_schema()
            status = get_email_configuration_status(self.config, profiles_path=self.profiles_path, db=db)
        except Exception as exc:
            self.email_status_label_var.set("Stato email: errore")
            self.email_status_detail_var.set(str(exc))
            self.email_status_label.configure(fg="#b22222")
            self._email_status = None
            return None

        self._email_status = status
        self.email_status_label_var.set(f"Stato email: {status.label}")
        detail = status.detail.strip()
        self.email_status_detail_var.set(detail)
        self.email_status_label.configure(fg=self._status_color_for_state(status.state))
        self._refresh_email_form_controls()
        return status

    def _refresh_email_provider_help(self) -> None:
        provider_id = self._selected_email_provider_id()
        preset = get_smtp_preset(provider_id)
        if provider_id == "custom":
            self.email_provider_help_var.set(
                "Percorso advanced attivo: configura manualmente host, porta e sicurezza del relay SMTP. "
                "Solo qui puoi usare anche 'Nessuna sicurezza'."
            )
        else:
            self.email_provider_help_var.set(preset.help_text if preset is not None else "")

        note_parts: list[str] = []
        mode = self.notify_mode_var.get().strip().lower()
        if mode == "telegram":
            note_parts.append(
                "Canale email disattivato dalla Modalita invio selezionata. "
                "Campi e test restano visibili ma non sono modificabili."
            )
        if provider_id == "custom":
            if self._current_custom_transport() is None:
                note_parts.append("Compila host, porta e sicurezza per configurare il relay da zero.")
            else:
                note_parts.append(
                    "Setup custom attivo: puoi modificare i valori senza perdere host, porta, sicurezza o secret gia salvati."
                )
            if _trim_text((self._email_loaded_snapshot or {}).get("app_password", "")):
                note_parts.append("Se non cambi il secret, viene mantenuto al salvataggio.")
        elif preset is not None:
            security_label = _SMTP_SECURITY_LABELS.get(preset.security_mode, preset.security_mode)
            note_parts.append(
                f"Modalita semplice attiva: host/porta/sicurezza arrivano dal preset ({preset.smtp_host}:{preset.smtp_port}, {security_label})."
            )
        self.email_setup_note_var.set(" ".join(note_parts).strip())

    def _is_email_test_running(self) -> bool:
        return self._email_test_worker is not None and self._email_test_worker.is_alive()

    def _refresh_email_form_controls(self) -> None:
        mode = self.notify_mode_var.get().strip().lower()
        provider_id = self._selected_email_provider_id()
        custom_transport = self._current_custom_transport()
        email_enabled = mode in {"email", "both"}
        custom_ready = provider_id != "custom" or custom_transport is not None
        can_test = (
            email_enabled
            and custom_ready
            and not self._is_email_test_running()
            and not (self._worker is not None and self._worker.is_alive())
        )
        inputs_enabled = email_enabled and not self._is_email_test_running()
        advanced_enabled = inputs_enabled and provider_id == "custom"

        self._set_widget_enabled(self.email_from_entry, inputs_enabled)
        self._set_widget_enabled(self.email_username_entry, inputs_enabled)
        self._set_widget_enabled(self.email_password_entry, inputs_enabled)
        self._set_widget_enabled(self.email_to_entry, inputs_enabled)
        self._set_widget_enabled(self.email_provider_box, inputs_enabled)
        self._set_widget_enabled(self.email_host_entry, advanced_enabled)
        self._set_widget_enabled(self.email_port_entry, advanced_enabled)
        self._set_widget_enabled(self.email_security_mode_box, advanced_enabled)
        self._set_widget_enabled(self.email_test_connection_btn, can_test)
        self._set_widget_enabled(self.email_test_send_btn, can_test)

    def _refresh_notify_mode_notes(self) -> None:
        mode = self.notify_mode_var.get().strip().lower()
        if mode == "telegram":
            self.notify_mode_note_var.set("Canale attivo: Telegram. La sezione Email e bloccata.")
            self.telegram_section_note_var.set("")
            return
        if mode == "email":
            self.notify_mode_note_var.set("Canale attivo: Email. La sezione Telegram e bloccata.")
            self.telegram_section_note_var.set("Canale Telegram disattivato dalla Modalita invio selezionata.")
            return
        self.notify_mode_note_var.set("Canali attivi: Telegram + Email.")
        self.telegram_section_note_var.set("")

    def _on_private_only_changed(self, *_args) -> None:
        self._refresh_private_only_controls()

    def _refresh_private_only_controls(self) -> None:
        private_only = bool(self.private_only_ads_var.get())
        if private_only:
            if not self.extract_agency_var.get():
                self.extract_agency_var.set(True)
            self._set_widget_enabled(self.extract_agency_check, False)
            self.private_only_note_var.set(
                "Con modalita attiva il progetto esclude localmente gli annunci con agenzia rilevata. "
                "Se il parser non rileva l'agenzia, l'annuncio resta ammesso e viene contato come segnale incerto."
            )
            return
        self._set_widget_enabled(self.extract_agency_check, True)
        self.private_only_note_var.set(
            "Con modalita disattiva il progetto usa solo il filtro URL del sito e l'eventuale blacklist agenzie locale."
        )

    def _on_email_provider_changed(self) -> None:
        if self._selected_email_provider_id() == "custom":
            self._ensure_custom_transport_defaults()
        self._refresh_email_provider_path()
        self._refresh_email_provider_help()
        self._refresh_email_form_controls()

    def _validate_email_destination(self) -> None:
        to_address = _trim_text(self.email_to_var.get())
        if not to_address:
            raise ConfigError("Destinatario email obbligatorio.")
        if not _looks_like_email(to_address):
            raise ConfigError("Destinatario email non valido.")

    def _resolved_email_secret(self) -> str:
        secret = _trim_text(self.email_password_var.get())
        if secret:
            return secret
        return _trim_text((self._email_loaded_snapshot or {}).get("app_password", ""))

    def _validate_sender_fields(self) -> tuple[str, str, str]:
        from_address = _trim_text(self.email_from_var.get())
        smtp_username = _trim_text(self.email_username_var.get())
        app_password = self._resolved_email_secret()

        if not from_address:
            raise ConfigError("Mittente email obbligatorio.")
        if not _looks_like_email(from_address):
            raise ConfigError("Mittente email non valido.")
        if not smtp_username:
            raise ConfigError("Username / API key SMTP obbligatorio.")
        if not app_password:
            raise ConfigError("Password / secret SMTP obbligatoria.")
        return from_address, smtp_username, app_password

    def _build_email_profile_from_form(self) -> EmailSenderProfile:
        provider_id = self._selected_email_provider_id()
        profile_id = self._active_email_profile_id()
        self._validate_email_destination()
        from_address, smtp_username, app_password = self._validate_sender_fields()

        if provider_id == "custom":
            smtp_host = _trim_text(self.email_host_var.get())
            if not smtp_host:
                raise ConfigError("Host SMTP obbligatorio per Custom SMTP.")
            smtp_port = self._parse_email_port()
            if smtp_port is None:
                raise ConfigError("Porta SMTP non valida. Usa un numero tra 1 e 65535.")
            security_mode = self._selected_email_security_mode()
            if security_mode not in _SMTP_SECURITY_LABELS:
                raise ConfigError("Seleziona la sicurezza SMTP per il relay custom.")
            return EmailSenderProfile(
                profile_id=profile_id,
                provider="custom",
                from_address=from_address,
                smtp_username=smtp_username,
                app_password=app_password,
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                security_mode=security_mode,
            )

        return EmailSenderProfile(
            profile_id=profile_id,
            provider=provider_id,
            from_address=from_address,
            smtp_username=smtp_username,
            app_password=app_password,
        )

    def _email_form_readiness_issues(self) -> tuple[list[str], list[str]]:
        missing: list[str] = []
        invalid: list[str] = []

        from_address = _trim_text(self.email_from_var.get())
        smtp_username = _trim_text(self.email_username_var.get())
        app_password = self._resolved_email_secret()
        to_address = _trim_text(self.email_to_var.get())

        if not from_address:
            missing.append("mittente")
        elif not _looks_like_email(from_address):
            invalid.append("mittente")

        if not smtp_username:
            missing.append("username / API key")

        if not app_password:
            missing.append("password / secret")

        if not to_address:
            missing.append("destinatario")
        elif not _looks_like_email(to_address):
            invalid.append("destinatario")

        if self._selected_email_provider_id() == "custom":
            if not _trim_text(self.email_host_var.get()):
                missing.append("host SMTP")
            port_text = _trim_text(self.email_port_var.get())
            if not port_text:
                missing.append("porta SMTP")
            elif self._parse_email_port(port_text) is None:
                invalid.append("porta SMTP")
            if self._selected_email_security_mode() not in _SMTP_SECURITY_LABELS:
                missing.append("sicurezza SMTP")

        return missing, invalid

    def _ensure_email_ready_for_save(self) -> EmailSenderProfile:
        missing, invalid = self._email_form_readiness_issues()
        if missing or invalid:
            parts: list[str] = []
            if missing:
                parts.append("Completa i campi richiesti: " + ", ".join(missing) + ".")
            if invalid:
                parts.append("Controlla questi campi: " + ", ".join(invalid) + ".")
            parts.append("Oppure passa a 'telegram' se non vuoi usare email adesso.")
            raise GuiUserFacingError(
                "Configurazione email incompleta",
                "Configurazione email incompleta. " + " ".join(parts),
            )
        try:
            return self._build_email_profile_from_form()
        except ConfigError as exc:
            raise GuiUserFacingError(
                "Configurazione email non valida",
                "Configurazione email non valida. Controlla i campi richiesti oppure passa a 'telegram'.",
            ) from exc

    def _load_blocked_names(self) -> None:
        self.blocked_listbox.delete(0, tk.END)
        for name in self._blocked_names:
            self.blocked_listbox.insert(tk.END, name)

    def _add_blocked_name(self) -> None:
        value = _normalize_spaces(self.blocked_name_var.get())
        if not value:
            return
        if value.lower() in {x.lower() for x in self._blocked_names}:
            self.blocked_name_var.set("")
            return
        self._blocked_names.append(value)
        self.blocked_name_var.set("")
        self._load_blocked_names()

    def _remove_selected_blocked_name(self) -> None:
        sel = self.blocked_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self._blocked_names):
            self._blocked_names.pop(idx)
        self._load_blocked_names()

    def _set_widget_enabled(self, widget: tk.Widget, enabled: bool) -> None:
        try:
            if enabled:
                widget.state(("!disabled",))
            else:
                widget.state(("disabled",))
            return
        except Exception:
            pass
        widget.configure(state=tk.NORMAL if enabled else tk.DISABLED)

    def _apply_notify_mode_lock(self) -> None:
        mode = self.notify_mode_var.get().strip().lower()
        if mode not in _NOTIFY_MODES:
            mode = "both"
            self.notify_mode_var.set(mode)

        telegram_enabled = mode in {"telegram", "both"}

        self._set_widget_enabled(self.telegram_token_entry, telegram_enabled)
        self._set_widget_enabled(self.telegram_chat_entry, telegram_enabled)
        self._refresh_notify_mode_notes()
        self._refresh_email_provider_help()
        self._refresh_email_form_controls()

    def _collect_urls(self) -> list[str]:
        urls = []
        for field_name, var in (("Idealista URL", self.idealista_url_var), ("Immobiliare URL", self.immobiliare_url_var)):
            raw = str(var.get() or "").strip()
            v = _sanitize_supported_url(raw)
            if raw and not v:
                raise ConfigError(f"{field_name}: URL non valido. Incolla un URL completo di idealista.it o immobiliare.it.")
            if v:
                var.set(v)
                urls.append(v)
        return urls

    def _save_configuration(self, show_message: bool = True, *, email_action: bool = False) -> bool:
        try:
            if self._is_email_test_running():
                raise ConfigError("Attendi la fine del test email in corso prima di salvare o avviare un run.")
            urls = self._collect_urls()
            if not urls:
                raise ConfigError("Inserisci almeno un URL di ricerca.")

            max_per_site = int(self.max_per_site_var.get())
            if max_per_site > 50:
                max_per_site = 50
                self.max_per_site_var.set(50)

            data = self.config.model_dump()
            data["search_urls"] = urls
            data["runtime"]["cycle_minutes"] = int(self.cycle_minutes_var.get())
            data["runtime"]["max_listings_per_page"] = max_per_site
            data["runtime"]["captcha_mode"] = "skip_and_notify"
            data["runtime"]["auto_restart_on_failure"] = True
            data["storage"]["retention_days"] = int(self.retention_days_var.get())
            data["extraction"]["extract_price"] = bool(self.extract_price_var.get())
            data["extraction"]["extract_zone"] = bool(self.extract_zone_var.get())
            data["extraction"]["private_only_ads"] = bool(self.private_only_ads_var.get())
            if self.private_only_ads_var.get():
                self.extract_agency_var.set(True)
            data["extraction"]["extract_agency"] = bool(self.extract_agency_var.get())

            mode = self.notify_mode_var.get().strip().lower()
            if mode not in _NOTIFY_MODES:
                mode = "both"
                self.notify_mode_var.set(mode)

            email_channel_active = mode in {"email", "both"}
            preview_profile = None
            if email_channel_active:
                preview_profile = self._ensure_email_ready_for_save()

            data["telegram"]["enabled"] = mode in {"telegram", "both"}
            data["telegram"]["bot_token"] = _trim_text(self.telegram_token_var.get())
            data["telegram"]["chat_id"] = _trim_text(self.telegram_chat_id_var.get())
            data["telegram"]["target_type"] = "channel"

            data["email"]["enabled"] = mode in {"email", "both"}
            data["email"]["to_address"] = _trim_text(self.email_to_var.get())

            profile_dirty = self._email_profile_dirty()
            recipient_dirty = self._email_recipient_dirty()
            should_persist_profile = email_action or (email_channel_active and profile_dirty)
            profile = None
            if should_persist_profile:
                profile = preview_profile if preview_profile is not None else self._build_email_profile_from_form()
                data["email"]["provider"] = profile.provider
                data["email"]["sender_mode"] = "profile"
                data["email"]["sender_profile_id"] = profile.profile_id
            elif email_channel_active and recipient_dirty and self.config.email.sender_mode == "profile":
                data["email"]["sender_mode"] = "profile"
                data["email"]["sender_profile_id"] = self._active_email_profile_id()

            validated = AppConfig.model_validate(data)
            if profile is not None:
                upsert_profile(self.profiles_path, profile)
            save_config(validated, self.config_path)
            self.config = validated
            self.extract_agency_var.set(self.config.extraction.extract_agency)
            self.private_only_ads_var.set(self.config.extraction.private_only_ads)
            self._refresh_private_only_controls()

            db_path = _resolve_db_from_config(self.config_path, self.config.storage.db_path)
            db = Database(db_path)
            db.init_schema()
            patterns = [_agency_name_to_regex(name) for name in self._blocked_names if _agency_name_to_regex(name)]
            db.set_blocked_agency_patterns(patterns)

            secure_profiles_file(self.profiles_path)
            self._load_email_form()
            self._refresh_email_status()
            self.gui_state = {
                "version": _GUI_STATE_VERSION,
                "notify_mode": mode,
                "blocked_agency_names": list(self._blocked_names),
                "log_filter": self.log_filter_var.get().strip().upper(),
                "autostart_enabled": bool(self.autostart_var.get()),
            }
            _save_gui_state(self.gui_state_path, self.gui_state)
            self.status_var.set("Configurazione salvata.")
            if show_message:
                messagebox.showinfo("Affitto v2", "Configurazione salvata con successo.")
            return True
        except (ConfigError, ValueError) as exc:
            title = exc.title if isinstance(exc, GuiUserFacingError) else "Configurazione non valida"
            messagebox.showerror(title, str(exc))
            if isinstance(exc, GuiUserFacingError):
                self.status_var.set("Salvataggio bloccato: email incompleta.")
            else:
                self.status_var.set("Errore configurazione.")
            return False

    def _clear_logs(self) -> None:
        self._log_records.clear()
        self._refresh_log_view()

    def _refresh_log_view(self) -> None:
        level_filter = self.log_filter_var.get().strip().upper()
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        for level, line in self._log_records:
            if level_filter != "ALL" and level != level_filter:
                continue
            self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _enqueue(self, kind: str, payload: str) -> None:
        self._queue.put((kind, payload))

    def _drain_queue(self) -> None:
        changed = False
        while True:
            try:
                kind, payload = self._queue.get_nowait()
            except Empty:
                break
            if kind == "log":
                level = _parse_log_level(payload)
                self._log_records.append((level, payload))
                changed = True
            elif kind == "status":
                self.status_var.set(str(payload))
            elif kind == "done":
                self._periodic_mode = False
                self.start_btn.configure(state=tk.NORMAL)
                self.stop_btn.configure(state=tk.DISABLED)
            elif kind == "email-test-finished":
                self._handle_email_test_finished(payload)
        if changed:
            self._refresh_log_view()
        self.root.after(120, self._drain_queue)

    def _friendly_email_test_error(self, message: str) -> str:
        raw = _trim_text(message)
        if not raw:
            return "Test email fallito."
        lowered = raw.lower()
        if "timed out" in lowered or "timeout" in lowered:
            return f"Timeout SMTP: il relay non ha risposto in tempo. Controlla host, porta e rete.\n\nDettaglio: {raw}"
        if any(token in lowered for token in ("authentication failed", "auth", "5.7.8", "535", "534")):
            return (
                "Autenticazione SMTP fallita. Controlla username/API key, password/secret e permessi del provider.\n\n"
                f"Dettaglio: {raw}"
            )
        if any(token in lowered for token in ("ssl", "tls", "starttls", "wrong version number", "certificate")):
            return (
                "Handshake TLS/SSL fallito. Controlla porta e modalita di sicurezza selezionata.\n\n"
                f"Dettaglio: {raw}"
            )
        return raw

    def _handle_email_test_finished(self, payload: object) -> None:
        self._email_test_worker = None
        result = payload if isinstance(payload, dict) else {}
        dry_run = bool(result.get("dry_run"))
        exit_code = int(result.get("exit_code", 1))
        output = str(result.get("output") or "").strip()
        action_label = "Test connessione" if dry_run else "Test invio"

        status = self._refresh_email_status()
        self._refresh_email_form_controls()

        if exit_code == 0:
            self.status_var.set(f"{action_label} completato.")
            messagebox.showinfo("Email", f"{action_label} completato con successo.")
            return

        detail = ""
        if status is not None:
            detail = status.detail.strip() or status.label
        if not detail:
            lines = [line.strip() for line in output.splitlines() if line.strip()]
            detail = lines[-1] if lines else f"{action_label} fallito."
        self.status_var.set(f"{action_label} fallito.")
        messagebox.showerror("Email", self._friendly_email_test_error(detail))

    def _cli_command(self, *args: str) -> list[str]:
        if self.bundle_mode:
            launcher = self.cli_exe if self.cli_exe.exists() else Path(sys.executable).resolve()
            return [str(launcher), *args]
        return [str(sys.executable), str(self.run_py), *args]

    def _build_fetch_command(self, send_real_notifications: bool, guard_ignore_cooldown: bool = False) -> list[str]:
        mode = self.notify_mode_var.get().strip().lower()
        if mode not in _NOTIFY_MODES:
            mode = "both"
        cmd = self._cli_command(
            "fetch-live-once",
            "--headed",
            "--notify-mode",
            mode,
            "--browser-channel",
            "auto",
            "--channel-rotation-mode",
            "round_robin",
            "--max-per-site",
            str(int(self.max_per_site_var.get())),
            "--captcha-wait-sec",
            "20",
            "--guard-jitter-min-sec",
            "2",
            "--guard-jitter-max-sec",
            "6",
            "--guard-base-cooldown-min",
            "30",
            "--guard-max-cooldown-min",
            "360",
            "--guard-state-file",
            str(self.guard_state_path),
            "--log-level",
            "INFO",
        )
        if send_real_notifications:
            cmd.append("--send-real-notifications")
        if guard_ignore_cooldown:
            cmd.append("--guard-ignore-cooldown")
        return cmd

    def _run_fetch_process(self, send_real_notifications: bool, guard_ignore_cooldown: bool = False) -> int:
        cmd = self._build_fetch_command(
            send_real_notifications=send_real_notifications,
            guard_ignore_cooldown=guard_ignore_cooldown,
        )
        self._enqueue("log", f"$ {' '.join(cmd)}")
        proc = subprocess.Popen(
            cmd,
            cwd=str(self.app_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        with self._process_lock:
            self._active_proc = proc
        assert proc.stdout is not None
        for line in proc.stdout:
            self._enqueue("log", line.rstrip("\r\n"))
            if self._stop_event.is_set():
                break
        if self._stop_event.is_set() and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                proc.kill()
        code = proc.wait()
        with self._process_lock:
            self._active_proc = None
        return code

    def _run_once_worker(self) -> None:
        self._enqueue("status", "Run once in esecuzione...")
        code = self._run_fetch_process(send_real_notifications=True, guard_ignore_cooldown=True)
        if code == 0:
            self._enqueue("status", "Run once completata.")
        else:
            self._enqueue("status", f"Run once terminata con errore (code={code}).")
        self._enqueue("done", "one-shot")

    def _run_once(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            messagebox.showwarning("Affitto v2", "Un run e gia in corso.")
            return
        if not self._save_configuration(show_message=False):
            return
        self._stop_event.clear()
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self._worker = threading.Thread(target=self._run_once_worker, daemon=True)
        self._worker.start()

    def _periodic_worker(self) -> None:
        self._enqueue("status", "Ciclo automatico avviato.")
        while not self._stop_event.is_set():
            code = self._run_fetch_process(send_real_notifications=True, guard_ignore_cooldown=False)
            if code != 0:
                self._enqueue("log", f"[WARN] Run ciclo terminata con code={code}.")
            if self._stop_event.is_set():
                break
            wait_minutes = int(self.cycle_minutes_var.get())
            wait_sec = max(5, wait_minutes * 60)
            self._enqueue("status", f"In attesa del prossimo ciclo ({wait_minutes} min).")
            end_ts = time.time() + wait_sec
            while time.time() < end_ts:
                if self._stop_event.wait(timeout=1):
                    break
        self._enqueue("status", "Ciclo automatico fermato.")
        self._enqueue("done", "periodic")

    def _start_periodic(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            messagebox.showwarning("Affitto v2", "Un run e gia in corso.")
            return
        if not self._save_configuration(show_message=False):
            return
        self._periodic_mode = True
        self._stop_event.clear()
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self._worker = threading.Thread(target=self._periodic_worker, daemon=True)
        self._worker.start()

    def _stop_running(self) -> None:
        self._stop_event.set()
        with self._process_lock:
            proc = self._active_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        self.status_var.set("Richiesto stop ciclo/run.")

    def _reset_guard(self) -> None:
        try:
            urls = self._collect_urls()
            if not urls:
                raise ConfigError("Inserisci almeno un URL prima di resettare il guard state.")
            _reset_guard_state(self.guard_state_path, urls)
            self.status_var.set("Site guard resettato (emergenza).")
            self._enqueue("log", f"[INFO] Site guard reset manuale: {self.guard_state_path}")
        except Exception as exc:
            messagebox.showerror("Reset guard", str(exc))

    def _reset_listings_db(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            messagebox.showwarning("Reset DB", "Ferma prima un run/ciclo attivo.")
            return
        confirm = messagebox.askyesno(
            "Reset DB Annunci",
            "Eliminare tutti gli annunci salvati nel DB?\n"
            "Le blacklist agenzie resteranno invariate.",
        )
        if not confirm:
            return
        try:
            db_path = _resolve_db_from_config(self.config_path, self.config.storage.db_path)
            db = Database(db_path)
            db.init_schema()
            removed = db.reset_listings()
            self.status_var.set(f"DB annunci resettato. record_rimossi={removed}")
            self._enqueue("log", f"[INFO] DB listings reset. path={db_path} removed={removed}")
        except Exception as exc:
            messagebox.showerror("Reset DB", str(exc))

    def _start_email_test(self, *, dry_run: bool) -> None:
        if self._worker is not None and self._worker.is_alive():
            messagebox.showwarning("Email", "Ferma prima il run/ciclo attivo per evitare conflitti sulla configurazione.")
            return
        if self._is_email_test_running():
            messagebox.showwarning("Email", "Un test email e gia in corso.")
            return
        if self.notify_mode_var.get().strip().lower() not in {"email", "both"}:
            messagebox.showwarning("Email", "Imposta Modalita invio su email o both prima di lanciare i test.")
            return
        if not self._save_configuration(show_message=False, email_action=True):
            return

        self.status_var.set("Test email in esecuzione...")
        self._refresh_email_form_controls()
        self._email_test_worker = threading.Thread(target=self._email_test_worker_run, args=(dry_run,), daemon=True)
        self._email_test_worker.start()

    def _email_test_worker_run(self, dry_run: bool) -> None:
        cmd = self._cli_command(
            "test-email",
            "--config",
            str(self.config_path),
            "--profiles",
            str(self.profiles_path),
            "--log-level",
            "INFO",
        )
        if dry_run:
            cmd.append("--dry-run")

        self._enqueue("log", f"$ {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            cwd=str(self.app_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = result.stdout or ""
        for line in output.splitlines():
            self._enqueue("log", line.rstrip("\r\n"))
        self._enqueue(
            "email-test-finished",
            {
                "dry_run": dry_run,
                "exit_code": result.returncode,
                "output": output,
            },
        )

    def _test_email_connection(self) -> None:
        self._start_email_test(dry_run=True)

    def _test_email_send(self) -> None:
        self._start_email_test(dry_run=False)

    def _is_autostart_enabled(self) -> bool:
        script = _windows_startup_script_path()
        return bool(script and script.exists())

    def _apply_autostart(self) -> None:
        script = _windows_startup_script_path()
        if script is None:
            messagebox.showwarning("Avvio automatico", "APPDATA non disponibile su questo sistema.")
            return
        try:
            if self.autostart_var.get():
                script.parent.mkdir(parents=True, exist_ok=True)
                if self.bundle_mode:
                    launcher = Path(sys.executable).resolve()
                    content = "@echo off\r\n" f'cd /d "{self.app_root}"\r\n' f'"{launcher}"\r\n'
                else:
                    py = _pythonw_or_python()
                    content = (
                        "@echo off\r\n"
                        f'cd /d "{self.app_root}"\r\n'
                        f'"{py}" "{self.run_py}" gui\r\n'
                    )
                script.write_text(content, encoding="utf-8")
                self.status_var.set("Avvio automatico abilitato.")
            else:
                if script.exists():
                    script.unlink()
                self.status_var.set("Avvio automatico disabilitato.")
            self.gui_state["autostart_enabled"] = bool(self.autostart_var.get())
            _save_gui_state(self.gui_state_path, self.gui_state)
        except Exception as exc:
            messagebox.showerror("Avvio automatico", str(exc))

    def on_close(self) -> None:
        self._stop_running()
        self.root.after(200, self.root.destroy)


def launch_gui(config_path: Path | None = None, profiles_path: Path | None = None) -> None:
    ensure_runtime_dirs()
    cfg_path = config_path or resolve_config_path(None)
    profiles = profiles_path or default_profiles_path(cfg_path)
    root = tk.Tk()
    app = AffittoGuiApp(root, config_path=cfg_path, profiles_path=profiles)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()

