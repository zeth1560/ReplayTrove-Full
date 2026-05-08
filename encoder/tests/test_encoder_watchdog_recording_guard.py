"""Tests for watchdog stale/missing restart gating vs recording protection."""

from __future__ import annotations

import logging
import time
import unittest
from pathlib import Path
import sys

ENCODER_DIR = Path(__file__).resolve().parent.parent
if str(ENCODER_DIR) not in sys.path:
    sys.path.insert(0, str(ENCODER_DIR))

import encoder_watchdog as wd


class StaleRestartDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.log = logging.getLogger("test.encoder_watchdog")

    def test_active_recording_beats_stale_streak_gate(self) -> None:
        should_restart, decision = wd._should_restart_for_stale_state(
            data={"state": "recording", "long_recording_active": True},
            stale_reason="stale_state age=91.0s",
            stale_or_missing_streak=9,
            stale_consecutive_limit=3,
            was_recording_at_last_success=False,
            last_success_mono=0.0,
            now_mono=time.monotonic(),
            short_protect_sec=120.0,
            max_blackout_sec=900.0,
            log=self.log,
        )
        self.assertFalse(should_restart)
        self.assertIn(decision, {"recording_guard", "recording_active"})

    def test_recent_recording_read_protection_beats_missing_state(self) -> None:
        now = time.monotonic()
        should_restart, decision = wd._should_restart_for_stale_state(
            data=None,
            stale_reason="missing_or_unreadable_state_file",
            stale_or_missing_streak=7,
            stale_consecutive_limit=3,
            was_recording_at_last_success=True,
            last_success_mono=now - 30.0,
            now_mono=now,
            short_protect_sec=120.0,
            max_blackout_sec=900.0,
            log=self.log,
        )
        self.assertFalse(should_restart)
        self.assertEqual(decision, "recording_guard")

    def test_restart_allowed_after_recording_protection_and_streak(self) -> None:
        now = time.monotonic()
        should_restart, decision = wd._should_restart_for_stale_state(
            data=None,
            stale_reason="missing_or_unreadable_state_file",
            stale_or_missing_streak=4,
            stale_consecutive_limit=3,
            was_recording_at_last_success=True,
            last_success_mono=now - 2000.0,
            now_mono=now,
            short_protect_sec=120.0,
            max_blackout_sec=900.0,
            log=self.log,
        )
        self.assertTrue(should_restart)
        self.assertEqual(decision, "restart")


if __name__ == "__main__":
    unittest.main()
