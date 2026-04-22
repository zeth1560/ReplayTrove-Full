"""Unified config adapter for worker (phase 2 compatibility layer)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkerUnifiedSnapshot:
    path: Path
    found: bool
    schema_version: int | None
    migrated: bool
    worker_section_loaded: bool
    general_section_loaded: bool
    storage_section_loaded: bool
    obsffmpeg_section_loaded: bool
    worker: dict[str, Any]
    general: dict[str, Any]
    storage: dict[str, Any]
    obsffmpeg: dict[str, Any]
    error: str | None = None


def _default_settings_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "settings.json"


def load_worker_unified_snapshot() -> WorkerUnifiedSnapshot:
    cfg_path = Path(
        os.environ.get("REPLAYTROVE_SETTINGS_FILE", "").strip() or _default_settings_path()
    )
    if not cfg_path.is_file():
        return WorkerUnifiedSnapshot(
            path=cfg_path,
            found=False,
            schema_version=None,
            migrated=False,
            worker_section_loaded=False,
            general_section_loaded=False,
            storage_section_loaded=False,
            obsffmpeg_section_loaded=False,
            worker={},
            general={},
            storage={},
            obsffmpeg={},
        )

    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError("settings root is not a JSON object")
    except Exception as exc:  # pragma: no cover - defensive parse guard
        return WorkerUnifiedSnapshot(
            path=cfg_path,
            found=True,
            schema_version=None,
            migrated=False,
            worker_section_loaded=False,
            general_section_loaded=False,
            storage_section_loaded=False,
            obsffmpeg_section_loaded=False,
            worker={},
            general={},
            storage={},
            obsffmpeg={},
            error=str(exc),
        )

    worker = data.get("worker") if isinstance(data.get("worker"), dict) else {}
    general = data.get("general") if isinstance(data.get("general"), dict) else {}
    storage = data.get("storage") if isinstance(data.get("storage"), dict) else {}
    obsffmpeg = (
        data.get("obsFfmpegPaths")
        if isinstance(data.get("obsFfmpegPaths"), dict)
        else {}
    )
    schema_version = data.get("schemaVersion")
    if isinstance(schema_version, bool):  # bool is int subclass; reject
        schema_version = None
    elif not isinstance(schema_version, int):
        schema_version = None

    return WorkerUnifiedSnapshot(
        path=cfg_path,
        found=True,
        schema_version=schema_version,
        migrated=False,
        worker_section_loaded=bool(worker),
        general_section_loaded=bool(general),
        storage_section_loaded=bool(storage),
        obsffmpeg_section_loaded=bool(obsffmpeg),
        worker=worker,
        general=general,
        storage=storage,
        obsffmpeg=obsffmpeg,
    )
