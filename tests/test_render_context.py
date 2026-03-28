from __future__ import annotations

import logging
import unittest
from unittest import mock

from src.affitto_v2.scrapers import live_fetch
from src.affitto_v2.scrapers.render_context import (
    GLOBAL_RENDER_CONTEXT_INIT_SCRIPT,
    install_render_context_init_script,
)


class _RecordingContext:
    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []

    async def add_init_script(self, *, script: str | None = None, path: str | None = None) -> None:
        self.calls.append({"script": script, "path": path})


class _FakeBrowserContext:
    def __init__(self) -> None:
        self.pages: list[object] = []
        self.created_page = object()

    async def new_page(self) -> object:
        self.pages.append(self.created_page)
        return self.created_page


class _FakeBrowser:
    def __init__(self, context: _FakeBrowserContext) -> None:
        self._context = context

    async def new_context(self) -> _FakeBrowserContext:
        return self._context


def _build_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    logger.setLevel(logging.INFO)
    return logger


class RenderContextInitScriptTests(unittest.TestCase):
    def test_init_script_contains_static_browser_overrides(self) -> None:
        self.assertIn("deviceMemory', 16", GLOBAL_RENDER_CONTEXT_INIT_SCRIPT)
        self.assertIn("hardwareConcurrency', 8", GLOBAL_RENDER_CONTEXT_INIT_SCRIPT)
        self.assertIn("Intel Inc.", GLOBAL_RENDER_CONTEXT_INIT_SCRIPT)
        self.assertIn("Intel(R) Iris(TM) Graphics Xe", GLOBAL_RENDER_CONTEXT_INIT_SCRIPT)
        self.assertIn("getParameter", GLOBAL_RENDER_CONTEXT_INIT_SCRIPT)
        self.assertIn("toDataURL", GLOBAL_RENDER_CONTEXT_INIT_SCRIPT)


class InstallRenderContextInitScriptTests(unittest.IsolatedAsyncioTestCase):
    async def test_install_render_context_init_script_registers_global_script(self) -> None:
        context = _RecordingContext()

        await install_render_context_init_script(context)

        self.assertEqual(
            context.calls,
            [{"script": GLOBAL_RENDER_CONTEXT_INIT_SCRIPT, "path": None}],
        )


class LaunchBrowserSessionRenderContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_launch_browser_session_installs_script_for_ephemeral_context(self) -> None:
        fake_context = _FakeBrowserContext()
        fake_browser = _FakeBrowser(fake_context)
        install_mock = mock.AsyncMock()
        bootstrap_mock = mock.AsyncMock()

        with (
            mock.patch.object(live_fetch, "_camoufox_launch_kwargs", return_value={}),
            mock.patch.object(live_fetch, "_resolve_channel_executable_path", return_value=None),
            mock.patch.object(live_fetch, "_site_profile_generation", return_value="generation-1"),
            mock.patch.object(live_fetch, "AsyncNewBrowser", new=mock.AsyncMock(return_value=fake_browser)),
            mock.patch.object(live_fetch, "install_render_context_init_script", new=install_mock),
            mock.patch.object(live_fetch, "bootstrap_static_resources_cache", new=bootstrap_mock),
        ):
            browser, context, page, channel_label = await live_fetch._launch_browser_session(
                pw=object(),
                site="idealista",
                profile_dir=None,
                requested_channel=None,
                guard_state={},
                headless=True,
                logger=_build_logger("test.render_context.launch"),
            )

        self.assertIs(browser, fake_browser)
        self.assertIs(context, fake_context)
        self.assertIs(page, fake_context.created_page)
        self.assertEqual(channel_label, "camoufox")
        install_mock.assert_awaited_once_with(fake_context, logger=mock.ANY)
        bootstrap_mock.assert_awaited_once_with(fake_context, logger=mock.ANY)
