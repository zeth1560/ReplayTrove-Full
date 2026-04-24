"""Per-day index.json maintenance (under global_log_write_lock)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_RESTART_SUBSTRINGS = (
    "restart",
    "respawn",
    "restarting operator",
    "supervisor_restart",
)


def default_index(day: str) -> dict[str, Any]:
    return {
        "date": day,
        "services": [],
        "total_events": 0,
        "error_count": 0,
        "warnings": 0,
        "restarts": 0,
        "first_event": None,
        "last_event": None,
    }


def bump_index(
    path: Path,
    *,
    day: str,
    timestamp: str,
    service: str,
    level: str,
    event: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = default_index(day)
    if path.is_file():
        try:
            raw = path.read_text(encoding="utf-8")
            merged = json.loads(raw)
            if isinstance(merged, dict):
                data.update(merged)
        except (OSError, json.JSONDecodeError):
            pass

    data["date"] = day
    data["total_events"] = int(data.get("total_events", 0)) + 1

    svcs = data.get("services")
    if not isinstance(svcs, list):
        svcs = []
    if service not in svcs:
        svcs.append(service)
    data["services"] = sorted(set(str(s) for s in svcs))

    ul = (level or "").upper()
    if ul in ("ERROR", "CRITICAL"):
        data["error_count"] = int(data.get("error_count", 0)) + 1
    if ul == "WARNING":
        data["warnings"] = int(data.get("warnings", 0)) + 1

    ev_l = (event or "").lower()
    if any(s in ev_l for s in _RESTART_SUBSTRINGS):
        data["restarts"] = int(data.get("restarts", 0)) + 1

    fe = data.get("first_event")
    if not fe or (isinstance(fe, str) and timestamp < fe):
        data["first_event"] = timestamp
    le = data.get("last_event")
    if not le or (isinstance(le, str) and timestamp > le):
        data["last_event"] = timestamp

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def apply_retention(
    logs_root: Path,
    *,
    keep_days: int,
    compress: bool = False,
) -> None:
    """Delete day folders older than keep_days (UTC date names). Optional zip archive."""
    import shutil
    from datetime import datetime, timedelta, timezone

    if keep_days < 1:
        return
    root = Path(logs_root)
    if not root.is_dir():
        return
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).date()
    archive_root = root / "_archive"
    for child in root.iterdir():
        if not child.is_dir() or child.name.startswith("_"):
            continue
        if not _DAY_RE.match(child.name):
            continue
        try:
            d = datetime.strptime(child.name, "%Y-%m-%d").replace(tzinfo=timezone.utc).date()
        except ValueError:
            continue
        if d >= cutoff:
            continue
        if compress:
            archive_root.mkdir(parents=True, exist_ok=True)
            base = archive_root / child.name
            shutil.make_archive(str(base), "zip", root_dir=str(child))
        shutil.rmtree(child, ignore_errors=True)
