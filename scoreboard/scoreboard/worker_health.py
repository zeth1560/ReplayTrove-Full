"""Lightweight worker replay-trigger HTTP probe (same server as ``/replay``)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

_LOG = logging.getLogger(__name__)


def probe_worker_replay_trigger_http(
    host: str,
    port: int,
    *,
    timeout_sec: float = 1.25,
) -> bool:
    """Return True if ``GET /health`` returns JSON ``{ok: true, service: replay-trigger-http}``."""
    host = (host or "").strip() or "127.0.0.1"
    url = f"http://{host}:{int(port)}/health"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(
            req, timeout=max(0.5, float(timeout_sec))
        ) as resp:
            code = getattr(resp, "status", 200)
            if code != 200:
                return False
            raw = resp.read()
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            return False
        return bool(data.get("ok")) and data.get("service") == "replay-trigger-http"
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        _LOG.debug("worker replay-trigger http health failed: %s", exc)
        return False
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
        _LOG.debug("worker replay-trigger http health bad response: %s", exc)
        return False
