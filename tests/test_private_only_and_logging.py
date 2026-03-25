from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


class LiveFetchReviewTests(unittest.IsolatedAsyncioTestCase):
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

    def test_resolve_channel_executable_path_uses_installed_browser(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            edge_path = Path(tmpdir) / "msedge.exe"
            edge_path.write_text("", encoding="utf-8")
            with mock.patch.object(live_fetch, "_channel_install_candidates", return_value=[edge_path]):
                resolved = live_fetch._resolve_channel_executable_path("msedge")

        self.assertEqual(resolved, edge_path)

    def test_alternate_browser_retry_candidates_skip_current_channel(self) -> None:
        candidates = ["msedge", "chrome", None]
        retry_candidates = live_fetch._alternate_browser_retry_candidates(candidates, current_label="chrome")

        self.assertEqual(retry_candidates, ["msedge", None])

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
            await live_fetch._verify_idealista_private_only_candidates(
                page=page,
                cards=cards,
                nav_timeout_ms=5000,
                logger=_build_logger("test.live_fetch.detail_verify"),
            )

        self.assertEqual(cards[0]["agency"], "")
        self.assertEqual(cards[1]["agency"], "Professionista (detail check)")
        self.assertEqual(page.visited, [cards[0]["url"], cards[1]["url"]])

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
            await live_fetch._verify_idealista_private_only_candidates(
                page=page,
                cards=cards,
                nav_timeout_ms=5000,
                logger=_build_logger("test.live_fetch.detail_verify.skip_cached"),
            )

        self.assertEqual(page.visited, [cards[1]["url"]])


if __name__ == "__main__":
    unittest.main()
