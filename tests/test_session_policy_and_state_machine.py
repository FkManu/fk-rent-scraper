from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from src.affitto_v2.scrapers import live_fetch
from src.affitto_v2.scrapers.browser.session_policy import get_session_policy


class SessionPolicyTests(unittest.TestCase):
    def test_site_policy_exposes_user_agent_and_hardware_signature(self) -> None:
        policy = get_session_policy("idealista")

        self.assertEqual(policy.site, "idealista")
        self.assertIn("Chrome/134.0.0.0", policy.user_agent)
        self.assertEqual(policy.hardware.device_memory, 16)
        self.assertEqual(policy.hardware.hardware_concurrency, 8)
        self.assertEqual(policy.hardware.webgl_vendor, "Intel Inc.")
        self.assertEqual(policy.hardware.webgl_renderer, "Intel(R) Iris(TM) Graphics Xe")


class StateMachineTests(unittest.TestCase):
    def test_hard_block_forces_cooldown_and_profile_destruction(self) -> None:
        now = datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc)
        state = {"sites": {"immobiliare": live_fetch._new_guard_site_entry()}}
        entry = state["sites"]["immobiliare"]
        entry["warmup_active"] = False
        entry["profile_created_utc"] = (now - timedelta(hours=1)).isoformat()
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

        self.assertTrue(decision.forced_cooldown)
        self.assertTrue(decision.destroy_persistent_profile)
        self.assertEqual(state["sites"]["immobiliare"]["profile_generation"], 1)
        self.assertEqual(state["sites"]["immobiliare"]["cooldown_profile_generation"], 0)
