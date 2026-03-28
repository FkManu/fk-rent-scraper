from __future__ import annotations

import logging
import unittest
from types import SimpleNamespace
from unittest import mock

from src.affitto_v2.models import ExtractionFields
from src.affitto_v2.scrapers import live_fetch


def _build_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    logger.setLevel(logging.INFO)
    return logger


class _Closable:
    def __init__(self, calls: list[str], label: str) -> None:
        self._calls = calls
        self._label = label

    async def close(self) -> None:
        self._calls.append(self._label)


class _FakeClickable:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    async def click(self, timeout: int | None = None) -> None:
        del timeout
        self._calls.append("click")

    async def is_visible(self) -> bool:
        return True


class _FakeCookieLocator:
    def __init__(self, calls: list[str], *, count: int = 1) -> None:
        self._calls = calls
        self._count = count
        self.first = _FakeClickable(calls)

    async def count(self) -> int:
        return self._count


class _FakeCookiePage:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def locator(self, selector: str) -> _FakeCookieLocator:
        del selector
        return _FakeCookieLocator(self._calls)

    def get_by_role(self, role: str, name: str) -> _FakeCookieLocator:
        del role, name
        return _FakeCookieLocator(self._calls, count=0)

    async def wait_for_timeout(self, timeout_ms: int) -> None:
        del timeout_ms
        self._calls.append("wait")


class _FakeGotoPage:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self.url = ""

    async def goto(self, url: str, timeout: int | None = None) -> SimpleNamespace:
        del timeout
        self.url = url
        self._calls.append("goto")
        return SimpleNamespace(status=200)

    async def wait_for_load_state(self, state: str, timeout: int | None = None) -> None:
        del state, timeout
        self._calls.append("wait_for_load_state")

    async def wait_for_timeout(self, timeout_ms: int) -> None:
        del timeout_ms
        self._calls.append("wait_for_timeout")


class InteractionPacingTests(unittest.IsolatedAsyncioTestCase):
    async def test_apply_interaction_pacing_uses_gamma_distribution(self) -> None:
        sleep_mock = mock.AsyncMock()

        with (
            mock.patch.object(live_fetch.random, "gammavariate", return_value=4.25) as gamma_mock,
            mock.patch.object(live_fetch.asyncio, "sleep", new=sleep_mock),
        ):
            delay_sec = await live_fetch.apply_interaction_pacing()

        gamma_mock.assert_called_once_with(2.0, 1.5)
        sleep_mock.assert_awaited_once_with(4.25)
        self.assertEqual(delay_sec, 4.25)

    async def test_close_browser_handles_paces_before_each_close(self) -> None:
        calls: list[str] = []

        async def record_pacing(*args, **kwargs) -> None:
            del args, kwargs
            calls.append("pace")

        with mock.patch.object(live_fetch, "apply_interaction_pacing", new=mock.AsyncMock(side_effect=record_pacing)):
            await live_fetch._close_browser_handles(
                context=_Closable(calls, "context.close"),
                browser=_Closable(calls, "browser.close"),
            )

        self.assertEqual(calls, ["pace", "context.close", "pace", "browser.close"])

    async def test_accept_cookies_paces_before_click(self) -> None:
        calls: list[str] = []
        page = _FakeCookiePage(calls)

        async def record_pacing(*args, **kwargs) -> None:
            del args, kwargs
            calls.append("pace")

        with mock.patch.object(live_fetch, "apply_interaction_pacing", new=mock.AsyncMock(side_effect=record_pacing)):
            await live_fetch._accept_cookies_if_present(page)

        self.assertEqual(calls, ["pace", "click", "wait"])

    async def test_extract_for_url_paces_before_goto(self) -> None:
        calls: list[str] = []
        page = _FakeGotoPage(calls)

        async def record_pacing(*args, **kwargs) -> None:
            del args, kwargs
            calls.append("pace")

        with (
            mock.patch.object(live_fetch, "apply_interaction_pacing", new=mock.AsyncMock(side_effect=record_pacing)),
            mock.patch.object(live_fetch, "_accept_cookies_if_present", new=mock.AsyncMock()),
        ):
            cards, outcome, stats = await live_fetch._extract_for_url(
                page=page,
                search_url="https://example.com/search",
                extraction=ExtractionFields(),
                max_per_site=10,
                wait_after_goto_ms=250,
                nav_timeout_ms=1000,
                captcha_mode="skip_and_notify",
                captcha_wait_sec=0,
                headless=True,
                debug_dir=None,
                listing_cache_db=None,
                detail_budget_remaining=None,
                logger=_build_logger("test.interaction_pacing.goto"),
            )

        self.assertEqual(calls[:2], ["pace", "goto"])
        self.assertEqual(cards, [])
        self.assertEqual(outcome.code, "unsupported_site")
        self.assertEqual(outcome.tier, "degraded")
        self.assertEqual(stats.retry_count, 0)
