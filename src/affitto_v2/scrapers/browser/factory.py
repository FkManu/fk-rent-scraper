from __future__ import annotations

import shutil
from pathlib import Path

from .bootstrap import apply_interaction_pacing
from .session_policy import SessionPolicy


async def close_browser_handles(*, context, browser, logger=None, policy: SessionPolicy | None = None, pacing_func=None) -> None:
    if context is not None:
        try:
            if policy is not None:
                if pacing_func is not None:
                    await pacing_func(logger=logger, reason="close_browser_handles:context", site=policy.site)
                else:
                    await apply_interaction_pacing(logger=logger, reason="close_browser_handles:context", policy=policy)
            await context.close()
            if logger is not None:
                logger.debug("Browser context closed.")
        except Exception as exc:
            if logger is not None:
                logger.debug("Browser context close skipped. error=%s", type(exc).__name__)
    if browser is not None:
        try:
            if policy is not None:
                if pacing_func is not None:
                    await pacing_func(logger=logger, reason="close_browser_handles:browser", site=policy.site)
                else:
                    await apply_interaction_pacing(logger=logger, reason="close_browser_handles:browser", policy=policy)
            await browser.close()
            if logger is not None:
                logger.debug("Browser instance closed.")
        except Exception as exc:
            if logger is not None:
                logger.debug("Browser instance close skipped. error=%s", type(exc).__name__)


async def close_browser_slots(slots: dict, *, policy_by_site, logger=None, pacing_func=None) -> None:
    for slot in slots.values():
        policy = policy_by_site(slot.site)
        await close_browser_handles(
            context=slot.context,
            browser=slot.browser,
            logger=logger,
            policy=policy,
            pacing_func=pacing_func,
        )


async def prune_site_session_slots(
    slots: dict,
    *,
    site: str,
    preserve_owner: str,
    policy_by_site,
    logger=None,
    pacing_func=None,
) -> int:
    removed = 0
    for owner_key, slot in list(slots.items()):
        if slot.site != site or (preserve_owner and owner_key == preserve_owner):
            continue
        slots.pop(owner_key, None)
        policy = policy_by_site(slot.site)
        await close_browser_handles(
            context=slot.context,
            browser=slot.browser,
            logger=logger,
            policy=policy,
            pacing_func=pacing_func,
        )
        removed += 1
    return removed


def destroy_persistent_profile_root(*, profile_root: str | Path | None, base_dir: str | Path | None, logger, site: str) -> bool:
    if not profile_root or not base_dir:
        return False
    target = Path(profile_root).expanduser().resolve()
    base = Path(base_dir).expanduser().resolve()
    try:
        target.relative_to(base)
    except ValueError:
        logger.warning(
            "Skipped profile destruction outside managed root. site=%s profile_root=%s base_dir=%s",
            site,
            target,
            base,
        )
        return False
    if not target.exists():
        return False
    shutil.rmtree(target, ignore_errors=False)
    logger.info("Destroyed persistent profile root. site=%s profile_root=%s", site, target)
    return True


__all__ = [
    "close_browser_handles",
    "close_browser_slots",
    "destroy_persistent_profile_root",
    "prune_site_session_slots",
]
