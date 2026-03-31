from __future__ import annotations

import logging
import tempfile
import unittest
from unittest import mock

from src.affitto_v2.scrapers import live_fetch
from src.affitto_v2.scrapers.browser.persona import camoufox_canvas_noise_offsets
from src.affitto_v2.scrapers.render_context import (
    GLOBAL_RENDER_CONTEXT_INIT_SCRIPT,
    build_render_context_init_script,
    install_render_context_init_script,
)
from src.affitto_v2.scrapers.browser.session_policy import HardwareMimetics


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
        self.assertNotIn("deviceMemory", GLOBAL_RENDER_CONTEXT_INIT_SCRIPT)
        self.assertIn("hardwareConcurrency', 8", GLOBAL_RENDER_CONTEXT_INIT_SCRIPT)
        self.assertIn("Firefox/135.0", GLOBAL_RENDER_CONTEXT_INIT_SCRIPT)
        self.assertIn("Intel Inc.", GLOBAL_RENDER_CONTEXT_INIT_SCRIPT)
        self.assertIn("Intel(R) Iris(TM) Graphics Xe", GLOBAL_RENDER_CONTEXT_INIT_SCRIPT)
        self.assertIn("getParameter", GLOBAL_RENDER_CONTEXT_INIT_SCRIPT)
        self.assertIn("toDataURL", GLOBAL_RENDER_CONTEXT_INIT_SCRIPT)
        self.assertIn("(data[index] + 1)", GLOBAL_RENDER_CONTEXT_INIT_SCRIPT)
        self.assertIn("(data[index + 1] + 2)", GLOBAL_RENDER_CONTEXT_INIT_SCRIPT)
        self.assertIn("(data[index + 2] + 3)", GLOBAL_RENDER_CONTEXT_INIT_SCRIPT)

    def test_canvas_noise_offsets_are_deterministic_from_seed(self) -> None:
        self.assertEqual(camoufox_canvas_noise_offsets(123456789), camoufox_canvas_noise_offsets(123456789))
        self.assertNotEqual(camoufox_canvas_noise_offsets(123456789), camoufox_canvas_noise_offsets(123456790))


class InstallRenderContextInitScriptTests(unittest.IsolatedAsyncioTestCase):
    async def test_install_render_context_init_script_registers_global_script(self) -> None:
        context = _RecordingContext()

        await install_render_context_init_script(context)

        self.assertEqual(
            context.calls,
            [{"script": GLOBAL_RENDER_CONTEXT_INIT_SCRIPT, "path": None}],
        )

    def test_build_render_context_init_script_uses_hardware_signature(self) -> None:
        script = build_render_context_init_script(
            HardwareMimetics(
                user_agent="UA-Test",
                device_memory=32,
                hardware_concurrency=12,
                webgl_vendor="Vendor-Test",
                webgl_renderer="Renderer-Test",
                canvas_r_offset=4,
                canvas_g_offset=5,
                canvas_b_offset=6,
            )
        )

        self.assertNotIn("deviceMemory", script)
        self.assertIn("hardwareConcurrency', 12", script)
        self.assertIn("userAgent', 'UA-Test'", script)
        self.assertIn("Vendor-Test", script)
        self.assertIn("Renderer-Test", script)
        self.assertIn("(data[index] + 4)", script)
        self.assertIn("(data[index + 1] + 5)", script)
        self.assertIn("(data[index + 2] + 6)", script)


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
        install_mock.assert_awaited_once()
        self.assertIs(install_mock.await_args.args[0], fake_context)
        self.assertIn("hardware", install_mock.await_args.kwargs)
        self.assertIn("logger", install_mock.await_args.kwargs)
        bootstrap_mock.assert_awaited_once_with(fake_context, logger=mock.ANY, site="idealista")

    async def test_launch_browser_session_uses_persona_seeded_canvas_offsets_for_persistent_profiles(self) -> None:
        fake_context = _FakeBrowserContext()
        install_mock = mock.AsyncMock()
        bootstrap_mock = mock.AsyncMock()
        persona = mock.Mock(
            persona_id="idealista-camoufox-g001-0001",
            screen_width=1920,
            screen_height=1080,
            window_width=1600,
            window_height=900,
            humanize_max_sec=1.2,
            canvas_r_offset=4,
            canvas_g_offset=5,
            canvas_b_offset=6,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                mock.patch.object(live_fetch, "_camoufox_launch_kwargs", return_value={}),
                mock.patch.object(live_fetch, "_resolve_channel_executable_path", return_value=None),
                mock.patch.object(live_fetch, "_site_profile_generation", return_value=1),
                mock.patch.object(live_fetch, "_load_or_create_camoufox_persona", return_value=persona),
                mock.patch.object(live_fetch, "AsyncNewBrowser", new=mock.AsyncMock(return_value=fake_context)),
                mock.patch.object(live_fetch, "install_render_context_init_script", new=install_mock),
                mock.patch.object(live_fetch, "bootstrap_static_resources_cache", new=bootstrap_mock),
            ):
                _, context, page, channel_label = await live_fetch._launch_browser_session(
                    pw=object(),
                    site="idealista",
                    profile_dir=tmpdir,
                    requested_channel=None,
                    guard_state={},
                    headless=True,
                    logger=_build_logger("test.render_context.launch.persona"),
                )

        self.assertIs(context, fake_context)
        self.assertIs(page, fake_context.created_page)
        self.assertEqual(channel_label, "camoufox")
        hardware = install_mock.await_args.kwargs["hardware"]
        self.assertEqual(hardware.canvas_noise_mode, "persona_seeded")
        self.assertEqual(hardware.canvas_r_offset, 4)
        self.assertEqual(hardware.canvas_g_offset, 5)
        self.assertEqual(hardware.canvas_b_offset, 6)
