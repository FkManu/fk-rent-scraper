from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path


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


def prune_debug_artifacts(
    *,
    debug_dir: Path,
    logger,
    now_epoch: float | None = None,
    retention_sec: int,
    max_files: int,
) -> int:
    if not debug_dir.exists():
        return 0
    now_ts = time.time() if now_epoch is None else float(now_epoch)
    candidates: list[tuple[float, Path]] = []
    for path in debug_dir.iterdir():
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        candidates.append((float(stat.st_mtime), path))
    if not candidates:
        return 0

    removed = 0
    stale_cutoff = now_ts - max(0, int(retention_sec))
    for mtime, path in list(candidates):
        if mtime >= stale_cutoff:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    if removed:
        candidates = [(mtime, path) for mtime, path in candidates if path.exists()]

    max_count = max(1, int(max_files))
    if len(candidates) > max_count:
        candidates.sort(key=lambda item: item[0], reverse=True)
        for _, path in candidates[max_count:]:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass

    if removed:
        logger.info(
            "Pruned live debug artifacts. removed=%s dir=%s retention_sec=%s max_files=%s",
            removed,
            debug_dir,
            retention_sec,
            max_count,
        )
    return removed


def save_guard_event_artifact(*, debug_dir: Path | None, site: str, event: str, payload: dict, logger) -> None:
    if debug_dir is None:
        return
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = debug_dir / f"{stamp}_{slug(site)}_{slug(event)}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        logger.info("Saved guard event artifact. file=%s", path)
    except Exception as exc:
        logger.debug("Unable to save guard event artifact (%s): %s", event, exc)


async def save_debug_artifacts(*, page, debug_dir: Path | None, site: str, reason: str, logger, normalize_func) -> None:
    if debug_dir is None:
        return
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stem = f"{stamp}_{slug(site)}_{slug(reason)}"
        html_path = debug_dir / f"{stem}.html"
        png_path = debug_dir / f"{stem}.png"
        title = normalize_func(await page.title())
        html = await page.content()
        header = f"<!-- url: {page.url}\n title: {title}\n reason: {reason}\n -->\n"
        html_path.write_text(header + html, encoding="utf-8")
        await page.screenshot(path=str(png_path), full_page=True)
        logger.info("Saved live debug artifacts. html=%s screenshot=%s", html_path, png_path)
    except Exception as exc:
        logger.debug("Unable to save debug artifacts (%s): %s", reason, exc)


__all__ = [
    "prune_debug_artifacts",
    "save_debug_artifacts",
    "save_guard_event_artifact",
    "slug",
]
