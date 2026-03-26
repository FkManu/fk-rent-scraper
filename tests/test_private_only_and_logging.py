from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import logging
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.affitto_v2 import main as app_main
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

    def test_alternate_browser_retry_is_suppressed_when_identity_budget_is_exhausted(self) -> None:
        allowed, reason = live_fetch._allow_alternate_browser_retry(
            cards=[],
            outcome=live_fetch.FetchOutcome(
                tier="blocked",
                code="interstitial_datadome",
                challenge_visible=True,
            ),
            requested_channel=None,
            rotation_mode="round_robin",
            alternate_candidates=["chrome"],
            risk_budget=live_fetch.RiskBudget(
                page_budget=1,
                detail_budget=0,
                identity_budget=0,
                retry_budget=1,
                cooldown_budget=1,
                manual_assist_threshold=1,
            ),
            identity_switch_count=0,
        )

        self.assertFalse(allowed)
        self.assertEqual(reason, "identity_budget_exhausted")

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

        profile_path = live_fetch._profile_dir_for_site_channel(base, "idealista", "chrome")

        self.assertEqual(profile_path, Path("C:/runtime/browser-profile/idealista/chrome"))

    def test_session_owner_key_includes_site_channel_and_profile(self) -> None:
        owner = live_fetch._session_owner_key(
            site="immobiliare",
            channel_label="msedge",
            profile_root=Path("C:/runtime/browser-profile/immobiliare/msedge"),
        )

        self.assertIn("immobiliare", owner)
        self.assertIn("msedge", owner)
        self.assertIn("browser-profile/immobiliare/msedge", owner.replace("\\", "/"))

    def test_session_identity_changes_between_sites(self) -> None:
        idealista_owner, idealista_root = live_fetch._session_identity(
            site="idealista",
            channel_label="chrome",
            profile_dir="C:/runtime/browser-profile",
        )
        immobiliare_owner, immobiliare_root = live_fetch._session_identity(
            site="immobiliare",
            channel_label="chrome",
            profile_dir="C:/runtime/browser-profile",
        )

        self.assertNotEqual(idealista_owner, immobiliare_owner)
        self.assertNotEqual(idealista_root, immobiliare_root)
        self.assertIn("idealista", str(idealista_root).replace("\\", "/"))
        self.assertIn("immobiliare", str(immobiliare_root).replace("\\", "/"))

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

    def test_alternate_browser_retry_candidates_are_empty_with_single_backend(self) -> None:
        candidates = ["msedge", "chrome", None]
        retry_candidates = live_fetch._alternate_browser_retry_candidates(candidates, current_label="camoufox")

        self.assertEqual(retry_candidates, [])

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
            channel_rotation_mode="round_robin",
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


if __name__ == "__main__":
    unittest.main()
