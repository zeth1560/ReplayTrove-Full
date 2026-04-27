"""Long-clips ingest must preserve encoder local timestamps in the basename."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock

from ingest import _long_clip_promotion_basename
from processor import parse_captured_at_utc


class LongClipPromotionBasenameTests(unittest.TestCase):
    def test_preserves_encoder_local_stem(self) -> None:
        settings = Mock()
        settings.local_timezone = "America/Chicago"
        entry = Path("2026-04-26T11-25-32.mkv")
        self.assertEqual(
            _long_clip_promotion_basename(entry, settings),
            "2026-04-26T11-25-32.mkv",
        )

    def test_fallback_when_stem_not_obs_local(self) -> None:
        settings = Mock()
        settings.local_timezone = "America/Chicago"
        entry = Path("recording_A.mkv")
        name = _long_clip_promotion_basename(entry, settings)
        self.assertTrue(name.endswith(".mkv"))
        self.assertRegex(name, r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.mkv$")


class ParseCapturedAtUtcTests(unittest.TestCase):
    def test_utc_z_stem(self) -> None:
        p = Path("2026-04-26T16-25-32Z.mp4")
        self.assertEqual(
            parse_captured_at_utc(p, "America/Chicago"),
            "2026-04-26T16:25:32Z",
        )

    def test_local_stem_with_tz(self) -> None:
        p = Path("2026-04-26T11-25-32.mp4")
        out = parse_captured_at_utc(p, "America/Chicago")
        self.assertRegex(out, r"^2026-04-26T\d{2}:\d{2}:\d{2}Z$")


if __name__ == "__main__":
    unittest.main()
