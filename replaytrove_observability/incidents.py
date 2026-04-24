"""
Incident detection: tail ``timeline.jsonl``, evaluate configurable rules, write incidents + daily summary.

Optional hook: ``IncidentEngine(..., on_incident_detected=callable)`` for UI / webhooks.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from replaytrove_observability.baseline import BaselineEngine
from replaytrove_logging.paths import day_dir, timeline_jsonl, utc_day_str
from replaytrove_logging.schema import STANDARD_TYPE_SYSTEM_HEARTBEAT
from replaytrove_logging.win_lock import global_log_write_lock

_LOG = logging.getLogger(__name__)

IncidentCallback = Callable[[dict[str, Any]], None]

INCIDENT_TYPES = frozenset(
    {
        "replay_stuck",
        "encoder_overload",
        "worker_stall",
        "upload_failure",
        "high_cpu",
        "replay_performance_degradation",
    }
)


def resolve_logs_root() -> Path:
    raw = os.environ.get("REPLAYTROVE_LOGS_ROOT", "").strip()
    if raw:
        return Path(raw)
    root = os.environ.get("REPLAYTROVE_ROOT", "").strip()
    if root:
        return Path(root) / "logs"
    return Path(r"C:\ReplayTrove\logs")


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _evidence_snippet(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": rec.get("timestamp"),
        "service": rec.get("service"),
        "event": rec.get("event"),
        "type": rec.get("type"),
        "message": (rec.get("message") or "")[:500],
        "correlation_id": rec.get("correlation_id"),
        "session_id": rec.get("session_id"),
        "clip_id": rec.get("clip_id"),
        "metrics": rec.get("metrics") or {},
    }


def _severity_for_type(incident_type: str) -> str:
    if incident_type in ("replay_stuck", "high_cpu"):
        return "critical"
    if incident_type in ("worker_stall", "upload_failure"):
        return "high"
    if incident_type == "replay_performance_degradation":
        return "high"
    if incident_type == "encoder_overload":
        return "medium"
    return "medium"


def _default_actions(incident_type: str) -> list[str]:
    if incident_type == "encoder_overload":
        return [
            "Lower encoder bitrate or output resolution.",
            "Enable or verify hardware acceleration (NVENC / QuickSync / AMF).",
            "Close competing CPU-heavy processes on the encoder host.",
        ]
    if incident_type == "replay_stuck":
        return [
            "Verify OBS replay buffer is enabled and long enough for your scene complexity.",
            "Confirm Stream Deck / Companion / HTTP trigger reaches the worker replay endpoint.",
            "Check worker logs for replay-buffer stage errors immediately after replay_started.",
        ]
    if incident_type == "upload_failure":
        return [
            "Verify network connectivity and DNS from the worker host.",
            "Validate AWS credentials, bucket policy, and region configuration.",
            "Check for S3 service status or throttling (HTTP 503/429) in surrounding logs.",
        ]
    if incident_type == "worker_stall":
        return [
            "Inspect worker thread dumps / hung ffmpeg processes.",
            "Check for disk-full or AV locking files under incoming/processing folders.",
            "Review Supabase and network health if the stall happens after uploads.",
        ]
    if incident_type == "high_cpu":
        return [
            "Identify top CPU consumers (encoder ffmpeg, worker ffmpeg, browser, updates).",
            "Reduce concurrent work (long-clip concurrency, preview generation).",
            "Consider stronger hardware or process isolation for encoder vs worker.",
        ]
    if incident_type == "replay_performance_degradation":
        return [
            "Reduce encoder load: bitrate/resolution, and check hardware acceleration.",
            "Inspect queue depth and upload latency for downstream backpressure.",
            "Compare current baseline.json against anomalies.jsonl for the exact metric drift.",
        ]
    return ["Review correlated timeline events and worker/encoder configuration."]


class Rule(Protocol):
    name: str

    def on_event(self, engine: IncidentEngine, rec: dict[str, Any], now: datetime) -> None:
        ...

    def tick(self, engine: IncidentEngine, now: datetime) -> None:
        ...


@dataclass
class PendingReplay:
    started_at: datetime
    session_id: str | None
    correlation_id: str
    evidence: dict[str, Any]


@dataclass
class PendingWorker:
    started_at: datetime
    session_id: str | None
    correlation_id: str
    evidence: dict[str, Any]


@dataclass
class IncidentEngine:
    """
    Tails today's ``timeline.jsonl`` (rolls over at UTC midnight), evaluates rules, appends incidents.

    Thread-safe for a single engine instance per process (one tail loop recommended).
    """

    logs_root: Path
    poll_interval_sec: float = 0.5
    correlation_window_sec: float = 10.0
    on_incident_detected: IncidentCallback | None = None
    rules: list[Rule] = field(default_factory=list)
    baseline_engine: BaselineEngine | None = None

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _tail_day: str = ""
    _tail_offset: int = 0
    _pending_replay: dict[str, PendingReplay] = field(default_factory=dict)
    _pending_worker: dict[str, PendingWorker] = field(default_factory=dict)
    _encoder_hits: deque[tuple[datetime, dict[str, Any]]] = field(default_factory=deque)
    _upload_hits: deque[tuple[datetime, dict[str, Any]]] = field(default_factory=deque)
    _cpu_high_since: datetime | None = None
    _recent_incident_keys: dict[str, float] = field(default_factory=dict)
    _anomaly_hits: deque[tuple[datetime, dict[str, Any]]] = field(default_factory=deque)
    _degraded_until: datetime | None = None
    _baseline_freeze_until: datetime | None = None

    def __post_init__(self) -> None:
        if self.baseline_engine is None:
            self.baseline_engine = BaselineEngine(
                logs_root=self.logs_root,
                on_anomaly_detected=self._on_anomaly_detected,
                normal_mode_provider=self._is_normal_mode,
            )
        if not self.rules:
            self.rules = [
                _ReplayStuckRule(),
                _EncoderOverloadRule(),
                _WorkerStallRule(),
                _UploadFailureLoopRule(),
                _HighCpuRule(),
                _PerformanceDegradationRule(),
            ]

    def _is_normal_mode(self) -> bool:
        now = datetime.now(timezone.utc)
        if self._baseline_freeze_until is not None and now < self._baseline_freeze_until:
            return False
        if self._degraded_until is not None and now < self._degraded_until:
            return False
        return True

    def _mark_degraded(self, *, seconds: float = 120.0) -> None:
        now = datetime.now(timezone.utc)
        until = now + timedelta(seconds=max(1.0, seconds))
        if self._degraded_until is None or until > self._degraded_until:
            self._degraded_until = until

    def _on_anomaly_detected(self, anomaly: dict[str, Any]) -> None:
        ts = _parse_ts(anomaly.get("timestamp")) or datetime.now(timezone.utc)
        self._anomaly_hits.append((ts, anomaly))

    def _dedupe_ok(self, key: str, cooldown_sec: float = 120.0) -> bool:
        now = time.monotonic()
        stale = [k for k, t in self._recent_incident_keys.items() if now - t > cooldown_sec * 2]
        for k in stale:
            self._recent_incident_keys.pop(k, None)
        if key in self._recent_incident_keys and now - self._recent_incident_keys[key] < cooldown_sec:
            return False
        self._recent_incident_keys[key] = now
        return True

    def _correlation_from(self, rec: dict[str, Any]) -> str | None:
        cid = rec.get("correlation_id")
        if isinstance(cid, str) and cid.strip():
            return cid.strip()
        st = rec.get("state") if isinstance(rec.get("state"), dict) else {}
        nested = st.get("structured") if isinstance(st.get("structured"), dict) else {}
        for key in ("correlation_id", "request_id"):
            v = nested.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    def _session_from(self, rec: dict[str, Any]) -> str | None:
        s = rec.get("session_id")
        return str(s) if s else None

    def emit(
        self,
        *,
        incident_type: str,
        severity: str | None,
        summary: str,
        root_cause_hint: str,
        evidence: list[dict[str, Any]],
        correlation_id: str | None,
        session_id: str | None,
        recommended_actions: list[str] | None = None,
        confidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if incident_type not in INCIDENT_TYPES:
            _LOG.warning("Unknown incident_type %r; emitting anyway", incident_type)
        sev = severity or _severity_for_type(incident_type)
        actions = recommended_actions if recommended_actions is not None else _default_actions(incident_type)
        inc_id = str(uuid.uuid4())
        day = utc_day_str()
        ts = datetime.now(timezone.utc).isoformat()
        body: dict[str, Any] = {
            "timestamp": ts,
            "type": "incident",
            "incident_id": inc_id,
            "incident_type": incident_type,
            "severity": sev,
            "correlation_id": correlation_id,
            "session_id": session_id,
            "summary": summary,
            "root_cause_hint": root_cause_hint,
            "evidence": evidence,
            "recommended_actions": actions,
            "confidence": confidence
            if isinstance(confidence, dict)
            else {
                "root_cause": root_cause_hint,
                "confidence": 0.55,
            },
        }
        path = day_dir(self.logs_root, day) / "incidents.jsonl"
        with global_log_write_lock():
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(body, ensure_ascii=False, default=str) + "\n")
            self._update_summary_locked(day, incident_type, sev)

        if sev in ("critical", "high"):
            self._baseline_freeze_until = datetime.now(timezone.utc) + timedelta(seconds=180)

        if self.on_incident_detected is not None:
            try:
                self.on_incident_detected(dict(body))
            except Exception:
                _LOG.exception("on_incident_detected callback failed")
        return body

    def _update_summary_locked(self, day: str, incident_type: str, severity: str) -> None:
        summary_path = day_dir(self.logs_root, day) / "incidents_summary.json"
        cur: dict[str, Any] = {
            "day": day,
            "total_incidents": 0,
            "by_type": {},
            "critical_count": 0,
            "top_issue": "",
            "system_health_score": 100,
        }
        if summary_path.is_file():
            try:
                cur = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        cur["total_incidents"] = int(cur.get("total_incidents", 0)) + 1
        by_t = dict(cur.get("by_type") or {})
        by_t[incident_type] = int(by_t.get(incident_type, 0)) + 1
        cur["by_type"] = by_t
        if severity == "critical":
            cur["critical_count"] = int(cur.get("critical_count", 0)) + 1
        top = max(by_t.items(), key=lambda kv: kv[1])[0] if by_t else ""
        cur["top_issue"] = top
        total = int(cur["total_incidents"])
        crit = int(cur.get("critical_count", 0))
        cur["system_health_score"] = max(0, min(100, int(100 - min(100, total * 4 + crit * 15))))
        summary_path.write_text(json.dumps(cur, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def process_record(self, rec: dict[str, Any]) -> None:
        now = _parse_ts(rec.get("timestamp")) or datetime.now(timezone.utc)
        with self._lock:
            event = str(rec.get("event") or "")
            if event in ("HEALTH_DEGRADED", "encoding_overload_detected"):
                self._mark_degraded(seconds=120)
            elif event in ("HEALTH_RECOVERED",):
                self._degraded_until = now
            if self.baseline_engine is not None:
                self.baseline_engine.process_record(rec)
            for rule in self.rules:
                rule.on_event(self, rec, now)
                rule.tick(self, now)

    def tick(self) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            if self.baseline_engine is not None:
                self.baseline_engine.tick()
            for rule in self.rules:
                rule.tick(self, now)

    def _read_new_lines(self) -> list[dict[str, Any]]:
        day = utc_day_str()
        path = timeline_jsonl(self.logs_root, day)
        if day != self._tail_day:
            self._tail_day = day
            self._tail_offset = 0
        if not path.is_file():
            return []
        try:
            size = path.stat().st_size
        except OSError:
            return []
        if size < self._tail_offset:
            self._tail_offset = 0
        out: list[dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(self._tail_offset)
                chunk = fh.read()
                self._tail_offset = fh.tell()
        except OSError:
            return []
        for line in chunk.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def run_loop(self, stop: threading.Event | None = None) -> None:
        _LOG.info("Incident engine started (logs_root=%s)", self.logs_root)
        while stop is None or not stop.is_set():
            lines = self._read_new_lines()
            for rec in lines:
                self.process_record(rec)
            self.tick()
            if stop is not None:
                if stop.wait(timeout=self.poll_interval_sec):
                    break
            else:
                time.sleep(self.poll_interval_sec)
        _LOG.info("Incident engine stopped")


class _ReplayStuckRule:
    name = "replay_stuck"

    def on_event(self, engine: IncidentEngine, rec: dict[str, Any], now: datetime) -> None:
        ev = rec.get("event")
        cid = engine._correlation_from(rec) or engine._session_from(rec) or "global"
        if ev == "replay_started":
            engine._pending_replay[cid] = PendingReplay(
                started_at=now,
                session_id=engine._session_from(rec),
                correlation_id=cid,
                evidence=_evidence_snippet(rec),
            )
        elif ev == "replay_completed":
            engine._pending_replay.pop(cid, None)

    def tick(self, engine: IncidentEngine, now: datetime) -> None:
        deadline = timedelta(seconds=10)
        fired: list[str] = []
        for cid, p in list(engine._pending_replay.items()):
            if now - p.started_at >= deadline:
                key = f"replay_stuck:{cid}:{int(p.started_at.timestamp())}"
                if engine._dedupe_ok(key, 30):
                    engine.emit(
                        incident_type="replay_stuck",
                        severity="critical",
                        summary=(
                            f"Replay started at {p.started_at.strftime('%H:%M:%S')} "
                            f"but no replay_completed within 10s (correlation {cid})."
                        ),
                        root_cause_hint=_hint_replay_stuck(engine, p.evidence),
                        evidence=[p.evidence],
                        correlation_id=None if cid == "global" else cid,
                        session_id=p.session_id,
                    )
                fired.append(cid)
        for cid in fired:
            engine._pending_replay.pop(cid, None)


class _EncoderOverloadRule:
    name = "encoder_overload"
    window = timedelta(seconds=60)
    need = 3

    def on_event(self, engine: IncidentEngine, rec: dict[str, Any], now: datetime) -> None:
        ev = rec.get("event")
        if ev != "encoding_overload_detected":
            return
        engine._encoder_hits.append((now, _evidence_snippet(rec)))
        while engine._encoder_hits and now - engine._encoder_hits[0][0] > self.window:
            engine._encoder_hits.popleft()

    def tick(self, engine: IncidentEngine, now: datetime) -> None:
        while engine._encoder_hits and now - engine._encoder_hits[0][0] > self.window:
            engine._encoder_hits.popleft()
        if len(engine._encoder_hits) < self.need:
            return
        evs = [t[1] for t in engine._encoder_hits]
        t0 = engine._encoder_hits[0][0]
        t1 = engine._encoder_hits[-1][0]
        key = f"encoder_overload:{int(t1.timestamp())}"
        if not engine._dedupe_ok(key, 60):
            return
        cid = evs[-1].get("correlation_id") if evs else None
        sid = evs[-1].get("session_id") if evs else None
        engine.emit(
            incident_type="encoder_overload",
            severity="medium",
            summary=(
                f"Encoder reported overload {len(engine._encoder_hits)} times "
                f"between {t0.strftime('%H:%M:%S')} and {t1.strftime('%H:%M:%S')}."
            ),
            root_cause_hint=_hint_encoder_cpu(engine, now),
            evidence=evs[-5:],
            correlation_id=cid if isinstance(cid, str) else None,
            session_id=sid if isinstance(sid, str) else None,
        )
        engine._encoder_hits.clear()


class _WorkerStallRule:
    name = "worker_stall"
    deadline = timedelta(seconds=60)

    def on_event(self, engine: IncidentEngine, rec: dict[str, Any], now: datetime) -> None:
        ev = rec.get("event")
        cid = engine._correlation_from(rec)
        if ev == "clip_processing_started":
            if not cid:
                cid = f"time:{engine._session_from(rec) or 'unknown'}:{int(now.timestamp())}"
            engine._pending_worker[cid] = PendingWorker(
                started_at=now,
                session_id=engine._session_from(rec),
                correlation_id=cid,
                evidence=_evidence_snippet(rec),
            )
        elif ev == "clip_processing_completed":
            c = cid
            if c:
                engine._pending_worker.pop(c, None)
            st = rec.get("state") if isinstance(rec.get("state"), dict) else {}
            nested = st.get("structured") if isinstance(st.get("structured"), dict) else {}
            job = nested.get("job_uuid")
            if isinstance(job, str):
                engine._pending_worker.pop(job, None)

    def tick(self, engine: IncidentEngine, now: datetime) -> None:
        fired: list[str] = []
        for cid, p in list(engine._pending_worker.items()):
            if now - p.started_at >= self.deadline:
                key = f"worker_stall:{cid}:{int(p.started_at.timestamp())}"
                if engine._dedupe_ok(key, 60):
                    engine.emit(
                        incident_type="worker_stall",
                        severity="high",
                        summary=(
                            f"clip_processing_started for {cid} at {p.started_at.strftime('%H:%M:%S')} "
                            f"with no clip_processing_completed within 60s."
                        ),
                        root_cause_hint=_hint_worker_stall(engine, p.started_at, now),
                        evidence=[p.evidence],
                        correlation_id=None if cid.startswith("time:") else cid,
                        session_id=p.session_id,
                    )
                fired.append(cid)
        for cid in fired:
            engine._pending_worker.pop(cid, None)


class _UploadFailureLoopRule:
    name = "upload_failure"
    window = timedelta(seconds=120)
    need = 3

    def on_event(self, engine: IncidentEngine, rec: dict[str, Any], now: datetime) -> None:
        if rec.get("event") != "upload_failed":
            return
        engine._upload_hits.append((now, _evidence_snippet(rec)))
        while engine._upload_hits and now - engine._upload_hits[0][0] > self.window:
            engine._upload_hits.popleft()

    def tick(self, engine: IncidentEngine, now: datetime) -> None:
        while engine._upload_hits and now - engine._upload_hits[0][0] > self.window:
            engine._upload_hits.popleft()
        if len(engine._upload_hits) < self.need:
            return
        evs = [t[1] for t in engine._upload_hits]
        key = f"upload_loop:{int(engine._upload_hits[-1][0].timestamp())}"
        if not engine._dedupe_ok(key, 120):
            return
        engine.emit(
            incident_type="upload_failure",
            severity="high",
            summary=f"{len(engine._upload_hits)} upload_failed events within 2 minutes — possible upload/network loop.",
            root_cause_hint=_hint_upload_failures(evs),
            evidence=evs[-5:],
            correlation_id=None,
            session_id=evs[-1].get("session_id") if evs else None,
        )
        engine._upload_hits.clear()


class _HighCpuRule:
    name = "high_cpu"
    threshold = 90.0
    sustain = timedelta(seconds=30)

    def on_event(self, engine: IncidentEngine, rec: dict[str, Any], now: datetime) -> None:
        if rec.get("type") != STANDARD_TYPE_SYSTEM_HEARTBEAT:
            return
        metrics = rec.get("metrics") if isinstance(rec.get("metrics"), dict) else {}
        cpu = metrics.get("cpu_percent")
        try:
            cpu_f = float(cpu)
        except (TypeError, ValueError):
            engine._cpu_high_since = None
            return
        if cpu_f > self.threshold:
            if engine._cpu_high_since is None:
                engine._cpu_high_since = now
        else:
            engine._cpu_high_since = None

    def tick(self, engine: IncidentEngine, now: datetime) -> None:
        if engine._cpu_high_since is None:
            return
        if now - engine._cpu_high_since < self.sustain:
            return
        key = f"high_cpu:{int(engine._cpu_high_since.timestamp())}"
        if not engine._dedupe_ok(key, 300):
            engine._cpu_high_since = now
            return
        engine.emit(
            incident_type="high_cpu",
            severity="critical",
            summary=f"system_heartbeat: CPU stayed above {self.threshold}% for {self.sustain.total_seconds():.0f}s.",
            root_cause_hint=_hint_encoder_cpu(engine, now),
            evidence=[
                {
                    "timestamp": now.isoformat(),
                    "cpu_high_since": engine._cpu_high_since.isoformat(),
                }
            ],
            correlation_id=None,
            session_id=None,
        )
        engine._cpu_high_since = None


def _performance_confidence(engine: IncidentEngine, anomalies: list[dict[str, Any]]) -> dict[str, Any]:
    signals: set[str] = {str(a.get("metric") or "") for a in anomalies}
    if engine._cpu_high_since is not None:
        signals.add("cpu_percent")
    if engine._encoder_hits:
        signals.add("encoding_overload_detected")
    base = 0.45 + min(0.45, 0.08 * len(signals))
    if len(anomalies) >= 5:
        base += 0.08
    confidence = max(0.0, min(1.0, base))
    root = "performance drift from baseline"
    if "cpu_percent" in signals and ("output_fps" in signals or "encoding_duration_ms" in signals):
        root = "CPU bottleneck during encoding"
    elif "upload_duration_ms" in signals:
        root = "downstream upload latency causing replay pipeline backpressure"
    elif "queue_depth" in signals:
        root = "processing backlog growth"
    return {"root_cause": root, "confidence": confidence}


class _PerformanceDegradationRule:
    name = "replay_performance_degradation"
    window = timedelta(seconds=60)
    need = 3

    def on_event(self, engine: IncidentEngine, rec: dict[str, Any], now: datetime) -> None:
        _ = (engine, rec, now)

    def tick(self, engine: IncidentEngine, now: datetime) -> None:
        while engine._anomaly_hits and now - engine._anomaly_hits[0][0] > self.window:
            engine._anomaly_hits.popleft()
        if len(engine._anomaly_hits) < self.need:
            return

        anomalies = [x[1] for x in engine._anomaly_hits]
        fps_count = sum(1 for a in anomalies if str(a.get("metric")) == "output_fps")
        hot_count = sum(1 for a in anomalies if str(a.get("metric")) in ("cpu_percent", "encoding_duration_ms"))
        if fps_count < 1:
            return

        last_ts = engine._anomaly_hits[-1][0]
        key = f"replay_perf_deg:{int(last_ts.timestamp())}"
        if not engine._dedupe_ok(key, 90):
            return

        sev = "medium"
        if len(anomalies) >= 5 or (fps_count >= 3 and hot_count >= 2):
            sev = "high"
        if len(anomalies) >= 8:
            sev = "critical"

        conf = _performance_confidence(engine, anomalies)
        engine.emit(
            incident_type="replay_performance_degradation",
            severity=sev,
            summary=(
                f"{len(anomalies)} baseline anomalies in 60s "
                f"({fps_count} output_fps-related) indicate replay performance degradation."
            ),
            root_cause_hint=str(conf.get("root_cause") or "performance drift from baseline"),
            evidence=anomalies[-8:],
            correlation_id=None,
            session_id=None,
            confidence=conf,
        )
        engine._anomaly_hits.clear()


def _hint_encoder_cpu(engine: IncidentEngine, now: datetime) -> str:
    if engine._encoder_hits:
        return "CPU bottleneck during encoding or heavy concurrent work on this host."
    return "Sustained CPU pressure — check encoder, worker ffmpeg, and background processes."


def _hint_replay_stuck(engine: IncidentEngine, start_ev: dict[str, Any]) -> str:
    _ = start_ev
    if not engine._encoder_hits:
        return "OBS replay buffer or trigger failure (no encoder overload pattern nearby)."
    return "Replay may be stalled while encoder or disk path is under stress."


def _hint_worker_stall(engine: IncidentEngine, started: datetime, now: datetime) -> str:
    _ = (engine, started, now)
    return "Possible deadlock, blocked I/O, or hung ffmpeg — CPU may be idle if a thread is stuck."


def _hint_upload_failures(evs: list[dict[str, Any]]) -> str:
    blob = json.dumps(evs, default=str).lower()
    if any(x in blob for x in ("timeout", "timed out", "connection", "reset", "slow down")):
        return "Network instability or S3 service issue (timeouts / connection errors in evidence)."
    if any(x in blob for x in ("accessdenied", "invalidaccesskey", "signature", "403", "401")):
        return "AWS credentials or bucket permissions may be misconfigured."
    return "Repeated upload failures — verify network path and object storage configuration."


def _merge_root_cause(base: str, extra: str) -> str:
    if extra and extra not in base:
        return f"{base} {extra}".strip()
    return base


def generate_incident_report(incident_id: str, *, logs_root: Path | None = None) -> str:
    """
    Load the incident by id, pull correlated ``timeline.jsonl`` rows (±10s and matching correlation_id),
    and return a short narrative plus heuristic root cause.
    """
    root = Path(logs_root) if logs_root is not None else resolve_logs_root()
    incident: dict[str, Any] | None = None
    incident_day: str | None = None
    if not root.is_dir():
        return f"Logs root {root} does not exist."
    for day_dir_path in sorted(root.iterdir(), reverse=True):
        if not day_dir_path.is_dir():
            continue
        inc_path = day_dir_path / "incidents.jsonl"
        if not inc_path.is_file():
            continue
        try:
            lines = inc_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(obj.get("incident_id")) == incident_id:
                incident = obj
                incident_day = day_dir_path.name
                break
        if incident is not None:
            break
    if incident is None:
        return f"Incident {incident_id!r} not found under {root}."

    cid = incident.get("correlation_id")
    center = _parse_ts(str(incident.get("timestamp"))) or datetime.now(timezone.utc)
    window = timedelta(seconds=10)
    start = center - window
    end = center + window

    timeline_path = timeline_jsonl(root, incident_day or utc_day_str(center))
    related: list[dict[str, Any]] = []
    if timeline_path.is_file():
        try:
            with open(timeline_path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = _parse_ts(rec.get("timestamp"))
                    if ts is None:
                        continue
                    if cid and rec.get("correlation_id") == cid:
                        related.append(rec)
                    elif not cid and start <= ts <= end:
                        related.append(rec)
        except OSError:
            pass

    related.sort(key=lambda r: (r.get("timestamp") or ""))

    lines_out: list[str] = []
    inc_type = str(incident.get("incident_type", ""))
    summary = str(incident.get("summary", ""))
    lines_out.append(f"Incident {incident_id} ({inc_type}).")
    lines_out.append(summary)

    replay_started = [r for r in related if r.get("event") == "replay_started"]
    replay_done = [r for r in related if r.get("event") == "replay_completed"]
    overload = [r for r in related if r.get("event") == "encoding_overload_detected"]
    heartbeats_hi = []
    for r in related:
        if r.get("type") != STANDARD_TYPE_SYSTEM_HEARTBEAT:
            continue
        m = r.get("metrics") or {}
        try:
            if float(m.get("cpu_percent", 0)) > 90:
                heartbeats_hi.append(r)
        except (TypeError, ValueError):
            continue
    uploads = [r for r in related if r.get("event") == "upload_failed"]

    if replay_started:
        ts0 = replay_started[0].get("timestamp", "")
        lines_out.append(f"Replay started at {_format_hms(ts0)}.")
    if overload:
        lines_out.append(f"Encoder reported overload {len(overload)} time(s) in the correlation window.")
    if heartbeats_hi:
        cpu_max = max(
            float((r.get("metrics") or {}).get("cpu_percent", 0) or 0) for r in heartbeats_hi
        )
        lines_out.append(f"CPU reached {cpu_max:.0f}% during the window.")
    if replay_done:
        ok = any(
            (r.get("state") or {}).get("structured", {}).get("outcome") == "success"
            for r in replay_done
            if isinstance(r.get("state"), dict)
        )
        if ok:
            lines_out.append("Replay pipeline reported completion.")
        else:
            lines_out.append("Replay completed with non-success outcome logged.")
    elif replay_started:
        lines_out.append("Replay never completed in the correlated timeline slice.")
    if uploads:
        lines_out.append(f"{len(uploads)} upload_failed event(s) in window.")

    hint = str(incident.get("root_cause_hint", ""))
    extra = ""
    if overload and heartbeats_hi:
        extra = _merge_root_cause(extra, "CPU bottleneck during encoding")
    elif inc_type == "encoder_overload" or heartbeats_hi:
        extra = _merge_root_cause(extra, "CPU bottleneck during encoding" if overload or heartbeats_hi else "")
    if inc_type == "replay_stuck" and not overload:
        extra = _merge_root_cause(extra, "OBS replay buffer or trigger failure")
    if uploads and "network" in _hint_upload_failures([_evidence_snippet(r) for r in uploads]).lower():
        extra = _merge_root_cause(extra, "network instability or S3 issue")
    if inc_type == "worker_stall" and not heartbeats_hi:
        extra = _merge_root_cause(extra, "deadlock or blocked IO")

    narrative_hint = _merge_root_cause(hint, extra).strip()
    lines_out.append(f"Likely cause: {narrative_hint}" if narrative_hint else "Likely cause: see evidence and recommended_actions on the incident record.")

    lines_out.append("Recommended actions:")
    for a in incident.get("recommended_actions") or []:
        lines_out.append(f"- {a}")
    return "\n".join(lines_out)


def _format_hms(ts: str) -> str:
    p = _parse_ts(ts)
    if p is None:
        return ts
    return p.strftime("%H:%M:%S")


def start_incident_engine_background(
    logs_root: Path | None = None,
    *,
    stop: threading.Event,
    on_incident_detected: IncidentCallback | None = None,
) -> threading.Thread:
    root = Path(logs_root) if logs_root is not None else resolve_logs_root()
    eng = IncidentEngine(logs_root=root, on_incident_detected=on_incident_detected)
    t = threading.Thread(target=lambda: eng.run_loop(stop), name="replaytrove-incidents", daemon=True)
    t.start()
    return t
