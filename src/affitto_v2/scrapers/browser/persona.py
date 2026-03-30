from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from browserforge.fingerprints import Screen
from camoufox.pkgman import launch_path as camoufox_launch_path
from camoufox.utils import launch_options as camoufox_launch_options

from ..core_types import CamoufoxPersona

DEFAULT_BROWSER_LABEL = "camoufox"
CHANNEL_LABELS = (DEFAULT_BROWSER_LABEL,)
CAMOUFOX_DEFAULT_LOCALE = "it-IT"
CAMOUFOX_DEFAULT_OS = "windows"
CAMOUFOX_DEFAULT_TIMEZONE = "Europe/Rome"
CAMOUFOX_PERSONA_VERSION = 1
CAMOUFOX_PERSONA_WINDOWS = (
    {
        "label": "desktop_fhd_balanced",
        "screen": (1920, 1080),
        "windows": ((1760, 990), (1680, 960), (1600, 900)),
    },
    {
        "label": "desktop_fhd_compact",
        "screen": (1920, 1080),
        "windows": ((1540, 900), (1480, 860), (1440, 840)),
    },
    {
        "label": "desktop_fhd_wide",
        "screen": (1920, 1080),
        "windows": ((1820, 1020), (1740, 980), (1660, 940)),
    },
)


def normalize_channel_label(value: str | None) -> str:
    return DEFAULT_BROWSER_LABEL


def channel_to_label(channel: str | None) -> str:
    return normalize_channel_label(channel)


def label_to_channel(label: str) -> str | None:
    normalize_channel_label(label)
    return None


def resolve_channel_executable_path(label: str) -> Path | None:
    if normalize_channel_label(label) != DEFAULT_BROWSER_LABEL:
        return None
    try:
        return Path(camoufox_launch_path())
    except Exception:
        return None


def is_channel_available(label: str) -> bool:
    return resolve_channel_executable_path(label) is not None


def slug(value: str) -> str:
    out = []
    for ch in (value or "").lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in {"-", "_"}:
            out.append(ch)
        else:
            out.append("-")
    text = "".join(out).strip("-")
    while "--" in text:
        text = text.replace("--", "-")
    return text or "n-a"


def camoufox_persona_path(profile_root: Path) -> Path:
    return profile_root / "camoufox_persona.json"


def camoufox_persona_seed(*, site: str, channel_label: str, profile_generation: int) -> int:
    raw = f"{site}|{channel_label}|{profile_generation}|camoufox-persona-v{CAMOUFOX_PERSONA_VERSION}"
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def camoufox_screen_constraints(*, width: int = 1920, height: int = 1080) -> Screen:
    return Screen(
        min_width=width,
        max_width=width,
        min_height=height,
        max_height=height,
    )


def camoufox_persona_from_payload(payload: dict[str, object]) -> CamoufoxPersona | None:
    try:
        launch_options = payload.get("launch_options")
        if not isinstance(launch_options, dict):
            return None
        persona = CamoufoxPersona(
            version=int(payload.get("version") or 0),
            persona_id=str(payload.get("persona_id") or "").strip(),
            seed=int(payload.get("seed") or 0),
            site=str(payload.get("site") or "").strip(),
            channel_label=str(payload.get("channel_label") or "").strip(),
            profile_generation=int(payload.get("profile_generation") or 0),
            created_utc=str(payload.get("created_utc") or "").strip(),
            screen_label=str(payload.get("screen_label") or "").strip(),
            screen_width=int(payload.get("screen_width") or 0),
            screen_height=int(payload.get("screen_height") or 0),
            window_width=int(payload.get("window_width") or 0),
            window_height=int(payload.get("window_height") or 0),
            humanize_max_sec=float(payload.get("humanize_max_sec") or 0.0),
            history_length=int(payload.get("history_length") or 0),
            font_spacing_seed=int(payload.get("font_spacing_seed") or 0),
            canvas_aa_offset=int(payload.get("canvas_aa_offset") or 0),
            launch_options=launch_options,
        )
    except (TypeError, ValueError):
        return None
    if (
        persona.version != CAMOUFOX_PERSONA_VERSION
        or not persona.persona_id
        or not persona.site
        or not persona.channel_label
        or not persona.created_utc
        or not persona.screen_label
        or persona.screen_width <= 0
        or persona.screen_height <= 0
        or persona.window_width <= 0
        or persona.window_height <= 0
        or persona.humanize_max_sec <= 0
        or persona.history_length <= 0
        or not persona.launch_options
    ):
        return None
    return persona


def build_camoufox_persona(
    *,
    site: str,
    channel_label: str,
    profile_generation: int,
    executable_path: Path | None,
    now: datetime,
) -> CamoufoxPersona:
    resolved_executable_path = executable_path if executable_path is not None and executable_path.exists() else None
    seed = camoufox_persona_seed(
        site=site,
        channel_label=channel_label,
        profile_generation=profile_generation,
    )
    rng = random.Random(seed)
    screen_profile = CAMOUFOX_PERSONA_WINDOWS[rng.randrange(len(CAMOUFOX_PERSONA_WINDOWS))]
    screen_width, screen_height = screen_profile["screen"]
    window_width, window_height = rng.choice(screen_profile["windows"])
    humanize_max_sec = round(rng.uniform(0.95, 1.45), 2)
    history_length = rng.randint(2, 5)
    font_spacing_seed = rng.randint(0, 1_073_741_823)
    canvas_aa_offset = rng.randint(-18, 18)
    config = {
        "timezone": CAMOUFOX_DEFAULT_TIMEZONE,
        "window.history.length": history_length,
        "fonts:spacing_seed": font_spacing_seed,
        "canvas:aaOffset": canvas_aa_offset,
        "canvas:aaCapOffset": True,
    }
    launch_options = camoufox_launch_options(
        headless=False,
        humanize=humanize_max_sec,
        locale=CAMOUFOX_DEFAULT_LOCALE,
        os=CAMOUFOX_DEFAULT_OS,
        screen=camoufox_screen_constraints(width=screen_width, height=screen_height),
        window=(window_width, window_height),
        config=config,
        executable_path=resolved_executable_path,
        i_know_what_im_doing=True,
    )
    return CamoufoxPersona(
        version=CAMOUFOX_PERSONA_VERSION,
        persona_id=f"{site}-{channel_label}-g{profile_generation:03d}-{seed % 10000:04d}",
        seed=seed,
        site=site,
        channel_label=channel_label,
        profile_generation=profile_generation,
        created_utc=now.isoformat(),
        screen_label=str(screen_profile["label"]),
        screen_width=screen_width,
        screen_height=screen_height,
        window_width=window_width,
        window_height=window_height,
        humanize_max_sec=humanize_max_sec,
        history_length=history_length,
        font_spacing_seed=font_spacing_seed,
        canvas_aa_offset=canvas_aa_offset,
        launch_options=launch_options,
    )


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    data = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


def load_or_create_camoufox_persona(
    *,
    site: str,
    channel_label: str,
    profile_generation: int,
    profile_root: Path,
    executable_path: Path | None,
    logger,
) -> CamoufoxPersona:
    persona_path = camoufox_persona_path(profile_root)
    if persona_path.exists():
        try:
            raw = json.loads(persona_path.read_text(encoding="utf-8"))
        except Exception:
            raw = None
        if isinstance(raw, dict):
            persona = camoufox_persona_from_payload(raw)
            if (
                persona is not None
                and persona.site == site
                and persona.channel_label == channel_label
                and persona.profile_generation == profile_generation
            ):
                return persona
            logger.info(
                "Camoufox persona file invalid or stale. site=%s channel=%s generation=%s file=%s",
                site,
                channel_label,
                profile_generation,
                persona_path,
            )
    persona = build_camoufox_persona(
        site=site,
        channel_label=channel_label,
        profile_generation=profile_generation,
        executable_path=executable_path,
        now=datetime.now(timezone.utc),
    )
    _write_json_atomic(persona_path, asdict(persona))
    logger.info(
        "Created Camoufox persona. site=%s channel=%s generation=%s persona=%s screen=%sx%s window=%sx%s humanize_max_sec=%s file=%s",
        site,
        channel_label,
        profile_generation,
        persona.persona_id,
        persona.screen_width,
        persona.screen_height,
        persona.window_width,
        persona.window_height,
        persona.humanize_max_sec,
        persona_path,
    )
    return persona


def camoufox_launch_kwargs(
    *,
    headless: bool,
    executable_path: Path | None,
    persistent_profile_dir: Path | None = None,
    persona: CamoufoxPersona | None = None,
) -> dict[str, object]:
    if persona is not None:
        launch_kwargs = json.loads(json.dumps(persona.launch_options))
        launch_kwargs["headless"] = headless
        if persistent_profile_dir is not None:
            launch_kwargs["persistent_context"] = True
            launch_kwargs["user_data_dir"] = str(persistent_profile_dir)
        if executable_path is not None:
            launch_kwargs["executable_path"] = str(executable_path)
        return launch_kwargs
    launch_kwargs: dict[str, object] = {
        "headless": headless,
        "humanize": True,
        "locale": CAMOUFOX_DEFAULT_LOCALE,
        "os": CAMOUFOX_DEFAULT_OS,
        "screen": camoufox_screen_constraints(),
        "config": {"timezone": CAMOUFOX_DEFAULT_TIMEZONE},
        "i_know_what_im_doing": True,
    }
    if persistent_profile_dir is not None:
        launch_kwargs["persistent_context"] = True
        launch_kwargs["user_data_dir"] = str(persistent_profile_dir)
    if executable_path is not None:
        launch_kwargs["executable_path"] = str(executable_path)
    return launch_kwargs


def profile_dir_for_channel(base_dir: Path, channel_label: str) -> Path:
    base_name = base_dir.name.strip().lower()
    if base_name == channel_label:
        return base_dir
    if base_name in CHANNEL_LABELS:
        return base_dir.parent / channel_label
    return base_dir / channel_label


def profile_dir_for_site(base_dir: Path, site: str) -> Path:
    base_name = base_dir.name.strip().lower()
    site_slug = slug(site)
    if base_name == site_slug:
        return base_dir
    if base_name in CHANNEL_LABELS:
        return base_dir.parent / site_slug
    return base_dir / site_slug


def profile_dir_for_site_channel(
    base_dir: Path,
    site: str,
    channel_label: str,
    profile_generation: int = 0,
) -> Path:
    site_root = profile_dir_for_site(base_dir, site)
    generation = max(0, int(profile_generation or 0))
    if generation > 0:
        site_root = site_root / f"gen-{generation:03d}"
    return profile_dir_for_channel(site_root, channel_label)


def session_profile_root(
    profile_dir: str | None,
    site: str,
    channel_label: str,
    profile_generation: int = 0,
) -> Path | None:
    if not profile_dir:
        return None
    return profile_dir_for_site_channel(
        Path(profile_dir).expanduser(),
        site,
        channel_label,
        profile_generation=profile_generation,
    )


def session_owner_key(*, site: str, channel_label: str, profile_root: Path | None) -> str:
    profile_part = str(profile_root) if profile_root is not None else "ephemeral"
    return f"{site}|{channel_label}|{profile_part}"


def session_identity(
    *,
    site: str,
    channel_label: str,
    profile_dir: str | None,
    profile_generation: int = 0,
) -> tuple[str, Path | None]:
    profile_root = session_profile_root(
        profile_dir,
        site,
        channel_label,
        profile_generation=profile_generation,
    )
    return (session_owner_key(site=site, channel_label=channel_label, profile_root=profile_root), profile_root)


__all__ = [
    "CAMOUFOX_DEFAULT_LOCALE",
    "CAMOUFOX_DEFAULT_OS",
    "CAMOUFOX_DEFAULT_TIMEZONE",
    "CHANNEL_LABELS",
    "DEFAULT_BROWSER_LABEL",
    "build_camoufox_persona",
    "camoufox_launch_kwargs",
    "camoufox_persona_from_payload",
    "camoufox_persona_path",
    "camoufox_persona_seed",
    "camoufox_screen_constraints",
    "channel_to_label",
    "is_channel_available",
    "label_to_channel",
    "load_or_create_camoufox_persona",
    "normalize_channel_label",
    "profile_dir_for_channel",
    "profile_dir_for_site",
    "profile_dir_for_site_channel",
    "resolve_channel_executable_path",
    "session_identity",
    "session_owner_key",
    "session_profile_root",
    "slug",
]
