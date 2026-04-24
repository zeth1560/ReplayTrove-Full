"""Periodic machine-level metrics into system.jsonl."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from replaytrove_logging.day_index import bump_index
from replaytrove_logging.paths import service_jsonl, timeline_jsonl, utc_day_str
from replaytrove_logging.schema import STANDARD_TYPE_SYSTEM_HEARTBEAT, build_record, dumps_record
from replaytrove_logging.session import get_session_id
from replaytrove_logging.win_lock import global_log_write_lock

_LOG = logging.getLogger(__name__)


def _metrics_snapshot() -> dict:
    out: dict = {}
    try:
        import psutil  # type: ignore

        out["cpu_percent"] = psutil.cpu_percent(interval=0.15)
        vm = psutil.virtual_memory()
        out["memory_percent"] = vm.percent
        out["memory_used_bytes"] = vm.used
        out["memory_total_bytes"] = vm.total
        try:
            du = psutil.disk_usage("C:\\")
            out["disk_c_percent"] = du.percent
            out["disk_c_free_bytes"] = du.free
            out["disk_c_total_bytes"] = du.total
        except OSError:
            pass
        out["boot_time_unix"] = psutil.boot_time()
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                out["temperature_c"] = {
                    k: [x.current for x in v if x.current is not None]
                    for k, v in temps.items()
                    if v
                }
        except Exception:
            pass
    except Exception as exc:
        out["collector_error"] = str(exc)
    return out


def _loop(logs_root: Path, interval_sec: float) -> None:
    logs_root = Path(logs_root)
    service_name = "system"
    while True:
        try:
            day = utc_day_str()
            ts = datetime.now(timezone.utc).isoformat()
            metrics = _metrics_snapshot()
            rec = build_record(
                timestamp=ts,
                level="INFO",
                service=service_name,
                event="heartbeat",
                message="system heartbeat",
                session_id=get_session_id(),
                metrics=metrics,
                state={"uptime_writer_sleep_sec": interval_sec},
                type=STANDARD_TYPE_SYSTEM_HEARTBEAT,
            )
            line = dumps_record(rec)
            svc_path = service_jsonl(logs_root, day, service_name)
            tl_path = timeline_jsonl(logs_root, day)
            idx_path = logs_root / day / "index.json"
            with global_log_write_lock():
                svc_path.parent.mkdir(parents=True, exist_ok=True)
                with open(svc_path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                with open(tl_path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                bump_index(
                    idx_path,
                    day=day,
                    timestamp=ts,
                    service=service_name,
                    level="INFO",
                    event="heartbeat",
                )
        except Exception:
            _LOG.debug("system heartbeat failed", exc_info=True)
        time.sleep(max(5.0, interval_sec))


def start_system_heartbeat_thread(
    logs_root: Path,
    *,
    interval_sec: float = 20.0,
) -> None:
    t = threading.Thread(
        target=_loop,
        args=(Path(logs_root), interval_sec),
        name="rt_system_heartbeat",
        daemon=True,
    )
    t.start()
