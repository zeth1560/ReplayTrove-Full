"""
Local-only HTTP trigger for replay-buffer processing (stdlib, Windows-friendly).

Binds to loopback by default. Use GET (query params) for Stream Deck / simple launchers,
or POST with JSON body. Responses are JSON; include optional ``request_id`` for log correlation.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.parse
from dataclasses import asdict
from hmac import compare_digest
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable

logger = logging.getLogger(__name__)

ReplayPipeline = Callable[..., tuple[Any, int]]
CANONICAL_TRIGGER_SOURCE = "save_replay_and_trigger.ps1"
CANONICAL_TOKEN_HEADER = "X-Replay-Canonical-Token"


class ReplayTriggerHTTPServer(HTTPServer):
    """HTTPServer with a shared busy lock for one replay at a time."""

    busy_lock: threading.Lock

    def __init__(
        self,
        server_address: tuple[str, int],
        RequestHandlerClass: type[BaseHTTPRequestHandler],
        busy_lock: threading.Lock,
    ) -> None:
        self.busy_lock = busy_lock
        super().__init__(server_address, RequestHandlerClass)


def _make_handler_class(
    run_pipeline: ReplayPipeline,
    default_timeout: float,
    default_prefix: str,
    default_tolerance: float,
    expected_canonical_token: str | None,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            logger.debug("replay-trigger-http: %s", fmt % args)

        def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _parse_post_json(self) -> dict[str, Any] | None:
            length_s = self.headers.get("Content-Length", "0").strip()
            try:
                n = int(length_s)
            except ValueError:
                return None
            if n <= 0:
                return {}
            raw = self.rfile.read(n)
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
            if not isinstance(data, dict):
                return None
            return data

        def _params_from_query(self) -> dict[str, Any]:
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
            out: dict[str, Any] = {}
            if "trigger" in qs and qs["trigger"]:
                out["trigger"] = qs["trigger"][0]
            if "timeout" in qs and qs["timeout"]:
                try:
                    out["timeout"] = float(qs["timeout"][0])
                except ValueError:
                    out["timeout"] = None
            if "request_id" in qs and qs["request_id"]:
                out["request_id"] = qs["request_id"][0]
            if "correlation_id" in qs and qs["correlation_id"]:
                out["correlation_id"] = qs["correlation_id"][0]
            if "prefix" in qs and qs["prefix"]:
                out["prefix"] = qs["prefix"][0]
            if "tolerance" in qs and qs["tolerance"]:
                try:
                    out["tolerance"] = float(qs["tolerance"][0])
                except ValueError:
                    out["tolerance"] = None
            if "trigger_source" in qs and qs["trigger_source"]:
                out["trigger_source"] = qs["trigger_source"][0]
            if "canonical_token" in qs and qs["canonical_token"]:
                out["canonical_token"] = qs["canonical_token"][0]
            return out

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path in ("/health", "/healthz"):
                self._send_json(HTTPStatus.OK, {"ok": True, "service": "replay-trigger-http"})
                return
            if path not in ("/replay", "/"):
                self.send_error(HTTPStatus.NOT_FOUND.value, "Not Found")
                return

            q = self._params_from_query()
            trigger = q.get("trigger")
            if not trigger or not isinstance(trigger, str):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "success": False,
                        "failure_reason": "missing_trigger",
                        "message": "Provide trigger as query parameter (Unix time or ISO-8601)",
                    },
                )
                return

            timeout = q.get("timeout")
            if timeout is None:
                timeout = default_timeout
            elif not isinstance(timeout, (int, float)):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"success": False, "failure_reason": "invalid_timeout"},
                )
                return

            prefix = q.get("prefix") if isinstance(q.get("prefix"), str) else default_prefix
            tolerance = q.get("tolerance")
            if tolerance is None:
                tolerance = default_tolerance
            elif not isinstance(tolerance, (int, float)):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"success": False, "failure_reason": "invalid_tolerance"},
                )
                return

            request_id = q.get("request_id") if isinstance(q.get("request_id"), str) else None
            correlation_id = (
                q.get("correlation_id")
                if isinstance(q.get("correlation_id"), str)
                else request_id
            )
            trigger_source = (
                q.get("trigger_source")
                if isinstance(q.get("trigger_source"), str)
                else None
            )
            canonical_token = (
                q.get("canonical_token")
                if isinstance(q.get("canonical_token"), str)
                else None
            )
            header_token = self.headers.get(CANONICAL_TOKEN_HEADER, "").strip()
            if header_token:
                canonical_token = header_token
            self._run_and_respond(
                trigger_raw=trigger,
                timeout_seconds=float(timeout),
                request_id=request_id,
                correlation_id=correlation_id,
                trigger_source=trigger_source,
                canonical_token=canonical_token,
                filename_prefix=prefix,
                tolerance_seconds=float(tolerance),
            )

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path not in ("/replay", "/"):
                self.send_error(HTTPStatus.NOT_FOUND.value, "Not Found")
                return

            data = self._parse_post_json()
            if data is None:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"success": False, "failure_reason": "invalid_json_body"},
                )
                return

            trigger = data.get("trigger")
            if not trigger or not isinstance(trigger, str):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"success": False, "failure_reason": "missing_trigger"},
                )
                return

            timeout = data.get("timeout", default_timeout)
            try:
                timeout_f = float(timeout)
            except (TypeError, ValueError):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"success": False, "failure_reason": "invalid_timeout"},
                )
                return

            prefix = data.get("prefix", default_prefix)
            if not isinstance(prefix, str):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"success": False, "failure_reason": "invalid_prefix"},
                )
                return

            tolerance = data.get("tolerance", default_tolerance)
            try:
                tolerance_f = float(tolerance)
            except (TypeError, ValueError):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"success": False, "failure_reason": "invalid_tolerance"},
                )
                return

            request_id = data.get("request_id")
            if request_id is not None and not isinstance(request_id, str):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"success": False, "failure_reason": "invalid_request_id"},
                )
                return
            correlation_id = data.get("correlation_id")
            if correlation_id is not None and not isinstance(correlation_id, str):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"success": False, "failure_reason": "invalid_correlation_id"},
                )
                return
            if correlation_id is None:
                correlation_id = request_id
            trigger_source = data.get("trigger_source")
            if trigger_source is not None and not isinstance(trigger_source, str):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"success": False, "failure_reason": "invalid_trigger_source"},
                )
                return
            canonical_token = data.get("canonical_token")
            if canonical_token is not None and not isinstance(canonical_token, str):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"success": False, "failure_reason": "invalid_canonical_token"},
                )
                return
            header_token = self.headers.get(CANONICAL_TOKEN_HEADER, "").strip()
            if header_token:
                canonical_token = header_token

            self._run_and_respond(
                trigger_raw=trigger,
                timeout_seconds=timeout_f,
                request_id=request_id,
                correlation_id=correlation_id,
                trigger_source=trigger_source,
                canonical_token=canonical_token,
                filename_prefix=prefix,
                tolerance_seconds=tolerance_f,
            )

        def _run_and_respond(
            self,
            *,
            trigger_raw: str,
            timeout_seconds: float,
            request_id: str | None,
            correlation_id: str | None,
            trigger_source: str | None,
            canonical_token: str | None,
            filename_prefix: str,
            tolerance_seconds: float,
        ) -> None:
            if not self.server.busy_lock.acquire(blocking=False):
                logger.warning(
                    "replay-trigger-http: busy; rejecting request",
                    extra={
                        "structured": {
                            "request_id": request_id,
                            "correlation_id": correlation_id,
                        }
                    },
                )
                self._send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {
                        "success": False,
                        "failure_reason": "replay_trigger_busy",
                        "request_id": request_id,
                        "correlation_id": correlation_id,
                    },
                )
                return

            logger.info(
                "replay-trigger-http: request received",
                extra={
                    "structured": {
                        "request_id": request_id,
                        "correlation_id": correlation_id,
                        "trigger": trigger_raw[:120],
                        "timeout_seconds": timeout_seconds,
                        "trigger_source": trigger_source,
                    }
                },
            )
            trust_category = "legacy_noncanonical"
            trust_reason = "non_canonical_source"
            token_configured = bool(expected_canonical_token)
            if trigger_source == CANONICAL_TRIGGER_SOURCE:
                if (
                    token_configured
                    and canonical_token
                    and compare_digest(canonical_token, expected_canonical_token or "")
                ):
                    trust_category = "canonical_trusted"
                    trust_reason = "valid_canonical_token"
                else:
                    trust_category = "canonical_claim_untrusted"
                    if not token_configured:
                        trust_reason = "canonical_token_not_configured"
                    elif not canonical_token:
                        trust_reason = "canonical_token_missing"
                    else:
                        trust_reason = "canonical_token_invalid"

            if trust_category == "canonical_trusted":
                logger.info(
                    "replay-trigger-http: canonical trusted request",
                    extra={
                        "structured": {
                            "request_id": request_id,
                            "correlation_id": correlation_id,
                            "trust_category": trust_category,
                            "trust_reason": trust_reason,
                            "trigger_source": trigger_source,
                        }
                    },
                )
            elif trust_category == "canonical_claim_untrusted":
                logger.warning(
                    "replay-trigger-http: canonical claim untrusted",
                    extra={
                        "structured": {
                            "request_id": request_id,
                            "correlation_id": correlation_id,
                            "trust_category": trust_category,
                            "trust_reason": trust_reason,
                            "trigger_source": trigger_source,
                            "canonical_source": CANONICAL_TRIGGER_SOURCE,
                        }
                    },
                )
            else:
                logger.warning(
                    "replay-trigger-http: legacy non-canonical request",
                    extra={
                        "structured": {
                            "request_id": request_id,
                            "correlation_id": correlation_id,
                            "trust_category": trust_category,
                            "trust_reason": trust_reason,
                            "trigger_source": trigger_source,
                            "canonical_source": CANONICAL_TRIGGER_SOURCE,
                        }
                    },
                )
            try:
                result, exit_code = run_pipeline(
                    trigger_raw=trigger_raw,
                    timeout_seconds=timeout_seconds,
                    request_id=request_id,
                    filename_prefix=filename_prefix,
                    tolerance_seconds=tolerance_seconds,
                )
            except Exception as exc:
                logger.exception(
                    "replay-trigger-http: pipeline raised",
                    extra={
                        "structured": {
                            "request_id": request_id,
                            "correlation_id": correlation_id,
                        }
                    },
                )
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "success": False,
                        "failure_reason": "replay_pipeline_exception",
                        "processing_error": str(exc)[:500],
                        "request_id": request_id,
                        "correlation_id": correlation_id,
                    },
                )
                return
            finally:
                self.server.busy_lock.release()

            payload: dict[str, Any] = dict(asdict(result))
            if request_id is not None:
                payload["request_id"] = request_id
            if correlation_id is not None:
                payload["correlation_id"] = correlation_id
            payload["canonical_trust_category"] = trust_category
            payload["canonical_trust_reason"] = trust_reason
            payload["exit_code"] = exit_code
            # Always 200 with JSON body so simple clients can parse; use success + exit_code.
            self._send_json(HTTPStatus.OK, payload)
            logger.info(
                "replay-trigger-http: request finished",
                extra={
                    "structured": {
                        "request_id": request_id,
                        "correlation_id": correlation_id,
                        "success": result.success,
                        "exit_code": exit_code,
                        "failure_reason": result.failure_reason,
                        "trust_category": trust_category,
                        "trust_reason": trust_reason,
                    }
                },
            )

    return Handler


def serve_replay_trigger_http_blocking(
    host: str,
    port: int,
    run_pipeline: ReplayPipeline,
    *,
    default_timeout: float = 120.0,
    default_prefix: str = "replay_",
    default_tolerance: float = 10.0,
    expected_canonical_token: str | None = None,
) -> None:
    """Run the HTTP server in the current thread until interrupted."""
    busy = threading.Lock()
    handler_cls = _make_handler_class(
        run_pipeline,
        default_timeout=default_timeout,
        default_prefix=default_prefix,
        default_tolerance=default_tolerance,
        expected_canonical_token=expected_canonical_token,
    )
    httpd = ReplayTriggerHTTPServer((host, port), handler_cls, busy_lock=busy)
    logger.info(
        "replay-trigger-http: listening",
        extra={"structured": {"host": host, "port": port}},
    )
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


def run_replay_trigger_http_loop(
    host: str,
    port: int,
    run_pipeline: ReplayPipeline,
    stop: threading.Event,
    *,
    default_timeout: float = 120.0,
    default_prefix: str = "replay_",
    default_tolerance: float = 10.0,
    expected_canonical_token: str | None = None,
) -> None:
    """Non-blocking-friendly loop: poll ``stop`` between requests (for embedding in worker)."""
    busy = threading.Lock()
    handler_cls = _make_handler_class(
        run_pipeline,
        default_timeout=default_timeout,
        default_prefix=default_prefix,
        default_tolerance=default_tolerance,
        expected_canonical_token=expected_canonical_token,
    )
    httpd = ReplayTriggerHTTPServer((host, port), handler_cls, busy_lock=busy)
    httpd.timeout = 0.5
    logger.info(
        "replay-trigger-http: listening (embedded)",
        extra={"structured": {"host": host, "port": port}},
    )
    try:
        while not stop.is_set():
            httpd.handle_request()
    finally:
        try:
            httpd.server_close()
        except OSError:
            pass
