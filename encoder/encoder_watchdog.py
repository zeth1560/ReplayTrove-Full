"""
Supervise the long-record operator process and restart it when encoder_state.json
reports unhealthy status (blocked, degraded, or stale updates). While
``long_recording_active`` is true or ``state`` is ``recording``, stale/degraded
restarts are skipped so a take ends only via the operator or max duration.

Primary health check: HTTP GET http://127.0.0.1:<port>/watchdog on the operator
(see ENCODER_WATCHDOG_HTTP_PORT in encoder .env). The encoder answers whether it is
ok, busy recording, or wants an external restart — so the watchdog does not rely only
on encoder_state.json (which can be temporarily unreadable on Windows).

If the ping endpoint is disabled (port 0) or unreachable, the watchdog falls back to
reading encoder_state.json. If the state file is temporarily unreadable while recording,
restarts are skipped for a short protect window, then a longer blackout cap, before
forcing a restart.

Run this instead of starting operator_long_only.py directly, e.g.:
  python encoder_watchdog.py

Environment (optional, after loading .env):
  ENCODER_WATCHDOG_HTTP_BIND / ENCODER_WATCHDOG_HTTP_PORT — must match the operator
      (default 127.0.0.1:18766; port 0 = file-only mode, no ping)
  WATCHDOG_ENCODER_PING_TIMEOUT_SECONDS — ping timeout (default: 2)
  ENCODER_STATE_PATH — same as operator (default: C:\\ReplayTrove\\scoreboard\\encoder_state.json)
  WATCHDOG_OPERATOR_SCRIPT — path to operator_long_only.py (default: alongside this file)
  WATCHDOG_POLL_INTERVAL — seconds between checks (default: 2)
  WATCHDOG_STARTUP_GRACE_SECONDS — ignore bad state until this long after each spawn (default: 45)
  WATCHDOG_STALE_STATE_SECONDS — if updated_at is older than this while child is alive, restart (default: 90)
  WATCHDOG_MAX_RESTARTS — exit watchdog after this many restarts in the sliding window (default: 15)
  WATCHDOG_RESTART_WINDOW_SECONDS — window for max restarts (default: 600)
  WATCHDOG_STATE_READ_ATTEMPTS — retries when encoder_state.json is unreadable (default: 5)
  WATCHDOG_STATE_READ_RETRY_DELAY_SECONDS — delay between read retries (default: 0.05)
  WATCHDOG_RECORDING_SHORT_PROTECT_SECONDS — after last good read showed recording, skip kills
      for this many seconds when state is unreadable/stale (default: 120)
  WATCHDOG_RECORDING_BLACKOUT_MAX_SECONDS — if state stays unreadable longer than this while the
      last good read showed recording, allow restart (operator likely wedged) (default: 900)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from replaytrove_logging.setup import setup_component_logging
from settings import load_dotenv_if_present
from subprocess_win import no_console_creationflags


def _opt_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return float(str(raw).strip())


def _opt_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return int(str(raw).strip())


def _state_path() -> Path:
    return Path(
        os.environ.get(
            "ENCODER_STATE_PATH",
            r"C:\ReplayTrove\scoreboard\encoder_state.json",
        )
    ).resolve()


def _purge_encoder_pending_commands(log: logging.Logger) -> None:
    """Move stale JSON from commands/encoder/pending before the first operator spawn.

    Stream Deck / Companion commands can accumulate while the encoder is down; draining
    them after a long outage causes bogus start/stop bursts. Default: enabled; set
    ENCODER_WATCHDOG_PURGE_PENDING_COMMANDS=0 to keep pending files.
    """
    raw = os.environ.get("ENCODER_WATCHDOG_PURGE_PENDING_COMMANDS", "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        log.info(
            "Encoder pending command purge skipped "
            "(ENCODER_WATCHDOG_PURGE_PENDING_COMMANDS=%s).",
            os.environ.get("ENCODER_WATCHDOG_PURGE_PENDING_COMMANDS", ""),
        )
        return
    pending = _REPO_ROOT / "commands" / "encoder" / "pending"
    if not pending.is_dir():
        return
    dest = _REPO_ROOT / "commands" / "encoder" / "purged_on_startup"
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("Encoder pending purge: cannot create %s: %s", dest, exc)
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    moved = 0
    for p in sorted(pending.iterdir()):
        if not p.is_file() or p.suffix.lower() != ".json":
            continue
        target = dest / f"{stamp}__{p.name}"
        n = 1
        while target.exists():
            target = dest / f"{stamp}__{n}__{p.name}"
            n += 1
        try:
            p.replace(target)
            moved += 1
        except OSError as exc:
            log.warning("Encoder pending purge: could not move %s: %s", p, exc)
    if moved:
        log.info(
            "Purged %s encoder command(s) from backlog (%s -> %s, batch=%s).",
            moved,
            pending,
            dest,
            stamp,
        )


def _operator_argv() -> list[str]:
    override = os.environ.get("WATCHDOG_OPERATOR_SCRIPT", "").strip()
    if override:
        script = Path(override).resolve()
    else:
        script = Path(__file__).resolve().parent / "operator_long_only.py"
    if not script.exists():
        raise FileNotFoundError(f"Operator script not found: {script}")
    return [sys.executable, str(script)]


def _parse_updated_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        s = raw.strip().replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _read_state(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _state_requires_restart(data: dict[str, Any]) -> tuple[bool, str]:
    st = data.get("state")
    if st == "shutting_down":
        return False, ""
    if data.get("degraded") is True:
        return True, "degraded"
    if st == "blocked":
        return True, "blocked"
    if st == "unavailable":
        return False, ""
    return False, ""


def _long_recording_active(data: dict[str, Any] | None) -> bool:
    """True when operator reports an in-progress capture (do not kill for stale/degraded)."""
    if not data:
        return False
    if data.get("long_recording_active") is True:
        return True
    st = str(data.get("state", "")).strip().lower()
    return st == "recording"


def _stale_from_data(data: dict[str, Any] | None, stale_after: float) -> tuple[bool, str]:
    """Stale/unhealthy decision from one parsed state payload (or None if unreadable)."""
    if data is None:
        return True, "missing_or_unreadable_state_file"
    ts = _parse_updated_at(data.get("updated_at"))
    if ts is None:
        return True, "invalid_or_missing_updated_at"
    age = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
    if age > stale_after:
        return True, f"stale_state age={age:.1f}s"
    return False, ""


def _state_age_seconds(data: dict[str, Any] | None) -> float | None:
    if not data:
        return None
    ts = _parse_updated_at(data.get("updated_at"))
    if ts is None:
        return None
    return (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()


def _log_restart_event(
    log: logging.Logger,
    *,
    reason: str,
    child: subprocess.Popen | None,
    state_path: Path,
    data: dict[str, Any] | None,
    expected_mode: str,
) -> None:
    process_alive = bool(child is not None and child.poll() is None)
    state_exists = state_path.is_file()
    state_age = _state_age_seconds(data)
    log.warning(
        "watchdog_restart_operator reason=%s process_alive=%s state_exists=%s state_age_seconds=%s expected_mode=%s",
        reason,
        process_alive,
        state_exists,
        f"{state_age:.1f}" if state_age is not None else "n/a",
        expected_mode or "unknown",
    )


def _read_state_with_retries(
    path: Path, attempts: int, delay_sec: float, log: logging.Logger
) -> dict[str, Any] | None:
    last: dict[str, Any] | None = None
    for i in range(max(1, attempts)):
        last = _read_state(path)
        if last is not None:
            return last
        if i + 1 < attempts:
            log.debug(
                "State read failed (%s attempt %s/%s); retrying in %.3fs",
                path,
                i + 1,
                attempts,
                delay_sec,
            )
            time.sleep(delay_sec)
    return None


def _recording_guard_suppresses_kill(
    *,
    data: dict[str, Any] | None,
    was_recording_at_last_success: bool,
    last_success_mono: float,
    now_mono: float,
    short_protect_sec: float,
    max_blackout_sec: float,
    log: logging.Logger,
    reason: str,
) -> bool:
    """
    If the operator recently reported an in-progress long capture, do not kill the process
    when ``encoder_state.json`` is temporarily unreadable or flaky — unless the blackout
    window has expired (operator likely wedged).
    """
    if _long_recording_active(data):
        return True
    if not was_recording_at_last_success or last_success_mono <= 0.0:
        return False
    elapsed = now_mono - last_success_mono
    if elapsed <= short_protect_sec:
        log.warning(
            "Recording guard: would restart (%s) but last successful state read %.1fs ago "
            "showed an in-progress capture; skipping kill (transient read/state issue).",
            reason,
            elapsed,
        )
        return True
    if elapsed < max_blackout_sec:
        log.debug(
            "Recording guard: skipping restart (%s); %.1fs since last good read "
            "(blackout cap %.0fs).",
            reason,
            elapsed,
            max_blackout_sec,
        )
        return True
    log.warning(
        "Recording guard lifted: %.0fs since last readable state (cap %.0fs); proceeding (%s).",
        elapsed,
        max_blackout_sec,
        reason,
    )
    return False


def _should_restart_for_stale_state(
    *,
    data: dict[str, Any] | None,
    stale_reason: str,
    stale_or_missing_streak: int,
    stale_consecutive_limit: int,
    was_recording_at_last_success: bool,
    last_success_mono: float,
    now_mono: float,
    short_protect_sec: float,
    max_blackout_sec: float,
    log: logging.Logger,
) -> tuple[bool, str]:
    """Decide whether stale/missing state should trigger restart.

    Recording protection is evaluated before streak gating so active/recent recording
    cannot be overridden by stale/missing consecutive-failure thresholds.
    """
    if _recording_guard_suppresses_kill(
        data=data,
        was_recording_at_last_success=was_recording_at_last_success,
        last_success_mono=last_success_mono,
        now_mono=now_mono,
        short_protect_sec=short_protect_sec,
        max_blackout_sec=max_blackout_sec,
        log=log,
        reason=stale_reason,
    ):
        return False, "recording_guard"
    if _long_recording_active(data):
        return False, "recording_active"
    if stale_or_missing_streak < stale_consecutive_limit:
        return False, "below_stale_consecutive_limit"
    return True, "restart"


def _fetch_encoder_ping(
    host: str, port: int, timeout: float, log: logging.Logger
) -> dict[str, Any] | None:
    if port <= 0:
        return None
    url = f"http://{host}:{port}/watchdog"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                log.debug("encoder ping HTTP status=%s", resp.status)
                return None
            raw = resp.read()
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            return None
        return parsed
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        log.debug("encoder ping failed: %s", exc)
        return None
    except json.JSONDecodeError as exc:
        log.debug("encoder ping invalid JSON: %s", exc)
        return None


def _kill_process_tree(pid: int, log: logging.Logger) -> None:
    if pid <= 0:
        return
    if sys.platform == "win32":
        r = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=45,
            **no_console_creationflags(),
        )
        if r.returncode != 0:
            log.warning(
                "taskkill exit %s: %s",
                r.returncode,
                (r.stderr or r.stdout or "").strip()[-500:],
            )
    else:
        try:
            os.kill(pid, 15)
        except OSError as e:
            log.warning("kill(%s) failed: %s", pid, e)


def main() -> None:
    load_dotenv_if_present()
    state_path = _state_path()
    poll = _opt_float("WATCHDOG_POLL_INTERVAL", 2.0)
    grace = _opt_float("WATCHDOG_STARTUP_GRACE_SECONDS", 45.0)
    stale_after = _opt_float("WATCHDOG_STALE_STATE_SECONDS", 90.0)
    max_restarts = _opt_int("WATCHDOG_MAX_RESTARTS", 15)
    window_sec = _opt_float("WATCHDOG_RESTART_WINDOW_SECONDS", 600.0)
    read_attempts = _opt_int("WATCHDOG_STATE_READ_ATTEMPTS", 5)
    read_retry_delay = _opt_float("WATCHDOG_STATE_READ_RETRY_DELAY_SECONDS", 0.05)
    rec_short_protect = _opt_float("WATCHDOG_RECORDING_SHORT_PROTECT_SECONDS", 120.0)
    rec_blackout_max = _opt_float("WATCHDOG_RECORDING_BLACKOUT_MAX_SECONDS", 900.0)
    stale_consecutive_limit = max(1, _opt_int("WATCHDOG_STALE_CONSECUTIVE_LIMIT", 3))
    ping_host = (
        os.environ.get("ENCODER_WATCHDOG_HTTP_BIND", "127.0.0.1").strip() or "127.0.0.1"
    )
    ping_port = _opt_int("ENCODER_WATCHDOG_HTTP_PORT", 18766)
    ping_timeout = _opt_float("WATCHDOG_ENCODER_PING_TIMEOUT_SECONDS", 2.0)
    restart_on_zero = os.environ.get("WATCHDOG_RESTART_ON_ZERO_EXIT", "0").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    log_root = Path(os.environ.get("ENCODER_LOG_DIR", r"C:\ReplayTrove\logs"))
    log_root.mkdir(parents=True, exist_ok=True)
    setup_component_logging(
        logs_root=log_root,
        service="encoder_watchdog",
        console_level=logging.INFO,
        file_level=logging.DEBUG,
        attach_to_root=False,
        logger_name="replaytrove.encoder.watchdog",
        clear_existing_handlers=True,
        enable_system_heartbeat=False,
    )
    log = logging.getLogger("replaytrove.encoder.watchdog")

    argv = _operator_argv()
    log.info(
        "Watchdog starting; state=%s operator=%s ping=%s:%s",
        state_path,
        argv,
        ping_host,
        ping_port if ping_port > 0 else "(off)",
    )
    _purge_encoder_pending_commands(log)

    restart_times: deque[float] = deque()
    child: subprocess.Popen | None = None
    spawn_mono: float = 0.0
    last_state_success_mono: float = 0.0
    was_recording_at_last_success: bool = False
    stale_or_missing_streak: int = 0

    def bump_restart_counter() -> None:
        restart_times.append(time.monotonic())
        if len(restart_times) >= max_restarts:
            log.critical(
                "Reached %s restarts in %.0fs (limit=%s); exiting watchdog.",
                len(restart_times),
                window_sec,
                max_restarts,
            )
            raise SystemExit(2)

    try:
        while True:
            now = time.monotonic()
            while restart_times and now - restart_times[0] > window_sec:
                restart_times.popleft()

            if child is None or child.poll() is not None:
                if child is not None and child.poll() is not None:
                    code = child.returncode
                    if code == 0 and not restart_on_zero:
                        log.info("Operator exited normally; watchdog stopping.")
                        return
                    # operator_long_only: singleton mutex held by another process
                    if code == 86:
                        log.error(
                            "Operator exited with code 86 (duplicate instance: another "
                            "long-only operator is already running). Watchdog exiting — "
                            "do not start multiple encoder stacks or watchdogs."
                        )
                        return
                    log.error("Operator exited (code=%s); restarting.", code)
                    bump_restart_counter()

                log.info("Spawning operator: %s", argv)
                child = subprocess.Popen(argv, **no_console_creationflags())
                spawn_mono = time.monotonic()
                last_state_success_mono = 0.0
                was_recording_at_last_success = False
                stale_or_missing_streak = 0
                time.sleep(min(poll, 1.0))
                continue

            in_grace = (time.monotonic() - spawn_mono) < grace

            if not in_grace:
                if ping_port > 0:
                    ping = _fetch_encoder_ping(ping_host, ping_port, ping_timeout, log)
                    if ping is not None and ping.get("schema_version") == 1:
                        if ping.get("restart_recommended") is True:
                            _log_restart_event(
                                log,
                                reason="ping_restart_recommended",
                                child=child,
                                state_path=state_path,
                                data=None,
                                expected_mode=str(ping.get("app_state") or "unknown"),
                            )
                            log.warning(
                                "Restarting operator details source=encoder_ping run_id=%s note=%s",
                                ping.get("run_id"),
                                ping.get("operator_note"),
                            )
                            _kill_process_tree(child.pid, log)
                            try:
                                child.wait(timeout=20)
                            except subprocess.TimeoutExpired:
                                log.warning("Child wait timeout after taskkill.")
                            child = None
                            bump_restart_counter()
                            time.sleep(1.0)
                            continue
                        if ping.get("ok") is True or ping.get("long_recording_active") is True:
                            log.debug(
                                "Encoder ping healthy app_state=%s recording=%s — "
                                "skipping encoder_state.json gate this cycle",
                                ping.get("app_state"),
                                ping.get("long_recording_active"),
                            )
                            time.sleep(poll)
                            continue

                data = _read_state_with_retries(
                    state_path, read_attempts, read_retry_delay, log
                )
                if data is not None:
                    last_state_success_mono = time.monotonic()
                    was_recording_at_last_success = _long_recording_active(data)
                    stale_or_missing_streak = 0

                bad_stale, stale_reason = _stale_from_data(data, stale_after)
                if bad_stale:
                    stale_or_missing_streak += 1
                    should_restart, decision = _should_restart_for_stale_state(
                        data=data,
                        stale_reason=stale_reason,
                        stale_or_missing_streak=stale_or_missing_streak,
                        stale_consecutive_limit=stale_consecutive_limit,
                        was_recording_at_last_success=was_recording_at_last_success,
                        last_success_mono=last_state_success_mono,
                        now_mono=time.monotonic(),
                        short_protect_sec=rec_short_protect,
                        max_blackout_sec=rec_blackout_max,
                        log=log,
                    )
                    if not should_restart and decision == "recording_guard":
                        time.sleep(poll)
                        continue
                    expected_mode = str(
                        (data or {}).get("state")
                        or (ping or {}).get("app_state")
                        or "unknown"
                    )
                    if not should_restart and decision == "below_stale_consecutive_limit":
                        log.warning(
                            "Deferring operator restart for transient state issue "
                            "(reason=%s streak=%s/%s expected_mode=%s).",
                            stale_reason,
                            stale_or_missing_streak,
                            stale_consecutive_limit,
                            expected_mode,
                        )
                        time.sleep(poll)
                        continue
                    _log_restart_event(
                        log,
                        reason=stale_reason,
                        child=child,
                        state_path=state_path,
                        data=data,
                        expected_mode=expected_mode,
                    )
                    _kill_process_tree(child.pid, log)
                    try:
                        child.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        log.warning("Child wait timeout after taskkill.")
                    child = None
                    stale_or_missing_streak = 0
                    bump_restart_counter()
                    time.sleep(1.0)
                    continue
                stale_or_missing_streak = 0

                if data:
                    need, reason = _state_requires_restart(data)
                    if need:
                        if _recording_guard_suppresses_kill(
                            data=data,
                            was_recording_at_last_success=was_recording_at_last_success,
                            last_success_mono=last_state_success_mono,
                            now_mono=time.monotonic(),
                            short_protect_sec=rec_short_protect,
                            max_blackout_sec=rec_blackout_max,
                            log=log,
                            reason=reason,
                        ):
                            time.sleep(poll)
                            continue
                        if _long_recording_active(data):
                            log.warning(
                                "Operator restart wanted (%s) but long recording active; "
                                "skipping kill (policy: stop only via operator or max duration).",
                                reason,
                            )
                            time.sleep(poll)
                            continue
                        _log_restart_event(
                            log,
                            reason=reason,
                            child=child,
                            state_path=state_path,
                            data=data,
                            expected_mode=str(data.get("state") or "unknown"),
                        )
                        log.warning(
                            "Restarting operator details state=%s last_error=%s",
                            data.get("state"),
                            data.get("last_error"),
                        )
                        _kill_process_tree(child.pid, log)
                        try:
                            child.wait(timeout=20)
                        except subprocess.TimeoutExpired:
                            log.warning("Child wait timeout after taskkill.")
                        child = None
                        bump_restart_counter()
                        time.sleep(1.0)
                        continue

            time.sleep(poll)
    finally:
        if child is not None and child.poll() is None:
            log.info("Watchdog stopping; terminating operator (pid=%s).", child.pid)
            _kill_process_tree(child.pid, log)
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Watchdog interrupted.", file=sys.stderr)
        raise SystemExit(130)
