"""One-shot diagnostic: print why Companion instant-replay readiness is true/false.

Does **not** POST to Companion by default (POSTs move Stream Deck / Companion pages).

Run from repo root or scoreboard dir:
  python scripts/diag_instant_replay_ready.py
  python scripts/diag_instant_replay_ready.py --post-companion-idle-locked
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

_SCOREBOARD_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _SCOREBOARD_DIR.parent
for _p in (_REPO_ROOT, _SCOREBOARD_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scoreboard.config.settings import load_settings
from scoreboard.encoder_status_overlay import explain_encoder_appliance_ready
from scoreboard.obs_health import probe_obs_video_recorder_ready_with_reason
from scoreboard.worker_health import probe_worker_replay_trigger_http
from scoreboard.startup_validation import resolve_mpv_executable


def _post_url(label: str, url: str) -> None:
    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            code = getattr(resp, "status", resp.getcode())
        print(f"  {label}: HTTP {code} ok")
    except urllib.error.HTTPError as e:
        print(f"  {label}: HTTP {e.code} {e.reason!r} (Companion returned error)")
    except Exception as e:
        print(f"  {label}: FAILED {type(e).__name__}: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--post-companion-idle-locked",
        action="store_true",
        help=(
            "POST only idle + locked readiness URLs (same method as scoreboard). "
            "Never posts replay-active; that would switch Companion into replay mode."
        ),
    )
    args = ap.parse_args()

    env = _SCOREBOARD_DIR / ".env"
    s = load_settings(str(env) if env.is_file() else ".env")

    enc_ok, enc_why = explain_encoder_appliance_ready(s)
    print("encoder_state_path:", s.encoder_state_path)
    print("encoder_appliance_ready (single read, matches strip logic):", enc_ok, enc_why)

    print("replay_enabled:", s.replay_enabled)
    rp = Path(s.replay_video_path)
    print("replay_video_path exists:", rp.is_file(), repr(str(rp)))
    mpv = resolve_mpv_executable(s)
    print("mpv resolved:", mpv)
    print(
        "worker_http_health:",
        s.worker_http_health_host,
        s.worker_http_health_port,
    )
    worker_ok = True
    if s.worker_http_health_port is not None:
        worker_ok = probe_worker_replay_trigger_http(
            s.worker_http_health_host,
            s.worker_http_health_port,
            timeout_sec=2.0,
        )
        print("worker GET /health ok:", worker_ok)
    print("companion_page_switch_enabled:", s.companion_page_switch_enabled)
    print(
        "companion_readiness_require_obs_websocket:",
        s.companion_readiness_require_obs_websocket,
    )
    print(
        "obs websocket:",
        s.obs_websocket_host,
        s.obs_websocket_port,
        "password_set=" + str(bool((s.obs_websocket_password or "").strip())),
    )

    obs_ok = False
    obs_reason = ""
    try:
        import obsws_python  # noqa: F401
    except ImportError:
        print("obsws-python: NOT INSTALLED (pip install obsws-python)")
    else:
        obs_ok, obs_reason = probe_obs_video_recorder_ready_with_reason(s)
        print("probe_obs_video_recorder_ready:", obs_ok)
        if not obs_ok:
            print("  reason:", obs_reason)

    # Same logic as ScoreboardApp._compute_instant_replay_ready
    ir = False
    why = "?"
    if not s.replay_enabled:
        why = "replay_disabled"
    elif mpv is None:
        why = "mpv_not_found"
    elif not rp.is_file():
        why = "replay_video_missing"
    elif s.worker_http_health_port is not None and not worker_ok:
        why = "worker_health_failed"
    elif s.companion_readiness_require_obs_websocket:
        ir = obs_ok
        why = "obs_ws_failed" if not obs_ok else "all_gates_ok"
    else:
        ir = True
        why = "obs_ws_not_required_for_readiness"

    print()
    print(">>> instant_replay_ready:", ir, f"({why})")

    if s.companion_page_switch_enabled:
        print()
        print("Companion page-switch URLs (configured; no POST unless --post-companion-idle-locked):")
        for label, u in (
            ("idle", s.companion_replay_idle_page_url),
            ("locked", s.companion_replay_locked_page_url),
            ("active", s.companion_replay_active_page_url),
        ):
            url = (u or "").strip()
            if not url:
                print(f"  {label}: (not set)")
                continue
            print(f"  {label}: {url}")
        if args.post_companion_idle_locked:
            print()
            print("POST idle + locked only (replay-active is never triggered from this script):")
            for label, u in (
                ("idle", s.companion_replay_idle_page_url),
                ("locked", s.companion_replay_locked_page_url),
            ):
                url = (u or "").strip()
                if not url:
                    print(f"  {label}: (not set, skip)")
                    continue
                _post_url(label, url)

    return 0 if ir else 1


if __name__ == "__main__":
    raise SystemExit(main())
