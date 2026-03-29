from __future__ import annotations

import asyncio
import random

from .session_policy import SessionPolicy


async def apply_interaction_pacing(
    *,
    logger=None,
    reason: str = "interaction",
    policy: SessionPolicy,
    clip_min_sec: float | None = None,
    clip_max_sec: float | None = None,
    random_module=random,
    sleep_func=asyncio.sleep,
) -> float:
    raw_delay_sec = max(0.0, random_module.gammavariate(policy.pacing_gamma_shape, policy.pacing_gamma_scale))
    effective_clip_min: float | None = None
    effective_clip_max: float | None = None
    if clip_min_sec is not None:
        effective_clip_min = max(0.0, float(clip_min_sec))
    if clip_max_sec is not None:
        effective_clip_max = max(0.0, float(clip_max_sec))
    if (
        effective_clip_min is not None
        and effective_clip_max is not None
        and effective_clip_max < effective_clip_min
    ):
        effective_clip_max = effective_clip_min

    delay_sec = raw_delay_sec
    if effective_clip_min is not None:
        delay_sec = max(effective_clip_min, delay_sec)
    if effective_clip_max is not None:
        delay_sec = min(effective_clip_max, delay_sec)
    clipped = delay_sec != raw_delay_sec
    if logger is not None:
        if clipped:
            logger.info(
                "Interaction pacing clipped. site=%s reason=%s raw_delay_sec=%.3f delay_sec=%.3f clip_min_sec=%s clip_max_sec=%s shape=%s scale=%s",
                policy.site,
                reason,
                raw_delay_sec,
                delay_sec,
                f"{effective_clip_min:.3f}" if effective_clip_min is not None else "none",
                f"{effective_clip_max:.3f}" if effective_clip_max is not None else "none",
                policy.pacing_gamma_shape,
                policy.pacing_gamma_scale,
            )
        else:
            logger.debug(
                "Interaction pacing scheduled. site=%s reason=%s delay_sec=%.3f shape=%s scale=%s",
                policy.site,
                reason,
                delay_sec,
                policy.pacing_gamma_shape,
                policy.pacing_gamma_scale,
            )
    await sleep_func(delay_sec)
    if logger is not None:
        logger.debug(
            "Interaction pacing completed. site=%s reason=%s delay_sec=%.3f clipped=%s",
            policy.site,
            reason,
            delay_sec,
            clipped,
        )
    return delay_sec


async def bootstrap_static_resources_cache(context, *, logger, policy: SessionPolicy, pacing_func=None) -> None:
    bootstrap_page = None
    warmed_count = 0
    try:
        logger.info(
            "Static resource bootstrap start. site=%s endpoints=%s timeout_ms=%s",
            policy.site,
            len(policy.bootstrap_urls),
            policy.bootstrap_timeout_ms,
        )
        bootstrap_page = await context.new_page()
        for url in policy.bootstrap_urls:
            try:
                logger.debug("Static resource bootstrap warm-up start. site=%s url=%s", policy.site, url)
                if pacing_func is not None:
                    await pacing_func(
                        logger=logger,
                        reason=f"bootstrap_static_resources_cache:{url}",
                        site=policy.site,
                    )
                else:
                    await apply_interaction_pacing(
                        logger=logger,
                        reason=f"bootstrap_static_resources_cache:{url}",
                        policy=policy,
                    )
                await bootstrap_page.goto(
                    url,
                    wait_until="commit",
                    timeout=policy.bootstrap_timeout_ms,
                )
                warmed_count += 1
                logger.debug("Static resource bootstrap warm-up completed. site=%s url=%s", policy.site, url)
            except Exception as exc:
                logger.debug(
                    "Static resource bootstrap skipped endpoint. site=%s url=%s error=%s",
                    policy.site,
                    url,
                    type(exc).__name__,
                )
        logger.info(
            "Static resource bootstrap completed. site=%s warmed=%s total=%s",
            policy.site,
            warmed_count,
            len(policy.bootstrap_urls),
        )
    finally:
        if bootstrap_page is not None:
            try:
                await bootstrap_page.close()
                logger.debug("Static resource bootstrap page closed. site=%s", policy.site)
            except Exception:
                pass


__all__ = [
    "apply_interaction_pacing",
    "bootstrap_static_resources_cache",
]
