"""Spawn ReplayTrove launcher ``restart_obs.ps1`` (same OBS flags as launcher_ui)."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
import json
from pathlib import Path

from scoreboard.config.settings import Settings

_LOG = logging.getLogger(__name__)

_POWERSHELL = os.path.join(
    os.environ.get("SystemRoot", r"C:\Windows"),
    "System32",
    "WindowsPowerShell",
    "v1.0",
    "powershell.exe",
)

_GRACEFUL_RELEASE_REASONS = {"shutdown", "stopped_by_operator", "supervision_disabled"}


def _parse_iso_utc(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        # Launcher writes ISO timestamps with trailing Z or offset.
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve_owner_lease_path(settings: Settings) -> Path:
    status_path = (settings.launcher_status_json_path or "").strip()
    if status_path:
        return Path(status_path).resolve().parent / "supervision_owner_lease.json"
    script = (settings.replay_launcher_restart_obs_script or "").strip()
    if script:
        return Path(script).resolve().parent / "supervision_owner_lease.json"
    return Path(r"C:\ReplayTrove\launcher\supervision_owner_lease.json")


def _launcher_supervision_owner_active(settings: Settings) -> bool:
    lease_path = _resolve_owner_lease_path(settings)
    if not lease_path.is_file():
        return False
    try:
        lease = json.loads(lease_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _LOG.warning("Launcher OBS restart: lease read failed path=%s", lease_path)
        return False

    reason = str(lease.get("reason") or "").strip().lower()
    if reason in _GRACEFUL_RELEASE_REASONS:
        return False

    updated_at = _parse_iso_utc(lease.get("updated_at"))
    if updated_at is None:
        return False
    timeout_raw = lease.get("lease_timeout_sec")
    try:
        timeout_sec = int(timeout_raw)
    except (TypeError, ValueError):
        timeout_sec = 20
    timeout_sec = max(1, timeout_sec)
    age_sec = (datetime.now(timezone.utc) - updated_at).total_seconds()
    return age_sec <= timeout_sec


def request_launcher_obs_restart(settings: Settings, reason: str) -> None:
    """
    Non-blocking: start PowerShell to run the launcher script (stop obs64, sentinel, start OBS).

    Only when ``replay_launcher_restart_obs_on_unavailable`` is true and ``os.name == 'nt'``.
    """
    if os.name != "nt":
        _LOG.debug("Launcher OBS restart skipped (not Windows) reason=%r", reason)
        return
    if not settings.replay_launcher_restart_obs_on_unavailable:
        return
    if _launcher_supervision_owner_active(settings):
        _LOG.warning(
            "Launcher OBS restart direct spawn disabled: active launcher supervision owner detected; "
            "using launcher restart signal only reason=%r",
            reason,
        )
        if not settings.launcher_status_enabled:
            _LOG.warning(
                "Launcher OBS restart signal may be unavailable because launcher_status_enabled=false."
            )
        return
    script = (settings.replay_launcher_restart_obs_script or "").strip()
    if not script:
        return
    ps_path = Path(script)
    if not ps_path.is_file():
        _LOG.warning(
            "Launcher OBS restart skipped (script missing): %s reason=%r",
            script,
            reason,
        )
        return
    if not os.path.isfile(_POWERSHELL):
        _LOG.warning("Launcher OBS restart skipped (powershell.exe missing)")
        return

    resolved = str(ps_path.resolve())
    cmd = [
        _POWERSHELL,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        resolved,
    ]
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(
            cmd,
            cwd=str(ps_path.parent),
            creationflags=creationflags,
        )
        _LOG.info(
            "Spawned launcher OBS restart script=%s reason=%r",
            resolved,
            reason,
        )
    except OSError:
        _LOG.exception("Launcher OBS restart spawn failed script=%s", resolved)
