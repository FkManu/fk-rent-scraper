from __future__ import annotations

import logging
import unittest
from unittest import mock

from src.affitto_v2.scrapers import live_fetch


def _build_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    return logger


class _FakeBootstrapPage:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self._calls = calls

    async def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        self._calls.append(("goto", url, wait_until, timeout))

    async def close(self) -> None:
        self._calls.append(("close",))


class _FakeBootstrapContext:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self._calls = calls

    async def new_page(self) -> _FakeBootstrapPage:
        self._calls.append(("new_page",))
        return _FakeBootstrapPage(self._calls)


class StaticResourceBootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def test_bootstrap_static_resources_cache_warms_endpoints_and_closes_page(self) -> None:
        calls: list[tuple[str, object]] = []
        context = _FakeBootstrapContext(calls)

        async def record_pacing(*args, **kwargs) -> None:
            del args, kwargs
            calls.append(("pace",))

        with mock.patch.object(live_fetch, "apply_interaction_pacing", new=mock.AsyncMock(side_effect=record_pacing)):
            await live_fetch.bootstrap_static_resources_cache(
                context,
                logger=_build_logger("test.static_resource_bootstrap"),
            )

        self.assertEqual(calls[0], ("new_page",))
        self.assertEqual(calls[-1], ("close",))
        goto_calls = [call for call in calls if call[0] == "goto"]
        self.assertEqual(
            goto_calls,
            [
                ("goto", "https://www.gstatic.com/generate_204", "commit", 5000),
                ("goto", "https://www.google.it/generate_204", "commit", 5000),
                ("goto", "https://www.cloudflare.com/cdn-cgi/trace", "commit", 5000),
            ],
        )
        self.assertEqual(len([call for call in calls if call[0] == "pace"]), 3)
