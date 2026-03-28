from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import io
import logging
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.affitto_v2 import main as app_main
from src.affitto_v2 import gui_app
from src.affitto_v2.db import Database, ListingRecord
from src.affitto_v2.logging_live import SafeRotatingFileHandler, setup_logging
from src.affitto_v2.models import AppConfig, EmailConfig, ExtractionFields, TelegramConfig
from src.affitto_v2.pipeline import PipelineRunOptions, process_listings
from src.affitto_v2.scrapers import live_fetch


def _build_config(*, private_only_ads: bool) -> AppConfig:
    return AppConfig(
        search_urls=["https://www.immobiliare.it/search-list/?idContratto=2&idCategoria=1"],
        extraction=ExtractionFields(private_only_ads=private_only_ads, extract_agency=not private_only_ads),
        telegram=TelegramConfig(enabled=True, bot_token="token", chat_id="chat"),
        email=EmailConfig(enabled=False, provider="gmail"),
    )


def _build_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    logger.setLevel(logging.INFO)
    return logger


class _Var:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


class PrivateOnlyModeTests(unittest.TestCase):
    def test_private_only_forces_agency_extraction(self) -> None:
        extraction = ExtractionFields(extract_agency=False, private_only_ads=True)
        self.assertTrue(extraction.extract_agency)

    def test_private_only_excludes_detected_agencies_and_tracks_unknowns(self) -> None:
        config = _build_config(private_only_ads=True)
        listings = [
            ListingRecord(
                site="idealista",
                search_url=config.search_urls[0],
                ad_id="ad-1",
                url="https://www.idealista.it/immobile/1/",
                title="Annuncio con agenzia",
                agency="Agency Torino",
            ),
            ListingRecord(
                site="idealista",
                search_url=config.search_urls[0],
                ad_id="ad-2",
                url="https://www.idealista.it/immobile/2/",
                title="Annuncio senza segnale",
                agency="",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "test.db")
            db.init_schema()
            result = process_listings(
                config=config,
                db=db,
                listings=listings,
                logger=_build_logger("test.private_only.enabled"),
                options=PipelineRunOptions(notify_mode="none", send_real_notifications=False),
            )

        self.assertEqual(result.processed, 2)
        self.assertEqual(result.skipped_private_only, 1)
        self.assertEqual(result.private_only_allowed_unknown, 1)
        self.assertEqual(result.inserted_new, 1)

    def test_standard_mode_keeps_detected_agencies(self) -> None:
        config = _build_config(private_only_ads=False)
        listings = [
            ListingRecord(
                site="immobiliare",
                search_url=config.search_urls[0],
                ad_id="ad-1",
                url="https://www.immobiliare.it/annunci/1/",
                title="Annuncio agenzia",
                agency="Agency Milano",
            ),
            ListingRecord(
                site="immobiliare",
                search_url=config.search_urls[0],
                ad_id="ad-2",
                url="https://www.immobiliare.it/annunci/2/",
                title="Annuncio senza segnale",
                agency="",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "test.db")
            db.init_schema()
            result = process_listings(
                config=config,
                db=db,
                listings=listings,
                logger=_build_logger("test.private_only.disabled"),
                options=PipelineRunOptions(notify_mode="none", send_real_notifications=False),
            )

        self.assertEqual(result.skipped_private_only, 0)
        self.assertEqual(result.private_only_allowed_unknown, 0)
        self.assertEqual(result.inserted_new, 2)


class SafeRotatingFileHandlerTests(unittest.TestCase):
    def test_rollover_lock_is_swallowed_and_logging_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "app.log"
            handler = SafeRotatingFileHandler(
                filename=log_path,
                maxBytes=1,
                backupCount=1,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            with mock.patch.object(handler, "rotate", side_effect=PermissionError(32, "locked", str(log_path))):
                logger = logging.getLogger("test.safe_rotate")
                logger.handlers.clear()
                logger.addHandler(handler)
                logger.propagate = False
                logger.setLevel(logging.INFO)
                logger.info("a")
                logger.info("b")
                handler.flush()
                text = log_path.read_text(encoding="utf-8")
                self.assertIn("b", text)
                handler.close()

    def test_setup_logging_can_skip_file_handler(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "app.log"
            logger = setup_logging(
                logger_name="test.no_file_handler",
                log_level="INFO",
                log_file=log_path,
                enable_file_logging=False,
            )
            logger.info("hello")
            self.assertFalse(log_path.exists())


class _FakeLocator:
    def __init__(self, text: str, *, count: int = 1) -> None:
        self._text = text
        self._count = count

    async def inner_text(self) -> str:
        return self._text

    async def count(self) -> int:
        return self._count


class _FakePage:
    def __init__(self, *, url: str, body_text: str) -> None:
        self.url = url
        self._body_text = body_text

    def locator(self, selector: str) -> _FakeLocator:
        if selector != "body":
            raise AssertionError(f"Unexpected selector: {selector}")
        return _FakeLocator(self._body_text)


class _FakeResponse:
    def __init__(self, status: int = 200) -> None:
        self.status = status


class _FakeDetailPage:
    def __init__(self, pages: dict[str, dict[str, str]]) -> None:
        self._pages = pages
        self.url = ""
        self.visited: list[str] = []

    async def goto(self, url: str, timeout: int | None = None) -> _FakeResponse:
        del timeout
        self.url = url
        self.visited.append(url)
        if url not in self._pages:
            raise KeyError(url)
        return _FakeResponse()

    async def wait_for_load_state(self, state: str, timeout: int | None = None) -> None:
        del state, timeout

    async def wait_for_timeout(self, timeout_ms: int) -> None:
        del timeout_ms

    def locator(self, selector: str) -> _FakeLocator:
        page = self._pages[self.url]
        if selector == "body":
            return _FakeLocator(page.get("body_text", ""))
        if selector == 'aside a[href*="/pro/"], [role="complementary"] a[href*="/pro/"], nav a[href*="/pro/"]':
            return _FakeLocator("", count=int(page.get("professional_profile_links", "0")))
        raise AssertionError(f"Unexpected selector: {selector}")

    async def content(self) -> str:
        page = self._pages[self.url]
        return page.get("html", page.get("body_text", ""))


class _CloseSpy:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class LiveFetchReviewTests(unittest.IsolatedAsyncioTestCase):
    def test_default_risk_budget_for_private_only_is_conservative(self) -> None:
        extraction = ExtractionFields(private_only_ads=True)
        budget = live_fetch._build_default_risk_budget(
            search_urls=[
                "https://www.idealista.it/affitto-case/torino/",
                "https://www.immobiliare.it/affitto-case/torino/",
            ],
            extraction=extraction,
        )

        self.assertEqual(budget.page_budget, 2)
        self.assertEqual(budget.detail_budget, live_fetch._IDEALISTA_PRIVATE_ONLY_DETAIL_MAX_CHECKS)
        self.assertEqual(budget.identity_budget, 0)
        self.assertEqual(budget.retry_budget, 1)

    def test_transient_retry_is_suppressed_when_retry_budget_is_exhausted(self) -> None:
        run_risk = live_fetch.RunRiskState(retries_used=1)
        allowed, reason = live_fetch._allow_transient_retry(
            outcome=live_fetch.FetchOutcome(tier="suspect", code="empty_suspicious", retryable=True),
            risk_budget=live_fetch.RiskBudget(
                page_budget=1,
                detail_budget=0,
                identity_budget=0,
                retry_budget=1,
                cooldown_budget=1,
                manual_assist_threshold=1,
            ),
            run_risk=run_risk,
        )

        self.assertFalse(allowed)
        self.assertEqual(reason, "retry_budget_exhausted")

    def test_cooldown_budget_sets_stop_request_when_exceeded(self) -> None:
        run_risk = live_fetch.RunRiskState(cooldown_used=1)
        exceeded = live_fetch._consume_cooldown_budget(
            outcome=live_fetch.FetchOutcome(tier="cooling", code="cooldown_active"),
            decision=live_fetch.GuardDecision(action="skip_due_cooldown"),
            risk_budget=live_fetch.RiskBudget(
                page_budget=1,
                detail_budget=0,
                identity_budget=0,
                retry_budget=1,
                cooldown_budget=1,
                manual_assist_threshold=1,
            ),
            run_risk=run_risk,
        )

        self.assertTrue(exceeded)
        self.assertTrue(run_risk.stop_requested)
        self.assertTrue(run_risk.assist_required)
        self.assertEqual(run_risk.current_state, "assist_required")
        self.assertEqual(run_risk.stop_reason, "cooldown_budget_exceeded")

    def test_remaining_detail_budget_decreases_with_consumption(self) -> None:
        budget = live_fetch.RiskBudget(
            page_budget=1,
            detail_budget=3,
            identity_budget=0,
            retry_budget=1,
            cooldown_budget=1,
            manual_assist_threshold=1,
        )
        run_risk = live_fetch.RunRiskState(detail_used=2)

        remaining = live_fetch._remaining_detail_budget(risk_budget=budget, run_risk=run_risk)

        self.assertEqual(remaining, 1)

    def test_same_site_owner_replace_becomes_suspect_then_assist_required(self) -> None:
        run_risk = live_fetch.RunRiskState()

        replace_count, owner_state = live_fetch._register_site_session_replace(
            run_risk,
            site="idealista",
            replaced_slots=1,
        )
        self.assertEqual(replace_count, 1)
        self.assertEqual(owner_state, "suspect")
        self.assertFalse(run_risk.assist_required)

        replace_count, owner_state = live_fetch._register_site_session_replace(
            run_risk,
            site="idealista",
            replaced_slots=1,
        )
        self.assertEqual(replace_count, 2)
        self.assertEqual(owner_state, "assist_required")
        self.assertTrue(run_risk.assist_required)
        self.assertEqual(run_risk.assist_reason, "same_site_owner_churn")


    def test_run_state_escalates_to_assist_required_after_repeated_degraded(self) -> None:
        entry = live_fetch._new_guard_site_entry()
        run_risk = live_fetch.RunRiskState()
        outcome = live_fetch.FetchOutcome(tier="degraded", code="parse_issue")
        decision = live_fetch.GuardDecision(action="observe_degraded")

        previous_state, current_state = live_fetch._advance_run_state(
            entry=entry,
            outcome=outcome,
            decision=decision,
            run_risk=run_risk,
        )
        self.assertEqual(previous_state, "warmup")
        self.assertEqual(current_state, "degraded")
        self.assertFalse(run_risk.assist_required)

        previous_state, current_state = live_fetch._advance_run_state(
            entry=entry,
            outcome=outcome,
            decision=decision,
            run_risk=run_risk,
        )
        self.assertEqual(previous_state, "degraded")
        self.assertEqual(current_state, "assist_required")
        self.assertTrue(run_risk.assist_required)
        self.assertEqual(run_risk.assist_reason, "persistent_degraded")

    def test_run_state_escalates_to_assist_required_after_repeated_challenge(self) -> None:
        entry = live_fetch._new_guard_site_entry()
        run_risk = live_fetch.RunRiskState()
        outcome = live_fetch.FetchOutcome(
            tier="blocked",
            code="interstitial_datadome",
            challenge_visible=True,
        )
        decision = live_fetch.GuardDecision(action="apply_cooldown_block", cooldown_sec=300)

        live_fetch._advance_run_state(
            entry=entry,
            outcome=outcome,
            decision=decision,
            run_risk=run_risk,
        )
        self.assertEqual(run_risk.current_state, "challenge_seen")
        self.assertFalse(run_risk.assist_required)

        live_fetch._advance_run_state(
            entry=entry,
            outcome=outcome,
            decision=decision,
            run_risk=run_risk,
        )
        self.assertEqual(run_risk.current_state, "assist_required")
        self.assertTrue(run_risk.assist_required)
        self.assertEqual(run_risk.assist_reason, "challenge_repeat")

    def test_telemetry_snapshot_marks_interstitial_as_challenge_seen(self) -> None:
        entry = live_fetch._new_guard_site_entry()
        entry["last_attempt_channel"] = "chrome"
        entry["warmup_started_utc"] = datetime(2026, 3, 25, 9, 0, tzinfo=timezone.utc).isoformat()
        outcome = live_fetch.FetchOutcome(
            tier="blocked",
            code="interstitial_datadome",
            challenge_visible=True,
        )
        decision = live_fetch.GuardDecision(action="apply_cooldown_block", cooldown_sec=600)

        snapshot = live_fetch._build_telemetry_snapshot(
            site="idealista",
            entry=entry,
            outcome=outcome,
            decision=decision,
            now=datetime(2026, 3, 25, 9, 5, tzinfo=timezone.utc),
            browser_mode="managed_stable",
            channel_label="chrome",
            identity_switch=0,
            attempt_stats=live_fetch.FetchAttemptStats(),
            manual_assist_used=False,
        )

        self.assertEqual(snapshot.state_transition, "challenge_seen")
        self.assertEqual(snapshot.risk_pause_reason, "challenge_seen_first")

    def test_telemetry_snapshot_tracks_profile_generation_and_profile_age(self) -> None:
        now = datetime(2026, 3, 27, 12, 0, tzinfo=timezone.utc)
        entry = live_fetch._new_guard_site_entry()
        entry["last_attempt_channel"] = "camoufox"
        entry["profile_generation"] = 2
        entry["cooldown_profile_generation"] = 1
        entry["profile_created_utc"] = (now - timedelta(minutes=10)).isoformat()
        entry["last_success_utc"] = (now - timedelta(minutes=25)).isoformat()
        outcome = live_fetch.FetchOutcome(tier="blocked", code="hard_block", hard_block=True)
        decision = live_fetch.GuardDecision(action="apply_cooldown_block", cooldown_sec=1800)

        snapshot = live_fetch._build_telemetry_snapshot(
            site="immobiliare",
            entry=entry,
            outcome=outcome,
            decision=decision,
            now=now,
            browser_mode="managed_stable",
            channel_label="camoufox",
            identity_switch=0,
            attempt_stats=live_fetch.FetchAttemptStats(),
            manual_assist_used=False,
        )

        self.assertEqual(snapshot.profile_generation, 2)
        self.assertEqual(snapshot.cooldown_profile_generation, 1)
        self.assertEqual(snapshot.profile_age_sec, 600)
        self.assertEqual(snapshot.session_age_sec, 1500)

    def test_log_guard_decision_reports_reactive_profile_rotation(self) -> None:
        now = datetime(2026, 3, 27, 12, 0, tzinfo=timezone.utc)
        state = {"sites": {"immobiliare": live_fetch._new_guard_site_entry()}}
        entry = state["sites"]["immobiliare"]
        entry["warmup_active"] = False
        entry["profile_created_utc"] = (now - timedelta(hours=2)).isoformat()
        entry["last_success_utc"] = (now - timedelta(minutes=25)).isoformat()
        outcome = live_fetch.FetchOutcome(tier="blocked", code="hard_block", hard_block=True)
        decision = live_fetch._apply_guard_outcome(
            state=state,
            site="immobiliare",
            outcome=outcome,
            now=now,
            base_sec=1800,
            max_sec=3600,
            channel_label="camoufox",
        )
        entry = state["sites"]["immobiliare"]
        stream = io.StringIO()
        logger = logging.getLogger("test.live_fetch.guard_logging.rotation")
        logger.handlers.clear()
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        logger.propagate = False
        logger.setLevel(logging.INFO)

        try:
            live_fetch._log_guard_decision(
                logger=logger,
                site="immobiliare",
                url="https://www.immobiliare.it/search-list/test",
                outcome=outcome,
                decision=decision,
                entry=entry,
                browser_mode="managed_stable",
                identity_switch=0,
                attempt_stats=live_fetch.FetchAttemptStats(),
                manual_assist_used=False,
            )
        finally:
            logger.handlers.clear()

        content = stream.getvalue()
        self.assertIn("Profile identity rotated. site=immobiliare", content)
        self.assertIn("previous_generation=0", content)
        self.assertIn("next_generation=1", content)
        self.assertIn("profile_generation=1", content)
        self.assertIn("cooldown_generation=0", content)
    def test_idealista_selectors_cover_pro_logo_alt(self) -> None:
        self.assertIn('a[href*="/pro/"] img[alt]', live_fetch._IDEALISTA_AGENCY_ATTR_SELECTORS)

    def test_interstitial_auto_wait_is_more_patient_for_idealista(self) -> None:
        interstitial_wait = live_fetch._challenge_auto_wait_sec(
            site="idealista",
            captcha_wait_sec=20,
            flow_code="interstitial_datadome",
        )
        challenge_wait = live_fetch._challenge_auto_wait_sec(
            site="idealista",
            captcha_wait_sec=20,
            flow_code="challenge_visible",
        )
        self.assertGreater(interstitial_wait, challenge_wait)
        self.assertEqual(interstitial_wait, 12)

    async def test_interstitial_waits_before_skipping_when_headed(self) -> None:
        page = _FakePage(
            url="https://www.idealista.it/aree/affitto-case/test",
            body_text="geo.captcha-delivery.com/interstitial verify you are a human",
        )
        with mock.patch.object(live_fetch, "_has_listing_signals", mock.AsyncMock(return_value=False)), mock.patch.object(
            live_fetch,
            "_is_hard_block_page",
            mock.AsyncMock(return_value=(False, "")),
        ), mock.patch.object(
            live_fetch,
            "_wait_until_verification_cleared",
            mock.AsyncMock(return_value=True),
        ) as wait_mock:
            can_continue, code = await live_fetch._resolve_captcha_flow(
                page=page,
                search_url="https://www.idealista.it/aree/affitto-case/test",
                site="idealista",
                captcha_mode="skip_and_notify",
                captcha_wait_sec=20,
                headless=False,
                logger=_build_logger("test.live_fetch.interstitial"),
                phase="after_goto",
                html="geo.captcha-delivery.com/interstitial",
            )

        self.assertTrue(can_continue)
        self.assertEqual(code, "ok")
        wait_mock.assert_awaited_once()
        self.assertEqual(wait_mock.await_args.kwargs["site"], "idealista")
        self.assertEqual(wait_mock.await_args.kwargs["timeout_sec"], 12)

    async def test_interstitial_wait_does_not_clear_while_interstitial_url_remains(self) -> None:
        page = _FakePage(
            url="https://geo.captcha-delivery.com/interstitial/?token=1",
            body_text="generic page body",
        )
        with mock.patch.object(live_fetch, "_has_listing_signals", mock.AsyncMock(return_value=False)), mock.patch.object(
            live_fetch,
            "_is_hard_block_page",
            mock.AsyncMock(return_value=(False, "")),
        ), mock.patch.object(
            live_fetch,
            "_is_likely_captcha",
            mock.AsyncMock(return_value=False),
        ), mock.patch("src.affitto_v2.scrapers.live_fetch.asyncio.sleep", mock.AsyncMock()):
            cleared = await live_fetch._wait_until_verification_cleared(
                page,
                site="immobiliare",
                timeout_sec=2,
                logger=_build_logger("test.live_fetch.interstitial.not_cleared"),
            )

        self.assertFalse(cleared)

    def test_interstitial_probe_becomes_due_only_after_scheduled_time(self) -> None:
        now = datetime(2026, 3, 24, 22, 51, tzinfo=timezone.utc)
        entry = live_fetch._new_guard_site_entry()
        entry["last_block_family"] = "interstitial"
        entry["probe_after_utc"] = (now + timedelta(minutes=10)).isoformat()

        self.assertFalse(live_fetch._is_interstitial_probe_due(entry, now))
        self.assertTrue(live_fetch._is_interstitial_probe_due(entry, now + timedelta(minutes=10)))

    def test_idealista_private_only_db_cache_reuses_known_records(self) -> None:
        cards = [
            {"ad_id": "a1", "url": "https://www.idealista.it/immobile/a1/", "agency": ""},
            {"ad_id": "a2", "url": "https://www.idealista.it/immobile/a2/", "agency": ""},
            {"ad_id": "a3", "url": "https://www.idealista.it/immobile/a3/", "agency": "Agency on label"},
        ]
        db = mock.Mock()
        db.get_listing_agencies_by_ad_ids.return_value = {"a1": "Professionista (detail check)", "a2": ""}

        live_fetch._apply_idealista_private_only_db_cache(
            db=db,
            search_url="https://www.idealista.it/aree/test",
            cards=cards,
            logger=_build_logger("test.live_fetch.private_only.db_cache"),
        )

        self.assertEqual(cards[0]["agency"], "Professionista (detail check)")
        self.assertTrue(cards[0]["_private_only_db_cached"])
        self.assertEqual(cards[1]["agency"], "")
        self.assertTrue(cards[1]["_private_only_db_cached"])
        self.assertNotIn("_private_only_db_cached", cards[2])

    def test_idealista_private_only_db_cache_reuses_professionals_saved_outside_listings(self) -> None:
        cards = [
            {"ad_id": "a1", "url": "https://www.idealista.it/immobile/a1/", "agency": ""},
            {"ad_id": "a2", "url": "https://www.idealista.it/immobile/a2/", "agency": ""},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "private_only_cache.db")
            db.init_schema()
            db.upsert_private_only_agency(
                site="idealista",
                search_url="https://www.idealista.it/aree/test",
                ad_id="a1",
                agency="Professionista (detail check)",
                source="unit_test",
            )

            live_fetch._apply_idealista_private_only_db_cache(
                db=db,
                search_url="https://www.idealista.it/aree/test",
                cards=cards,
                logger=_build_logger("test.live_fetch.private_only.db_cache.professional_memory"),
            )

        self.assertEqual(cards[0]["agency"], "Professionista (detail check)")
        self.assertTrue(cards[0]["_private_only_db_cached"])
        self.assertEqual(cards[1]["agency"], "")

    def test_resolve_channel_executable_path_uses_installed_browser(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            camoufox_path = Path(tmpdir) / "camoufox.exe"
            camoufox_path.write_text("", encoding="utf-8")
            with mock.patch.object(live_fetch, "camoufox_launch_path", return_value=str(camoufox_path)):
                resolved = live_fetch._resolve_channel_executable_path("camoufox")

        self.assertEqual(resolved, camoufox_path)

    def test_camoufox_launch_kwargs_match_italian_windows_profile(self) -> None:
        launch_kwargs = live_fetch._camoufox_launch_kwargs(
            headless=True,
            executable_path=Path("C:/camoufox/camoufox.exe"),
            persistent_profile_dir=Path("C:/runtime/camoufox-profile/idealista/camoufox"),
        )

        self.assertTrue(launch_kwargs["headless"])
        self.assertTrue(launch_kwargs["humanize"])
        self.assertEqual(launch_kwargs["locale"], "it-IT")
        self.assertEqual(launch_kwargs["os"], "windows")
        self.assertEqual(launch_kwargs["config"], {"timezone": "Europe/Rome"})
        self.assertEqual(Path(str(launch_kwargs["user_data_dir"])), Path("C:/runtime/camoufox-profile/idealista/camoufox"))
        self.assertEqual(Path(str(launch_kwargs["executable_path"])), Path("C:/camoufox/camoufox.exe"))
        self.assertTrue(launch_kwargs["persistent_context"])
        self.assertTrue(launch_kwargs["i_know_what_im_doing"])
        screen = launch_kwargs["screen"]
        self.assertEqual(screen.min_width, 1920)
        self.assertEqual(screen.max_width, 1920)
        self.assertEqual(screen.min_height, 1080)
        self.assertEqual(screen.max_height, 1080)

    def test_profile_dir_for_site_channel_isolates_site_and_channel(self) -> None:
        base = Path("C:/runtime/browser-profile")

        profile_path = live_fetch._profile_dir_for_site_channel(base, "idealista", "camoufox")

        self.assertEqual(profile_path, Path("C:/runtime/browser-profile/idealista/camoufox"))

    def test_profile_dir_for_site_channel_appends_generation_when_rotated(self) -> None:
        base = Path("C:/runtime/browser-profile")

        profile_path = live_fetch._profile_dir_for_site_channel(
            base,
            "immobiliare",
            "camoufox",
            profile_generation=2,
        )

        self.assertEqual(profile_path, Path("C:/runtime/browser-profile/immobiliare/gen-002/camoufox"))

    def test_load_or_create_camoufox_persona_is_stable_for_same_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_root = Path(tmpdir) / "immobiliare" / "gen-000" / "camoufox"
            profile_root.mkdir(parents=True, exist_ok=True)
            logger = _build_logger("test.live_fetch.camoufox_persona.same_generation")

            persona_a = live_fetch._load_or_create_camoufox_persona(
                site="immobiliare",
                channel_label="camoufox",
                profile_generation=0,
                profile_root=profile_root,
                executable_path=Path("C:/camoufox/camoufox.exe"),
                logger=logger,
            )
            persona_b = live_fetch._load_or_create_camoufox_persona(
                site="immobiliare",
                channel_label="camoufox",
                profile_generation=0,
                profile_root=profile_root,
                executable_path=Path("C:/camoufox/camoufox.exe"),
                logger=logger,
            )

        self.assertEqual(persona_a.persona_id, persona_b.persona_id)
        self.assertEqual(persona_a.seed, persona_b.seed)
        self.assertEqual(persona_a.screen_width, persona_b.screen_width)
        self.assertEqual(persona_a.window_width, persona_b.window_width)
        self.assertEqual(persona_a.humanize_max_sec, persona_b.humanize_max_sec)

    def test_load_or_create_camoufox_persona_changes_across_generations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = _build_logger("test.live_fetch.camoufox_persona.cross_generation")
            root_a = Path(tmpdir) / "idealista" / "camoufox"
            root_b = Path(tmpdir) / "idealista" / "gen-001" / "camoufox"
            root_a.mkdir(parents=True, exist_ok=True)
            root_b.mkdir(parents=True, exist_ok=True)

            persona_a = live_fetch._load_or_create_camoufox_persona(
                site="idealista",
                channel_label="camoufox",
                profile_generation=0,
                profile_root=root_a,
                executable_path=Path("C:/camoufox/camoufox.exe"),
                logger=logger,
            )
            persona_b = live_fetch._load_or_create_camoufox_persona(
                site="idealista",
                channel_label="camoufox",
                profile_generation=1,
                profile_root=root_b,
                executable_path=Path("C:/camoufox/camoufox.exe"),
                logger=logger,
            )

        self.assertNotEqual(persona_a.persona_id, persona_b.persona_id)
        self.assertNotEqual(persona_a.seed, persona_b.seed)
        self.assertNotEqual(persona_a.profile_generation, persona_b.profile_generation)

    def test_camoufox_launch_kwargs_use_persona_template_when_available(self) -> None:
        persona = live_fetch.CamoufoxPersona(
            version=1,
            persona_id="immobiliare-camoufox-g000-1234",
            seed=1234,
            site="immobiliare",
            channel_label="camoufox",
            profile_generation=0,
            created_utc="2026-03-27T12:00:00+00:00",
            screen_label="desktop_fhd",
            screen_width=1920,
            screen_height=1080,
            window_width=1760,
            window_height=990,
            humanize_max_sec=1.2,
            history_length=4,
            font_spacing_seed=123456,
            canvas_aa_offset=7,
            launch_options={
                "executable_path": "C:/camoufox/old.exe",
                "args": ["--persona"],
                "env": {"A": "1"},
                "firefox_user_prefs": {"pref.one": True},
                "proxy": None,
                "headless": False,
            },
        )

        launch_kwargs = live_fetch._camoufox_launch_kwargs(
            headless=True,
            executable_path=Path("C:/camoufox/current.exe"),
            persistent_profile_dir=Path("C:/runtime/camoufox-profile/immobiliare/camoufox"),
            persona=persona,
        )

        self.assertTrue(launch_kwargs["headless"])
        self.assertEqual(launch_kwargs["args"], ["--persona"])
        self.assertEqual(launch_kwargs["env"], {"A": "1"})
        self.assertEqual(launch_kwargs["firefox_user_prefs"], {"pref.one": True})
        self.assertEqual(Path(str(launch_kwargs["user_data_dir"])), Path("C:/runtime/camoufox-profile/immobiliare/camoufox"))
        self.assertEqual(Path(str(launch_kwargs["executable_path"])), Path("C:/camoufox/current.exe"))
        self.assertTrue(launch_kwargs["persistent_context"])

    def test_session_owner_key_includes_site_channel_and_profile(self) -> None:
        owner = live_fetch._session_owner_key(
            site="immobiliare",
            channel_label="camoufox",
            profile_root=Path("C:/runtime/browser-profile/immobiliare/camoufox"),
        )

        self.assertIn("immobiliare", owner)
        self.assertIn("camoufox", owner)
        self.assertIn("browser-profile/immobiliare/camoufox", owner.replace("\\", "/"))

    def test_session_identity_changes_between_sites(self) -> None:
        idealista_owner, idealista_root = live_fetch._session_identity(
            site="idealista",
            channel_label="camoufox",
            profile_dir="C:/runtime/browser-profile",
        )
        immobiliare_owner, immobiliare_root = live_fetch._session_identity(
            site="immobiliare",
            channel_label="camoufox",
            profile_dir="C:/runtime/browser-profile",
        )

        self.assertNotEqual(idealista_owner, immobiliare_owner)
        self.assertNotEqual(idealista_root, immobiliare_root)
        self.assertIn("idealista", str(idealista_root).replace("\\", "/"))
        self.assertIn("immobiliare", str(immobiliare_root).replace("\\", "/"))

    def test_session_identity_includes_profile_generation(self) -> None:
        owner, profile_root = live_fetch._session_identity(
            site="immobiliare",
            channel_label="camoufox",
            profile_dir="C:/runtime/browser-profile",
            profile_generation=3,
        )

        self.assertIn("gen-003", str(profile_root).replace("\\", "/"))
        self.assertIn("gen-003", owner.replace("\\", "/"))

    def test_maybe_rotate_site_profile_applies_preventive_rotation_only_to_immobiliare(self) -> None:
        state = {"sites": {"immobiliare": live_fetch._new_guard_site_entry(), "idealista": live_fetch._new_guard_site_entry()}}
        now = datetime(2026, 3, 27, 12, 0, tzinfo=timezone.utc)
        state["sites"]["immobiliare"]["profile_created_utc"] = (now - timedelta(hours=25)).isoformat()
        state["sites"]["idealista"]["profile_created_utc"] = (now - timedelta(hours=25)).isoformat()

        immobiliare_changed = live_fetch._maybe_rotate_site_profile(
            state=state,
            site="immobiliare",
            now=now,
            logger=_build_logger("test.live_fetch.profile_rotate.immobiliare"),
        )
        idealista_changed = live_fetch._maybe_rotate_site_profile(
            state=state,
            site="idealista",
            now=now,
            logger=_build_logger("test.live_fetch.profile_rotate.idealista"),
        )

        self.assertTrue(immobiliare_changed)
        self.assertEqual(state["sites"]["immobiliare"]["profile_generation"], 1)
        self.assertEqual(state["sites"]["immobiliare"]["profile_quarantine_reason"], "profile_age_cap")
        self.assertFalse(idealista_changed)
        self.assertEqual(state["sites"]["idealista"]["profile_generation"], 0)

    def test_apply_guard_outcome_rotates_profile_on_hard_block_for_idealista_and_immobiliare(self) -> None:
        now = datetime(2026, 3, 27, 12, 0, tzinfo=timezone.utc)
        outcome = live_fetch.FetchOutcome(tier="blocked", code="hard_block", hard_block=True)

        for site in ("idealista", "immobiliare"):
            state = {"sites": {site: live_fetch._new_guard_site_entry()}}
            state["sites"][site]["warmup_active"] = False
            state["sites"][site]["profile_created_utc"] = (now - timedelta(hours=2)).isoformat()

            decision = live_fetch._apply_guard_outcome(
                state=state,
                site=site,
                outcome=outcome,
                now=now,
                base_sec=1800,
                max_sec=3600,
                channel_label="camoufox",
            )

            entry = state["sites"][site]
            self.assertEqual(decision.action, "apply_cooldown_block")
            self.assertEqual(entry["profile_generation"], 1)
            self.assertEqual(entry["cooldown_profile_generation"], 0)
            self.assertEqual(entry["profile_quarantine_reason"], "hard_block:hard_block")

    def test_cooldown_remaining_sec_is_bypassed_for_rotated_profile_generation(self) -> None:
        now = datetime(2026, 3, 27, 12, 0, tzinfo=timezone.utc)
        state = {"sites": {"immobiliare": live_fetch._new_guard_site_entry()}}
        entry = state["sites"]["immobiliare"]
        entry["profile_generation"] = 1
        entry["cooldown_profile_generation"] = 0
        entry["cooldown_until_utc"] = (now + timedelta(minutes=30)).isoformat()

        remaining = live_fetch._cooldown_remaining_sec(state, "immobiliare", now)

        self.assertEqual(remaining, 0)

    def test_cooldown_remaining_sec_applies_to_current_profile_generation(self) -> None:
        now = datetime(2026, 3, 27, 12, 0, tzinfo=timezone.utc)
        state = {"sites": {"immobiliare": live_fetch._new_guard_site_entry()}}
        entry = state["sites"]["immobiliare"]
        entry["profile_generation"] = 1
        entry["cooldown_profile_generation"] = 1
        entry["cooldown_until_utc"] = (now + timedelta(minutes=30)).isoformat()

        remaining = live_fetch._cooldown_remaining_sec(state, "immobiliare", now)

        self.assertGreater(remaining, 0)

    def test_reset_site_guard_state_seeds_profile_rotation_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "site_guard_state.json"
            logger = _build_logger("test.main.reset_site_guard_state")

            app_main._reset_site_guard_state(
                path,
                [
                    "https://www.immobiliare.it/affitto-case/torino/",
                    "https://www.idealista.it/affitto-case/torino/",
                ],
                logger,
            )

            payload = live_fetch._load_guard_state(path)

        self.assertEqual(payload["version"], 7)
        self.assertEqual(payload["sites"]["immobiliare"]["profile_generation"], 0)
        self.assertEqual(payload["sites"]["immobiliare"]["cooldown_profile_generation"], "")
        self.assertEqual(payload["sites"]["idealista"]["profile_created_utc"], "")

    async def test_prune_site_session_slots_closes_same_site_owners_only(self) -> None:
        keep_slot = live_fetch.BrowserSessionSlot(
            owner_key="idealista|chrome|one",
            site="idealista",
            channel_label="chrome",
            profile_root="one",
            browser=_CloseSpy(),
            context=_CloseSpy(),
            page=object(),
        )
        prune_slot = live_fetch.BrowserSessionSlot(
            owner_key="idealista|msedge|two",
            site="idealista",
            channel_label="msedge",
            profile_root="two",
            browser=_CloseSpy(),
            context=_CloseSpy(),
            page=object(),
        )
        other_site_slot = live_fetch.BrowserSessionSlot(
            owner_key="immobiliare|chrome|three",
            site="immobiliare",
            channel_label="chrome",
            profile_root="three",
            browser=_CloseSpy(),
            context=_CloseSpy(),
            page=object(),
        )
        slots = {
            keep_slot.owner_key: keep_slot,
            prune_slot.owner_key: prune_slot,
            other_site_slot.owner_key: other_site_slot,
        }

        removed = await live_fetch._prune_site_session_slots(
            slots,
            site="idealista",
            preserve_owner=keep_slot.owner_key,
        )

        self.assertEqual(removed, 1)
        self.assertIn(keep_slot.owner_key, slots)
        self.assertNotIn(prune_slot.owner_key, slots)
        self.assertIn(other_site_slot.owner_key, slots)
        self.assertTrue(prune_slot.browser.closed)
        self.assertTrue(prune_slot.context.closed)
        self.assertFalse(keep_slot.browser.closed)

    def test_normalize_browser_channel_accepts_only_auto_and_camoufox(self) -> None:
        self.assertIsNone(live_fetch._normalize_browser_channel("auto"))
        self.assertEqual(live_fetch._normalize_browser_channel("camoufox"), "camoufox")
        with self.assertRaisesRegex(ValueError, "auto\\|camoufox"):
            live_fetch._normalize_browser_channel("chrome")

    def test_classify_idealista_publisher_kind(self) -> None:
        private_body = "Persona che pubblica l'annuncio Privato Daniele Contatta l'inserzionista"
        professional_body = (
            "Persona che pubblica l'annuncio Professionista "
            "STUDIO PECETTO S.A.S. DI ROBERTO GIUSTO & C."
        )

        self.assertEqual(live_fetch._classify_idealista_publisher_kind(private_body), "privato")
        self.assertEqual(live_fetch._classify_idealista_publisher_kind(professional_body), "professionista")
        self.assertEqual(
            live_fetch._classify_idealista_publisher_kind_from_signals(
                body_text="Pagina senza label esplicite",
                has_professional_profile_link=True,
            ),
            "professionista",
        )

    async def test_detail_verification_flags_professionals_for_private_only(self) -> None:
        cards = [
            {
                "site": "idealista",
                "url": "https://www.idealista.it/immobile/1/",
                "ad_id": "1",
                "title": "Annuncio privato",
                "agency": "",
            },
            {
                "site": "idealista",
                "url": "https://www.idealista.it/immobile/2/",
                "ad_id": "2",
                "title": "Annuncio professionale",
                "agency": "",
            },
        ]
        page = _FakeDetailPage(
            {
                "https://www.idealista.it/immobile/1/": {
                    "body_text": "Persona che pubblica l'annuncio Privato Daniele",
                },
                "https://www.idealista.it/immobile/2/": {
                    "body_text": "Pagina renderizzata senza label utile",
                    "professional_profile_links": "1",
                },
            }
        )

        with mock.patch.object(live_fetch, "_accept_cookies_if_present", mock.AsyncMock()), mock.patch.object(
            live_fetch,
            "_dismiss_intrusive_popups",
            mock.AsyncMock(),
        ), mock.patch.object(
            live_fetch,
            "_is_likely_captcha",
            mock.AsyncMock(return_value=False),
        ):
            attempted = await live_fetch._verify_idealista_private_only_candidates(
                page=page,
                cards=cards,
                nav_timeout_ms=5000,
                detail_budget_remaining=1,
                logger=_build_logger("test.live_fetch.detail_verify"),
            )

        self.assertEqual(attempted, 1)
        self.assertEqual(cards[0]["agency"], "")
        self.assertEqual(cards[1]["agency"], "")
        self.assertEqual(page.visited, [cards[0]["url"]])

    async def test_detail_verification_skips_db_cached_cards(self) -> None:
        cards = [
            {
                "site": "idealista",
                "url": "https://www.idealista.it/immobile/1/",
                "ad_id": "1",
                "title": "Gia in cache",
                "agency": "",
                "_private_only_db_cached": True,
            },
            {
                "site": "idealista",
                "url": "https://www.idealista.it/immobile/2/",
                "ad_id": "2",
                "title": "Da verificare",
                "agency": "",
            },
        ]
        page = _FakeDetailPage(
            {
                "https://www.idealista.it/immobile/2/": {
                    "body_text": "Persona che pubblica l'annuncio Privato Marta",
                },
            }
        )

        with mock.patch.object(live_fetch, "_accept_cookies_if_present", mock.AsyncMock()), mock.patch.object(
            live_fetch,
            "_dismiss_intrusive_popups",
            mock.AsyncMock(),
        ), mock.patch.object(
            live_fetch,
            "_is_likely_captcha",
            mock.AsyncMock(return_value=False),
        ):
            attempted = await live_fetch._verify_idealista_private_only_candidates(
                page=page,
                cards=cards,
                nav_timeout_ms=5000,
                logger=_build_logger("test.live_fetch.detail_verify.skip_cached"),
            )

        self.assertEqual(attempted, 1)
        self.assertEqual(page.visited, [cards[1]["url"]])

    async def test_detail_verification_returns_zero_when_no_candidates_remain(self) -> None:
        cards = [
            {
                "site": "idealista",
                "url": "https://www.idealista.it/immobile/1/",
                "ad_id": "1",
                "title": "Gia classificato",
                "agency": "Professionista (detail check)",
            },
            {
                "site": "idealista",
                "url": "https://www.idealista.it/immobile/2/",
                "ad_id": "2",
                "title": "Gia in cache",
                "agency": "",
                "_private_only_db_cached": True,
            },
        ]
        page = _FakeDetailPage({})

        attempted = await live_fetch._verify_idealista_private_only_candidates(
            page=page,
            cards=cards,
            nav_timeout_ms=5000,
            logger=_build_logger("test.live_fetch.detail_verify.no_candidates"),
        )

        self.assertEqual(attempted, 0)
        self.assertEqual(page.visited, [])

    def test_coerce_detail_touch_count_keeps_int_without_warning(self) -> None:
        logger = _build_logger("test.live_fetch.detail_touch_count.int")

        with mock.patch.object(logger, "warning") as warning_mock:
            detail_touch_count = live_fetch._coerce_detail_touch_count(
                value=3,
                site="idealista",
                logger=logger,
            )

        self.assertEqual(detail_touch_count, 3)
        warning_mock.assert_not_called()

    def test_coerce_detail_touch_count_warns_and_coerces_none(self) -> None:
        logger = _build_logger("test.live_fetch.detail_touch_count.none")

        with mock.patch.object(logger, "warning") as warning_mock:
            detail_touch_count = live_fetch._coerce_detail_touch_count(
                value=None,
                site="idealista",
                logger=logger,
            )

        self.assertEqual(detail_touch_count, 0)
        warning_mock.assert_called_once()
        self.assertIn("Non-integer detail touch count returned", warning_mock.call_args.args[0])

    async def test_detail_verification_persists_professional_memory(self) -> None:
        cards = [
            {
                "site": "idealista",
                "url": "https://www.idealista.it/immobile/2/",
                "ad_id": "2",
                "title": "Annuncio professionale",
                "agency": "",
            },
        ]
        page = _FakeDetailPage(
            {
                "https://www.idealista.it/immobile/2/": {
                    "body_text": "Pagina renderizzata senza label utile",
                    "professional_profile_links": "1",
                },
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "detail_verify_memory.db")
            db.init_schema()
            with mock.patch.object(live_fetch, "_accept_cookies_if_present", mock.AsyncMock()), mock.patch.object(
                live_fetch,
                "_dismiss_intrusive_popups",
                mock.AsyncMock(),
            ), mock.patch.object(
                live_fetch,
                "_is_likely_captcha",
                mock.AsyncMock(return_value=False),
            ):
                attempted = await live_fetch._verify_idealista_private_only_candidates(
                    page=page,
                    cards=cards,
                    nav_timeout_ms=5000,
                    db=db,
                    search_url="https://www.idealista.it/aree/test",
                    logger=_build_logger("test.live_fetch.detail_verify.persist_memory"),
                )
            cached = db.get_listing_agencies_by_ad_ids(
                site="idealista",
                search_url="https://www.idealista.it/aree/test",
                ad_ids=["2"],
            )

        self.assertEqual(attempted, 1)
        self.assertEqual(cards[0]["agency"], "Professionista (detail check)")
        self.assertEqual(cached, {"2": "Professionista (detail check)"})


class LiveServiceSchedulingTests(unittest.TestCase):
    def _build_service_args(self, **overrides) -> SimpleNamespace:
        data = {
            "cycle_max_minutes": 10,
            "max_cycles": 0,
            "override_cycle_minutes": 0,
            "save_overrides": False,
            "service_stop_flag": "",
        }
        data.update(overrides)
        return SimpleNamespace(**data)

    def test_build_live_service_policy_uses_runtime_cadence(self) -> None:
        config = _build_config(private_only_ads=False)
        policy = app_main._build_live_service_policy(config, self._build_service_args(max_cycles=3))

        self.assertEqual(policy.cadence_sec, 300)
        self.assertEqual(policy.max_cycle_sec, 600)
        self.assertEqual(policy.max_cycles, 3)
        self.assertTrue(policy.restart_on_failure)

    def test_sleep_until_next_cycle_or_stop_returns_true_when_flag_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stop_flag = Path(tmpdir) / "live_service.stop"
            stop_flag.write_text("stop\n", encoding="utf-8")

            stop_requested = app_main._sleep_until_next_cycle_or_stop(
                sleep_sec=30.0,
                stop_flag_path=stop_flag,
                monotonic_fn=lambda: 0.0,
                sleep_fn=lambda _: None,
            )

        self.assertTrue(stop_requested)

    def test_build_live_service_policy_rejects_threshold_lower_than_cadence(self) -> None:
        config = _build_config(private_only_ads=False)
        config.runtime.cycle_minutes = 6

        with self.assertRaisesRegex(Exception, "cycle_max_minutes cannot be lower than cycle_minutes"):
            app_main._build_live_service_policy(config, self._build_service_args(cycle_max_minutes=5))

    def test_count_missed_cycle_slots_returns_zero_when_cycle_finishes_inside_window(self) -> None:
        missed = app_main._count_missed_cycle_slots(
            cycle_started_monotonic=100.0,
            cycle_finished_monotonic=399.0,
            cadence_sec=300,
        )

        self.assertEqual(missed, 0)

    def test_count_missed_cycle_slots_counts_all_crossed_boundaries(self) -> None:
        missed = app_main._count_missed_cycle_slots(
            cycle_started_monotonic=100.0,
            cycle_finished_monotonic=710.0,
            cadence_sec=300,
        )

        self.assertEqual(missed, 2)

    def test_live_service_state_becomes_stable_after_clean_cycle(self) -> None:
        service_state = app_main.LiveServiceState()

        previous_state, current_state = app_main._advance_live_service_state(
            service_state=service_state,
            cycle_failed=False,
            cycle_overrun=False,
            missed_slots=0,
        )

        self.assertEqual(previous_state, "warmup")
        self.assertEqual(current_state, "stable")
        self.assertFalse(service_state.assist_required)

    def test_live_service_state_requires_assistance_after_repeated_failures(self) -> None:
        service_state = app_main.LiveServiceState()

        app_main._advance_live_service_state(
            service_state=service_state,
            cycle_failed=True,
            cycle_overrun=False,
            missed_slots=0,
        )
        previous_state, current_state = app_main._advance_live_service_state(
            service_state=service_state,
            cycle_failed=True,
            cycle_overrun=False,
            missed_slots=0,
        )

        self.assertEqual(previous_state, "degraded")
        self.assertEqual(current_state, "assist_required")
        self.assertTrue(service_state.assist_required)
        self.assertEqual(service_state.assist_reason, "repeated_cycle_failures")

    def test_live_service_state_requires_assistance_when_run_requires_it(self) -> None:
        service_state = app_main.LiveServiceState()

        previous_state, current_state = app_main._advance_live_service_state(
            service_state=service_state,
            cycle_failed=False,
            cycle_overrun=False,
            missed_slots=0,
            run_state="assist_required",
            run_assist_required=True,
            run_assist_reason="challenge_repeat",
            run_stop_requested=True,
        )

        self.assertEqual(previous_state, "warmup")
        self.assertEqual(current_state, "assist_required")
        self.assertTrue(service_state.assist_required)
        self.assertEqual(service_state.assist_reason, "challenge_repeat")

    def test_live_service_state_tracks_repeated_run_degraded_without_forcing_assist(self) -> None:
        service_state = app_main.LiveServiceState()

        app_main._advance_live_service_state(
            service_state=service_state,
            cycle_failed=False,
            cycle_overrun=False,
            missed_slots=0,
            run_state="degraded",
            run_assist_required=False,
            run_assist_reason="",
            run_stop_requested=False,
        )
        previous_state, current_state = app_main._advance_live_service_state(
            service_state=service_state,
            cycle_failed=False,
            cycle_overrun=False,
            missed_slots=0,
            run_state="cooldown",
            run_assist_required=False,
            run_assist_reason="",
            run_stop_requested=True,
        )

        self.assertEqual(previous_state, "degraded")
        self.assertEqual(current_state, "degraded")
        self.assertFalse(service_state.assist_required)
        self.assertEqual(service_state.consecutive_run_degraded_cycles, 2)

    def test_runtime_disposition_recycles_site_slot_on_cooldown(self) -> None:
        report = live_fetch.LiveFetchRunReport(
            listings=[],
            run_state="cooldown",
            run_state_site="idealista",
            assist_required=False,
            assist_reason="",
            stop_requested=True,
            stop_reason="cooldown_active",
        )

        decision = app_main._decide_runtime_disposition(
            cycle_failed=False,
            cycle_report=report,
            service_state=app_main.LiveServiceState(),
        )

        self.assertEqual(decision.action, "recycle_site_slot")
        self.assertEqual(decision.site, "idealista")

    def test_runtime_disposition_recycles_single_blocked_site_even_when_run_state_is_stable(self) -> None:
        report = live_fetch.LiveFetchRunReport(
            listings=[],
            run_state="stable",
            run_state_site="immobiliare",
            assist_required=False,
            assist_reason="",
            stop_requested=False,
            stop_reason="",
            site_outcome_tiers={"idealista": "blocked", "immobiliare": "healthy"},
        )

        decision = app_main._decide_runtime_disposition(
            cycle_failed=False,
            cycle_report=report,
            service_state=app_main.LiveServiceState(),
        )

        self.assertEqual(decision.action, "recycle_site_slot")
        self.assertEqual(decision.site, "idealista")
        self.assertEqual(decision.reason, "site_blocked")

    def test_preemptive_site_slot_recycle_triggers_for_long_immobiliare_session(self) -> None:
        runtime = live_fetch.LiveFetchServiceRuntime(
            session_slots={
                "immobiliare|chrome|profile": live_fetch.BrowserSessionSlot(
                    owner_key="immobiliare|chrome|profile",
                    site="immobiliare",
                    channel_label="chrome",
                    profile_root="profile",
                    browser=None,
                    context=object(),
                    page=object(),
                    reuse_count=13,
                    created_monotonic=10.0,
                    last_used_monotonic=20.0,
                )
            }
        )

        decision = app_main._maybe_preemptive_site_slot_recycle(
            slot_summary=live_fetch.service_runtime_site_slot_snapshot(runtime, now_monotonic=5600.0),
            logger=_build_logger("test.preemptive_recycle"),
        )

        self.assertEqual(decision.action, "recycle_site_slot")
        self.assertEqual(decision.site, "immobiliare")
        self.assertIn("session_age_cap", decision.reason)
        self.assertIn("slot_reuse_cap", decision.reason)

    def test_runtime_disposition_recycles_runtime_on_cycle_failure(self) -> None:
        decision = app_main._decide_runtime_disposition(
            cycle_failed=True,
            cycle_report=None,
            service_state=app_main.LiveServiceState(),
        )

        self.assertEqual(decision.action, "recycle_runtime")

    def test_prune_debug_artifacts_removes_stale_and_excess_files(self) -> None:
        logger = _build_logger("test.debug_prune")
        with tempfile.TemporaryDirectory() as tmpdir:
            debug_dir = Path(tmpdir)
            stale = debug_dir / "stale.json"
            fresh_keep = debug_dir / "fresh_keep.json"
            fresh_drop = debug_dir / "fresh_drop.json"
            for path in (stale, fresh_keep, fresh_drop):
                path.write_text("{}", encoding="utf-8")
            os.utime(stale, (10, 10))
            os.utime(fresh_keep, (190, 190))
            os.utime(fresh_drop, (180, 180))

            removed = live_fetch._prune_debug_artifacts(
                debug_dir=debug_dir,
                logger=logger,
                now_epoch=200.0,
                retention_sec=50,
                max_files=1,
            )

            self.assertEqual(removed, 2)
            self.assertFalse(stale.exists())
            self.assertFalse(fresh_drop.exists())
            self.assertTrue(fresh_keep.exists())

    def test_prune_guard_state_sites_keeps_only_configured_sites(self) -> None:
        state = {
            "version": 5,
            "last_channel": "chrome",
            "sites": {
                "idealista": {"strikes": 0},
                "immobiliare": {"strikes": 1},
                "old_site": {"strikes": 2},
            },
        }

        removed = live_fetch._prune_guard_state_sites(
            state,
            [
                "https://www.idealista.it/affitto-case/torino/",
                "https://www.immobiliare.it/search-list/?idContratto=2&idCategoria=1",
            ],
        )

        self.assertEqual(removed, ["old_site"])
        self.assertEqual(sorted(state["sites"].keys()), ["idealista", "immobiliare"])

    def test_runtime_disposition_recycles_runtime_on_multi_site_degraded(self) -> None:
        report = live_fetch.LiveFetchRunReport(
            listings=[],
            run_state="degraded",
            run_state_site="idealista",
            assist_required=False,
            assist_reason="",
            stop_requested=False,
            stop_reason="",
            site_outcome_tiers={"idealista": "degraded", "immobiliare": "cooling"},
        )

        decision = app_main._decide_runtime_disposition(
            cycle_failed=False,
            cycle_report=report,
            service_state=app_main.LiveServiceState(),
        )

        self.assertEqual(decision.action, "recycle_runtime")
        self.assertEqual(decision.reason, "multi_site_degraded")

    def test_runtime_disposition_stops_service_when_run_requires_assistance(self) -> None:
        report = live_fetch.LiveFetchRunReport(
            listings=[],
            run_state="assist_required",
            run_state_site="idealista",
            assist_required=True,
            assist_reason="challenge_repeat",
            stop_requested=True,
            stop_reason="challenge_repeat",
        )

        decision = app_main._decide_runtime_disposition(
            cycle_failed=False,
            cycle_report=report,
            service_state=app_main.LiveServiceState(),
        )

        self.assertEqual(decision.action, "stop_service")
        self.assertEqual(decision.reason, "challenge_repeat")

    def test_live_service_runs_multiple_cycles_without_sleep_when_already_due(self) -> None:
        logger = _build_logger("test.live_service.cycles")
        args = self._build_service_args(max_cycles=2)
        fake_times = iter([0.0, 0.0, 1.0, 2.0, 300.0, 301.0, 302.0])
        sleep_calls: list[float] = []
        cycle_calls: list[int] = []

        def fake_monotonic() -> float:
            return next(fake_times)

        def fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "app_config.json"
            profiles_path = Path(tmpdir) / "profiles.json"
            with mock.patch.object(app_main, "load_or_create_config", return_value=_build_config(private_only_ads=False)):
                with mock.patch.object(app_main, "_apply_config_overrides", side_effect=lambda config, raw_args: (config, [])):
                    with mock.patch.object(app_main, "_run_fetch_live_once", side_effect=lambda *a, **k: cycle_calls.append(1)):
                        app_main._run_fetch_live_service(
                            config_path,
                            profiles_path,
                            args,
                            logger,
                            monotonic_fn=fake_monotonic,
                            sleep_fn=fake_sleep,
                        )

        self.assertEqual(len(cycle_calls), 2)
        self.assertEqual(sleep_calls, [])

    def test_live_service_stops_cleanly_when_stop_flag_exists_before_first_cycle(self) -> None:
        logger = _build_logger("test.live_service.stop_flag_pre_cycle")
        args = self._build_service_args(max_cycles=2)

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "app_config.json"
            profiles_path = Path(tmpdir) / "profiles.json"
            stop_flag = Path(tmpdir) / "live_service.stop"
            stop_flag.write_text("stop\n", encoding="utf-8")
            run_args = vars(args).copy()
            run_args["service_stop_flag"] = str(stop_flag)
            with mock.patch.object(app_main, "load_or_create_config", return_value=_build_config(private_only_ads=False)):
                with mock.patch.object(app_main, "_apply_config_overrides", side_effect=lambda config, raw_args: (config, [])):
                    with mock.patch.object(app_main, "_clear_service_stop_flag", side_effect=lambda path: None):
                        with mock.patch.object(app_main, "_run_fetch_live_once") as run_once_mock:
                            app_main._run_fetch_live_service(
                                config_path,
                                profiles_path,
                                argparse.Namespace(**run_args),
                                logger,
                                monotonic_fn=lambda: 0.0,
                                sleep_fn=lambda _: None,
                            )

        run_once_mock.assert_not_called()

    def test_live_service_stops_cleanly_when_stop_flag_is_created_while_waiting(self) -> None:
        logger = _build_logger("test.live_service.stop_flag_wait")
        args = self._build_service_args(max_cycles=3)
        fake_times = iter([0.0, 0.0, 1.0, 2.0, 2.0, 300.0])

        def fake_monotonic() -> float:
            return next(fake_times)

        sleep_calls: list[float] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "app_config.json"
            profiles_path = Path(tmpdir) / "profiles.json"
            stop_flag = Path(tmpdir) / "live_service.stop"
            run_args = vars(args).copy()
            run_args["service_stop_flag"] = str(stop_flag)

            def fake_sleep(seconds: float) -> None:
                sleep_calls.append(seconds)
                stop_flag.write_text("stop\n", encoding="utf-8")

            with mock.patch.object(app_main, "load_or_create_config", return_value=_build_config(private_only_ads=False)):
                with mock.patch.object(app_main, "_apply_config_overrides", side_effect=lambda config, raw_args: (config, [])):
                    with mock.patch.object(app_main, "_run_fetch_live_once", return_value=None) as run_once_mock:
                        app_main._run_fetch_live_service(
                            config_path,
                            profiles_path,
                            argparse.Namespace(**run_args),
                            logger,
                            monotonic_fn=fake_monotonic,
                            sleep_fn=fake_sleep,
                        )

        run_once_mock.assert_called_once()
        self.assertEqual(sleep_calls, [1.0])

    def test_live_service_reuses_same_runtime_between_cycles_and_closes_it(self) -> None:
        logger = _build_logger("test.live_service.runtime")
        args = self._build_service_args(max_cycles=2)
        fake_times = iter([0.0, 0.0, 1.0, 2.0, 300.0, 301.0, 302.0])
        runtime_ids: list[int] = []

        def fake_monotonic() -> float:
            return next(fake_times)

        def capture_runtime(*_args, **kwargs) -> None:
            runtime = kwargs.get("service_runtime")
            runtime_ids.append(id(runtime))
            runtime.session_slots["idealista|chrome|persist"] = mock.Mock()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "app_config.json"
            profiles_path = Path(tmpdir) / "profiles.json"
            with mock.patch.object(app_main, "load_or_create_config", return_value=_build_config(private_only_ads=False)):
                with mock.patch.object(app_main, "_apply_config_overrides", side_effect=lambda config, raw_args: (config, [])):
                    with mock.patch.object(app_main, "_run_fetch_live_once", side_effect=capture_runtime):
                        with mock.patch.object(app_main, "close_live_fetch_service_runtime", new=mock.AsyncMock()) as close_mock:
                            app_main._run_fetch_live_service(
                                config_path,
                                profiles_path,
                                args,
                                logger,
                                monotonic_fn=fake_monotonic,
                                sleep_fn=lambda _: None,
                            )

        self.assertEqual(len(runtime_ids), 2)
        self.assertEqual(runtime_ids[0], runtime_ids[1])
        close_mock.assert_awaited_once()

    def test_live_service_counts_overruns_and_missed_slots(self) -> None:
        logger = _build_logger("test.live_service.overrun")
        args = self._build_service_args(max_cycles=1)
        fake_times = iter([0.0, 0.0, 0.0, 700.0])

        def fake_monotonic() -> float:
            return next(fake_times)

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "app_config.json"
            profiles_path = Path(tmpdir) / "profiles.json"
            with mock.patch.object(app_main, "load_or_create_config", return_value=_build_config(private_only_ads=False)):
                with mock.patch.object(app_main, "_apply_config_overrides", side_effect=lambda config, raw_args: (config, [])):
                    with mock.patch.object(app_main, "_run_fetch_live_once", return_value=None):
                        with mock.patch.object(logger, "warning") as warning_mock:
                            app_main._run_fetch_live_service(
                                config_path,
                                profiles_path,
                                args,
                                logger,
                                monotonic_fn=fake_monotonic,
                                sleep_fn=lambda _: None,
                            )

        warning_messages = " ".join(str(call.args[0]) for call in warning_mock.call_args_list)
        self.assertIn("exceeded hard threshold", warning_messages)
        self.assertIn("missed scheduled slots", warning_messages)

    def test_live_service_recycles_site_slot_when_run_report_enters_cooldown(self) -> None:
        logger = _build_logger("test.live_service.recycle_site")
        args = self._build_service_args(max_cycles=1)
        fake_times = iter([0.0, 0.0, 1.0, 2.0])

        def fake_monotonic() -> float:
            return next(fake_times)

        run_report = live_fetch.LiveFetchRunReport(
            listings=[],
            run_state="cooldown",
            run_state_site="idealista",
            assist_required=False,
            assist_reason="",
            stop_requested=True,
            stop_reason="cooldown_active",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "app_config.json"
            profiles_path = Path(tmpdir) / "profiles.json"
            with mock.patch.object(app_main, "load_or_create_config", return_value=_build_config(private_only_ads=False)):
                with mock.patch.object(app_main, "_apply_config_overrides", side_effect=lambda config, raw_args: (config, [])):
                    with mock.patch.object(app_main, "_run_fetch_live_once", return_value=run_report):
                        with mock.patch.object(app_main, "recycle_live_fetch_site_runtime", new=mock.AsyncMock(return_value=1)) as recycle_mock:
                            with mock.patch.object(app_main, "close_live_fetch_service_runtime", new=mock.AsyncMock()):
                                app_main._run_fetch_live_service(
                                    config_path,
                                    profiles_path,
                                    args,
                                    logger,
                                    monotonic_fn=fake_monotonic,
                                    sleep_fn=lambda _: None,
                                )

        recycle_mock.assert_awaited_once()

    def test_live_service_stops_when_service_state_requires_assistance(self) -> None:
        logger = _build_logger("test.live_service.assist")
        args = self._build_service_args(max_cycles=3)
        fake_times = iter([0.0, 0.0, 1.0, 2.0, 300.0, 301.0, 302.0])

        def fake_monotonic() -> float:
            return next(fake_times)

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "app_config.json"
            profiles_path = Path(tmpdir) / "profiles.json"
            with mock.patch.object(app_main, "load_or_create_config", return_value=_build_config(private_only_ads=False)):
                with mock.patch.object(app_main, "_apply_config_overrides", side_effect=lambda config, raw_args: (config, [])):
                    with mock.patch.object(
                        app_main,
                        "_run_fetch_live_once",
                        side_effect=[
                            app_main.RuntimeJobError("cycle-1"),
                            app_main.RuntimeJobError("cycle-2"),
                        ],
                    ):
                        with self.assertRaisesRegex(app_main.RuntimeJobError, "requires assistance"):
                            app_main._run_fetch_live_service(
                                config_path,
                                profiles_path,
                                args,
                                logger,
                                monotonic_fn=fake_monotonic,
                                sleep_fn=lambda _: None,
                            )

    def test_live_service_stops_when_run_report_requires_assistance(self) -> None:
        logger = _build_logger("test.live_service.run_report_assist")
        args = self._build_service_args(max_cycles=2)
        fake_times = iter([0.0, 0.0, 1.0, 2.0])

        def fake_monotonic() -> float:
            return next(fake_times)

        run_report = live_fetch.LiveFetchRunReport(
            listings=[],
            run_state="assist_required",
            run_state_site="idealista",
            assist_required=True,
            assist_reason="challenge_repeat",
            stop_requested=True,
            stop_reason="challenge_repeat",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "app_config.json"
            profiles_path = Path(tmpdir) / "profiles.json"
            with mock.patch.object(app_main, "load_or_create_config", return_value=_build_config(private_only_ads=False)):
                with mock.patch.object(app_main, "_apply_config_overrides", side_effect=lambda config, raw_args: (config, [])):
                    with mock.patch.object(app_main, "_run_fetch_live_once", return_value=run_report):
                        with self.assertRaisesRegex(app_main.RuntimeJobError, "requires assistance"):
                            app_main._run_fetch_live_service(
                                config_path,
                                profiles_path,
                                args,
                                logger,
                                monotonic_fn=fake_monotonic,
                                sleep_fn=lambda _: None,
                            )


class LiveFetchCommandTests(unittest.TestCase):
    def test_run_fetch_live_once_passes_storage_retention_to_live_fetch(self) -> None:
        logger = _build_logger("test.fetch_live_once.retention")
        args = argparse.Namespace(
            save_overrides=False,
            db="",
            notify_mode="none",
            send_real_notifications=False,
            max_per_site=0,
            headed=False,
            browser_channel="auto",
            profile_dir="",
            save_live_debug=True,
            live_debug_dir="",
            disable_site_guard=False,
            guard_state_file="",
            guard_jitter_min_sec=2,
            guard_jitter_max_sec=6,
            guard_base_cooldown_min=30,
            guard_max_cooldown_min=360,
            guard_ignore_cooldown=False,
            guard_reset_state=False,
            wait_after_goto_ms=1000,
            nav_timeout_ms=10000,
            captcha_wait_sec=20,
        )
        captured_kwargs: dict[str, object] = {}

        def fake_fetch_runner(kwargs: dict[str, object]):
            captured_kwargs.update(kwargs)
            return live_fetch.LiveFetchRunReport(
                listings=[],
                run_state="stable",
                run_state_site="idealista",
                assist_required=False,
                assist_reason="",
                stop_requested=False,
                stop_reason="",
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "app_config.json"
            profiles_path = Path(tmpdir) / "profiles.json"
            config = _build_config(private_only_ads=False)
            config.storage.retention_days = 9
            with mock.patch.object(app_main, "load_or_create_config", return_value=config):
                with mock.patch.object(app_main, "_apply_config_overrides", side_effect=lambda config, raw_args: (config, [])):
                    with mock.patch.object(app_main, "_build_notifiers", return_value=app_main.NotifierBootstrapState()):
                        with mock.patch.object(app_main, "process_listings", return_value=object()):
                            with mock.patch.object(app_main, "_log_pipeline_summary", return_value=None):
                                app_main._run_fetch_live_once(
                                    config_path,
                                    profiles_path,
                                    args,
                                    logger,
                                    fetch_runner=fake_fetch_runner,
                                )

        self.assertEqual(captured_kwargs["artifact_retention_days"], 9)


class GuiCommandTests(unittest.TestCase):
    def test_build_fetch_command_omits_removed_channel_rotation_flag(self) -> None:
        app = object.__new__(gui_app.AffittoGuiApp)
        app.notify_mode_var = _Var("telegram")
        app.max_per_site_var = _Var("15")
        app.debugger_mode_var = _Var(True)
        app.live_debug_dir_path = Path(r"C:\tmp\debug")
        app.guard_state_path = Path(r"C:\tmp\site_guard_state.json")
        app.service_stop_flag_path = Path(r"C:\tmp\live_service.stop")
        app._cli_command = lambda *args: list(args)

        cmd = gui_app.AffittoGuiApp._build_fetch_command(
            app,
            command="fetch-live-service",
            send_real_notifications=True,
        )

        self.assertNotIn("--channel-rotation-mode", cmd)
        self.assertIn("--save-live-debug", cmd)
        self.assertIn("--service-stop-flag", cmd)


if __name__ == "__main__":
    unittest.main()
