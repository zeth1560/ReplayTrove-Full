from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

_LOG = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class BookingInfo:
    booking_id: str
    start_time: datetime | None
    end_time: datetime | None


@dataclass
class BookingOverlayState:
    active_booking_id: str = ""
    last_welcome_booking_id: str = ""
    last_goodbye_booking_id: str = ""
    last_seen_start_time: str = ""
    last_seen_end_time: str = ""

    def to_json(self) -> dict[str, str]:
        return {
            "active_booking_id": self.active_booking_id,
            "last_welcome_booking_id": self.last_welcome_booking_id,
            "last_goodbye_booking_id": self.last_goodbye_booking_id,
            "last_seen_start_time": self.last_seen_start_time,
            "last_seen_end_time": self.last_seen_end_time,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "BookingOverlayState":
        return cls(
            active_booking_id=str(raw.get("active_booking_id") or ""),
            last_welcome_booking_id=str(raw.get("last_welcome_booking_id") or ""),
            last_goodbye_booking_id=str(raw.get("last_goodbye_booking_id") or ""),
            last_seen_start_time=str(raw.get("last_seen_start_time") or ""),
            last_seen_end_time=str(raw.get("last_seen_end_time") or ""),
        )


class BookingOverlayPoller:
    def __init__(
        self,
        *,
        state_path: Path,
        poll_interval_sec: int,
        logger: logging.Logger | None,
        fetch_current_booking: Callable[[], BookingInfo | None],
        on_show_overlay: Callable[[str], str],
        on_warn: Callable[[str], None] | None = None,
    ) -> None:
        self._state_path = Path(state_path)
        self._poll_interval_sec = max(60, int(poll_interval_sec))
        self._log = logger or _LOG
        self._fetch_current_booking = fetch_current_booking
        self._on_show_overlay = on_show_overlay
        self._on_warn = on_warn
        self._state = self._load_state()

    @property
    def state(self) -> BookingOverlayState:
        return self._state

    def compute_next_delay_ms(self, now: datetime | None = None) -> int:
        n = now or _utc_now()
        # Keep polls near xx:00/xx:30 when interval is 30m; fallback to fixed interval otherwise.
        if self._poll_interval_sec == 1800:
            minute = n.minute
            anchor_minute = 30 if minute < 30 else 60
            next_boundary = n.replace(second=0, microsecond=0)
            if anchor_minute == 60:
                next_boundary = (next_boundary + timedelta(hours=1)).replace(minute=0)
            else:
                next_boundary = next_boundary.replace(minute=30)
            delay_sec = max(1.0, (next_boundary - n).total_seconds())
            return int(delay_sec * 1000)
        return int(self._poll_interval_sec * 1000)

    def set_fake_booking(self, booking: BookingInfo | None) -> None:
        self._apply_poll_result(booking, source="injector")

    def poll_once(self) -> None:
        self._log.info("booking_overlay_poll")
        try:
            booking = self._fetch_current_booking()
        except Exception as exc:
            self._log.warning("booking_overlay_poll warning=%s", exc)
            if self._on_warn is not None:
                self._on_warn(f"{exc}")
            return
        self._apply_poll_result(booking, source="poll")

    def apply_poll_result(self, booking: BookingInfo | None, *, source: str = "poll") -> None:
        self._apply_poll_result(booking, source=source)

    def _apply_poll_result(self, booking: BookingInfo | None, *, source: str) -> None:
        now = _utc_now()
        if booking is None or not booking.booking_id:
            self._handle_no_booking(now=now)
            return

        self._log.info(
            "booking_overlay_booking_found booking_id=%s start_time=%s end_time=%s source=%s",
            booking.booking_id,
            booking.start_time.isoformat() if booking.start_time else "",
            booking.end_time.isoformat() if booking.end_time else "",
            source,
        )
        self._state.active_booking_id = booking.booking_id
        self._state.last_seen_start_time = booking.start_time.isoformat() if booking.start_time else ""
        self._state.last_seen_end_time = booking.end_time.isoformat() if booking.end_time else ""

        if booking.booking_id != self._state.last_welcome_booking_id:
            outcome = self._on_show_overlay("welcome")
            if outcome == "shown":
                self._state.last_welcome_booking_id = booking.booking_id
                self._save_state()
                self._log.info("booking_overlay_welcome_shown booking_id=%s", booking.booking_id)
            elif outcome == "queued":
                self._log.info("booking_overlay_queued_for_replay overlay_type=welcome booking_id=%s", booking.booking_id)
            else:
                self._log.warning("booking_overlay_display_error overlay_type=welcome booking_id=%s", booking.booking_id)
        else:
            self._log.info("booking_overlay_skipped_duplicate overlay_type=welcome booking_id=%s", booking.booking_id)

        if booking.end_time is not None and now >= booking.end_time:
            if booking.booking_id != self._state.last_goodbye_booking_id:
                outcome = self._on_show_overlay("goodbye")
                if outcome == "shown":
                    self._state.last_goodbye_booking_id = booking.booking_id
                    self._save_state()
                    self._log.info("booking_overlay_goodbye_shown booking_id=%s", booking.booking_id)
                elif outcome == "queued":
                    self._log.info("booking_overlay_queued_for_replay overlay_type=goodbye booking_id=%s", booking.booking_id)
                else:
                    self._log.warning("booking_overlay_display_error overlay_type=goodbye booking_id=%s", booking.booking_id)
            else:
                self._log.info("booking_overlay_skipped_duplicate overlay_type=goodbye booking_id=%s", booking.booking_id)
        self._save_state()

    def _handle_no_booking(self, *, now: datetime) -> None:
        ended_dt = _parse_iso_utc(self._state.last_seen_end_time)
        active_booking_id = self._state.active_booking_id
        if (
            active_booking_id
            and ended_dt is not None
            and now >= ended_dt
            and active_booking_id != self._state.last_goodbye_booking_id
        ):
            outcome = self._on_show_overlay("goodbye")
            if outcome == "shown":
                self._state.last_goodbye_booking_id = active_booking_id
                self._log.info("booking_overlay_goodbye_shown booking_id=%s source=state", active_booking_id)
            elif outcome == "queued":
                self._log.info("booking_overlay_queued_for_replay overlay_type=goodbye booking_id=%s", active_booking_id)
            else:
                self._log.warning("booking_overlay_display_error overlay_type=goodbye booking_id=%s", active_booking_id)
        self._state.active_booking_id = ""
        self._save_state()

    def _load_state(self) -> BookingOverlayState:
        if not self._state_path.exists():
            return BookingOverlayState()
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return BookingOverlayState.from_json(raw)
        except Exception:
            self._log.warning("booking_overlay_display_error reason=state_load_failed", exc_info=True)
        return BookingOverlayState()

    def _save_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state.to_json(), ensure_ascii=True), encoding="utf-8")
        tmp.replace(self._state_path)


def fetch_current_booking_via_pickle_planner(
    *,
    match_url: str,
    api_key: str,
    api_key_header: str,
    club_id: str,
    court_id: str,
    timeout_sec: float = 10.0,
) -> BookingInfo | None:
    if not all([match_url, api_key, api_key_header, club_id, court_id]):
        raise RuntimeError("booking overlay polling is missing Pickle Planner configuration")

    now = _utc_now().isoformat().replace("+00:00", "Z")
    payload = {
        "recorded_at": now,
        "club_id": club_id,
        "court_id": court_id,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        match_url,
        method="POST",
        headers={
            "Content-Type": "application/json",
            api_key_header: api_key,
        },
        data=body,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if 400 <= exc.code < 500:
            raise RuntimeError(f"booking API returned HTTP {exc.code}") from exc
        raise RuntimeError(f"booking API transient HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"booking API connection failed: {exc.reason}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("booking API returned non-JSON response") from exc
    if not isinstance(data, dict):
        return None
    booking_id = str(data.get("booking_id") or "").strip()
    if not booking_id:
        return None
    return BookingInfo(
        booking_id=booking_id,
        start_time=_parse_iso_utc(str(data.get("start_time") or "")),
        end_time=_parse_iso_utc(str(data.get("end_time") or "")),
    )
