"""Unified config adapter for scoreboard (phase 2 compatibility layer)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ScoreboardUnifiedSnapshot:
    path: Path
    found: bool
    schema_version: int | None
    migrated: bool
    scoreboard_section_loaded: bool
    obsffmpeg_section_loaded: bool
    scoreboard: dict[str, Any]
    obsffmpeg: dict[str, Any]
    error: str | None = None


def _default_settings_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "settings.json"


def load_scoreboard_unified_snapshot() -> ScoreboardUnifiedSnapshot:
    cfg_path = Path(
        os.environ.get("REPLAYTROVE_SETTINGS_FILE", "").strip() or _default_settings_path()
    )
    if not cfg_path.is_file():
        return ScoreboardUnifiedSnapshot(
            path=cfg_path,
            found=False,
            schema_version=None,
            migrated=False,
            scoreboard_section_loaded=False,
            obsffmpeg_section_loaded=False,
            scoreboard={},
            obsffmpeg={},
        )

    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError("settings root is not a JSON object")
    except Exception as exc:  # pragma: no cover - defensive parse guard
        return ScoreboardUnifiedSnapshot(
            path=cfg_path,
            found=True,
            schema_version=None,
            migrated=False,
            scoreboard_section_loaded=False,
            obsffmpeg_section_loaded=False,
            scoreboard={},
            obsffmpeg={},
            error=str(exc),
        )

    scoreboard = (
        data.get("scoreboard") if isinstance(data.get("scoreboard"), dict) else {}
    )
    obsffmpeg = (
        data.get("obsFfmpegPaths")
        if isinstance(data.get("obsFfmpegPaths"), dict)
        else {}
    )
    schema_version = data.get("schemaVersion")
    if isinstance(schema_version, bool):
        schema_version = None
    elif not isinstance(schema_version, int):
        schema_version = None

    return ScoreboardUnifiedSnapshot(
        path=cfg_path,
        found=True,
        schema_version=schema_version,
        migrated=False,
        scoreboard_section_loaded=bool(scoreboard),
        obsffmpeg_section_loaded=bool(obsffmpeg),
        scoreboard=scoreboard,
        obsffmpeg=obsffmpeg,
    )
