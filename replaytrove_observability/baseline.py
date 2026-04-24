"""
Baseline-aware performance modeling and anomaly detection.

Maintains rolling baselines for key metrics, writes ``baseline.json``, and emits
runtime anomalies to ``anomalies.jsonl``.
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from replaytrove_logging.paths import day_dir, utc_day_str
from replaytrove_logging.win_lock import global_log_write_lock

_LOG = logging.getLogger(__name__)

AnomalyCallback = Callable[[dict[str, Any]], None]
NormalModeProvider = Callable[[], bool]

TRACKED_METRICS = (
    "output_fps",
    "encoding_duration_ms",
    "replay_latency_ms",
    "upload_duration_ms",
    "cpu_percent",
    "queue_depth",
)


@dataclass
class FramePolicy:
    input_fps: float = 60.0
    output_fps: float = 30.0
    expected_drop_ratio: float = 0.5
    jitter_tolerance_fps: float = 2.0
    min_output_fps: float | None = None

    def output_floor(self) -> float:
        if self.min_output_fps is not None:
            return float(self.min_output_fps)
        return max(1.0, float(self.output_fps) * 0.9)


def _parse_ts(ts: Any) -> datetime:
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _to_float(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def _mean(values: list[float]) -> float:
    return sum(values) / float(len(values)) if values else 0.0


def _stddev(values: list[float], avg: float) -> float:
    if len(values) <= 1:
        return 0.0
    var = sum((v - avg) ** 2 for v in values) / float(len(values))
    return math.sqrt(max(0.0, var))


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(max(0, min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)))
    return float(ordered[idx])


def _extract_metrics(rec: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    metrics = rec.get("metrics") if isinstance(rec.get("metrics"), dict) else {}
    state = rec.get("state") if isinstance(rec.get("state"), dict) else {}
    structured = state.get("structured") if isinstance(state.get("structured"), dict) else {}

    for key in ("output_fps", "encoding_duration_ms", "replay_latency_ms", "upload_duration_ms", "cpu_percent", "queue_depth"):
        v = _to_float(metrics.get(key))
        if v is None:
            v = _to_float(structured.get(key))
        if v is not None:
            out[key] = v
    return out


@dataclass
class BaselineEngine:
    logs_root: Path
    window_size: int = 80
    batch_interval_sec: float = 1.5
    deviation_threshold: float = 0.25
    on_anomaly_detected: AnomalyCallback | None = None
    normal_mode_provider: NormalModeProvider | None = None

    _samples: dict[str, deque[float]] = field(default_factory=dict, init=False, repr=False)
    _baseline: dict[str, dict[str, float]] = field(default_factory=dict, init=False, repr=False)
    _pending: list[tuple[datetime, dict[str, Any], str, float]] = field(default_factory=list, init=False, repr=False)
    _last_batch_mono: float = field(default_factory=time.monotonic, init=False, repr=False)
    _frame_policy: FramePolicy = field(default_factory=FramePolicy, init=False, repr=False)
    _fps_window: deque[float] = field(default_factory=lambda: deque(maxlen=30), init=False, repr=False)

    def __post_init__(self) -> None:
        self.logs_root = Path(self.logs_root)
        self.window_size = max(50, min(200, int(self.window_size)))
        for metric in TRACKED_METRICS:
            self._samples[metric] = deque(maxlen=self.window_size)
            self._baseline[metric] = {"avg": 0.0, "p95": 0.0, "std_dev": 0.0}

    def process_record(self, rec: dict[str, Any]) -> None:
        now = _parse_ts(rec.get("timestamp"))
        event = str(rec.get("event") or "")

        if event == "frame_policy":
            self._update_frame_policy(rec)

        observed = _extract_metrics(rec)
        for metric, value in observed.items():
            self._emit_anomaly_if_needed(now, rec, metric, value)
            self._pending.append((now, rec, metric, value))
            if metric == "output_fps":
                self._fps_window.append(value)

    def tick(self) -> None:
        now_mono = time.monotonic()
        if now_mono - self._last_batch_mono < self.batch_interval_sec:
            return
        self._last_batch_mono = now_mono
        self._apply_pending_batch()
        self._write_baseline_snapshot()

    def snapshot(self) -> dict[str, dict[str, float]]:
        return {k: dict(v) for k, v in self._baseline.items()}

    def _is_normal_mode(self) -> bool:
        if self.normal_mode_provider is None:
            return True
        try:
            return bool(self.normal_mode_provider())
        except Exception:
            _LOG.exception("normal_mode_provider failed")
            return True

    def _apply_pending_batch(self) -> None:
        if not self._pending:
            return
        if not self._is_normal_mode():
            # Freeze adaptation in degraded/incident mode.
            self._pending.clear()
            return
        for _ts, _rec, metric, value in self._pending:
            self._samples[metric].append(value)
        self._pending.clear()
        for metric, dq in self._samples.items():
            vals = list(dq)
            if not vals:
                continue
            avg = _mean(vals)
            self._baseline[metric] = {
                "avg": avg,
                "p95": _p95(vals),
                "std_dev": _stddev(vals, avg),
            }

    def _write_baseline_snapshot(self) -> None:
        day = utc_day_str()
        out = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "window_size": self.window_size,
            "metrics": self.snapshot(),
        }
        path = day_dir(self.logs_root, day) / "baseline.json"
        with global_log_write_lock():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _update_frame_policy(self, rec: dict[str, Any]) -> None:
        source = rec.get("state") if isinstance(rec.get("state"), dict) else {}
        structured = source.get("structured") if isinstance(source.get("structured"), dict) else {}
        data = structured if structured else rec
        inp = _to_float(data.get("input_fps"))
        out = _to_float(data.get("output_fps"))
        drop = _to_float(data.get("expected_drop_ratio"))
        jitter_tol = _to_float(data.get("jitter_tolerance_fps"))
        floor = _to_float(data.get("min_output_fps"))
        if inp is not None:
            self._frame_policy.input_fps = inp
        if out is not None:
            self._frame_policy.output_fps = out
        if drop is not None:
            self._frame_policy.expected_drop_ratio = max(0.0, min(1.0, drop))
        if jitter_tol is not None:
            self._frame_policy.jitter_tolerance_fps = max(0.1, jitter_tol)
        if floor is not None:
            self._frame_policy.min_output_fps = max(1.0, floor)

    def _emit_anomaly_if_needed(self, now: datetime, rec: dict[str, Any], metric: str, actual: float) -> None:
        baseline = self._baseline.get(metric) or {"avg": 0.0, "p95": 0.0, "std_dev": 0.0}
        expected = float(baseline.get("avg") or 0.0)
        p95 = float(baseline.get("p95") or 0.0)
        deviation = 0.0
        if expected > 0:
            deviation = (actual - expected) / expected

        is_anomaly = False
        reason = ""

        if metric == "output_fps":
            floor = self._frame_policy.output_floor()
            jitter = _stddev(list(self._fps_window), _mean(list(self._fps_window))) if self._fps_window else 0.0
            if actual < floor:
                is_anomaly = True
                reason = f"output_fps below floor {floor:.2f}"
            elif jitter > self._frame_policy.jitter_tolerance_fps and len(self._fps_window) >= 8:
                is_anomaly = True
                reason = f"fps jitter {jitter:.2f} exceeds tolerance {self._frame_policy.jitter_tolerance_fps:.2f}"
        else:
            if expected > 0 and abs(deviation) > self.deviation_threshold:
                is_anomaly = True
                reason = f"deviation {deviation:.3f} exceeds threshold {self.deviation_threshold:.3f}"
            if p95 > 0 and actual > p95:
                is_anomaly = True
                reason = reason or f"value {actual:.3f} exceeds baseline p95 {p95:.3f}"

        if not is_anomaly:
            return

        severity = "low"
        mag = abs(deviation)
        if mag >= 0.5:
            severity = "high"
        elif mag >= 0.25:
            severity = "medium"

        correlation_id = rec.get("correlation_id")
        if not isinstance(correlation_id, str):
            correlation_id = None
        anomaly = {
            "timestamp": now.isoformat(),
            "type": "anomaly",
            "metric": metric,
            "expected": expected,
            "actual": actual,
            "deviation": deviation,
            "severity": severity,
            "correlation_id": correlation_id,
            "context": {
                "reason": reason,
                "baseline_p95": p95,
                "baseline_std_dev": float(baseline.get("std_dev") or 0.0),
                "frame_policy": {
                    "input_fps": self._frame_policy.input_fps,
                    "output_fps": self._frame_policy.output_fps,
                    "expected_drop_ratio": self._frame_policy.expected_drop_ratio,
                    "output_floor": self._frame_policy.output_floor(),
                    "jitter_tolerance_fps": self._frame_policy.jitter_tolerance_fps,
                }
                if metric == "output_fps"
                else {},
            },
        }
        self._write_anomaly(anomaly)
        if self.on_anomaly_detected is not None:
            try:
                self.on_anomaly_detected(dict(anomaly))
            except Exception:
                _LOG.exception("on_anomaly_detected callback failed")

    def _write_anomaly(self, anomaly: dict[str, Any]) -> None:
        day = utc_day_str()
        path = day_dir(self.logs_root, day) / "anomalies.jsonl"
        with global_log_write_lock():
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(anomaly, ensure_ascii=False, default=str) + "\n")

