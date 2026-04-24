"""Verify OBS WebSocket host/port/password using the same config and probe as the scoreboard.

Operator-only diagnostic: run manually when troubleshooting. This file is not imported by
``main.py`` or the scoreboard UI; it has no effect on production runs unless you execute it.

Run from the scoreboard project directory (where ``.env`` lives)::

    cd C:\\ReplayTrove\\scoreboard
    .\\.venv\\Scripts\\python.exe test_obs_websocket.py

Exit code 0 = probe succeeded; 1 = probe failed; 2 = settings load error.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Same layout as main.py: repo root (replaytrove_logging) + this folder (scoreboard package).
_SCOREBOARD_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCOREBOARD_DIR.parent
for _p in (_REPO_ROOT, _SCOREBOARD_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scoreboard.config.settings import load_settings
from scoreboard.obs_health import probe_obs_video_recorder_ready_with_reason


def main() -> int:
    logging.basicConfig(level=logging.ERROR)

    parser = argparse.ArgumentParser(
        description="Test OBS WebSocket settings (matches scoreboard readiness probe).",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to .env (default: .env). Prefer running with cwd = scoreboard folder.",
    )
    args = parser.parse_args()

    try:
        settings = load_settings(args.env_file)
    except Exception as exc:
        print(f"Failed to load settings: {exc}", file=sys.stderr)
        return 2

    try:
        import obsws_python  # noqa: F401
    except ImportError:
        print(
            "obsws-python is not installed in this interpreter "
            "(pip install obsws-python).",
            file=sys.stderr,
        )
        return 2

    pw = settings.obs_websocket_password
    pw_note = "(empty)" if not (pw or "").strip() else "(set, not shown)"

    print(f"Target: {settings.obs_websocket_host!r}:{settings.obs_websocket_port}")
    print(f"Timeout: {settings.obs_websocket_timeout_sec}s  Password: {pw_note}")
    print(
        "Gate flags: "
        f"recording_obs_block_if_main_recording={settings.recording_obs_block_if_main_recording} "
        f"obs_status_require_main_output_idle={settings.obs_status_require_main_output_idle}"
    )
    print()

    ok, reason = probe_obs_video_recorder_ready_with_reason(settings)
    if ok:
        print("OK - WebSocket reachable; probe matches Companion / recorder readiness.")
        return 0

    print(f"FAILED - {reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
