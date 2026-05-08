"""Unit tests for clip thumbnail seek helper."""

from processor import thumbnail_seek_seconds


def test_thumbnail_seek_unknown_duration_defaults_to_three():
    assert thumbnail_seek_seconds(None) == 3.0


def test_thumbnail_seek_short_clip_targets_three_clamped():
    assert thumbnail_seek_seconds(29.9) == 3.0
    assert thumbnail_seek_seconds(5.0) == 3.0


def test_thumbnail_seek_long_clip_targets_ten_clamped():
    assert thumbnail_seek_seconds(120.0) == 10.0
    assert thumbnail_seek_seconds(60.0) == 10.0


def test_thumbnail_seek_very_short_does_not_exceed_duration():
    # duration 2s -> margin 0.2s -> inner 1.8s -> min(3, 1.8) == 1.8
    assert thumbnail_seek_seconds(2.0) == 1.8


def test_thumbnail_seek_non_finite_falls_back():
    assert thumbnail_seek_seconds(float("nan")) == 3.0
    assert thumbnail_seek_seconds(-1.0) == 3.0
