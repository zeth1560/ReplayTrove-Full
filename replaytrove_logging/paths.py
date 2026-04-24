"""Central log paths: date-first layout."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def utc_day_str(now: datetime | None = None) -> str:
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).date().isoformat()


def day_dir(logs_root: Path, day: str) -> Path:
    return Path(logs_root) / day


def service_jsonl(logs_root: Path, day: str, service: str) -> Path:
    return day_dir(logs_root, day) / f"{service}.jsonl"


def timeline_jsonl(logs_root: Path, day: str) -> Path:
    return day_dir(logs_root, day) / "timeline.jsonl"


def system_jsonl(logs_root: Path, day: str) -> Path:
    return day_dir(logs_root, day) / "system.jsonl"


def index_json(logs_root: Path, day: str) -> Path:
    return day_dir(logs_root, day) / "index.json"
