"""
Local HTTP endpoint so encoder_watchdog can ask the operator process whether it is
alive and whether it wants an external restart — without inferring that only from
encoder_state.json (which can be temporarily unreadable on Windows).
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

GetPayload = Callable[[], dict[str, Any]]


def _make_handler(get_payload: GetPayload) -> type[BaseHTTPRequestHandler]:
    class WatchdogPingHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0].rstrip("/")
            if path != "/watchdog":
                self.send_error(404, "Not Found")
                return
            try:
                payload = get_payload()
                body = json.dumps(payload, sort_keys=False).encode("utf-8")
            except Exception as exc:
                self.send_error(500, str(exc))
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    return WatchdogPingHandler


def start_watchdog_ping_server_thread(
    get_payload: GetPayload,
    host: str,
    port: int,
    log: logging.Logger,
) -> None:
    if port <= 0:
        return

    def run() -> None:
        handler = _make_handler(get_payload)
        try:
            httpd = ThreadingHTTPServer((host, port), handler)
        except OSError as exc:
            log.error(
                "Watchdog ping server failed to bind http://%s:%s — %s",
                host,
                port,
                exc,
            )
            return
        log.info(
            "Watchdog ping server listening on http://%s:%s/watchdog",
            host,
            port,
        )
        httpd.serve_forever()

    threading.Thread(
        target=run,
        daemon=True,
        name="encoder-watchdog-ping",
    ).start()
