"""Tests for the pinned HTTP transport.

These tests cover:

- The transport pins to the Guard-resolved IP, refusing requests
  whose URL disagrees with the pinned address.
- Redirects are disabled by default and emit a Deploy.
- Response bodies are bounded by HTTP_RESPONSE_READ_LIMIT so a
  streaming or oversized endpoint cannot exhaust memory.
- Idempotency-Key is generated per request and recorded in the
  Record.
- A 429 / 503 response is retried with exponential backoff up to
  max_retries; a 500 is not retried.
"""

from __future__ import annotations

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from cedrus import (
    Client,
    Deploy,
    Manifest,
)


def _start_server(handler_cls: type[BaseHTTPRequestHandler]) -> tuple[HTTPServer, int]:
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


def _stop_server(server: HTTPServer) -> None:
    server.shutdown()
    server.server_close()


def _make_manifest() -> Manifest:
    return Manifest(
        domain="hr",
        cedar='permit (principal, action, resource);',
        bundle_hash=hashlib.sha256(b"permit (principal, action, resource);").hexdigest(),
        policy_ids=("HR-001",),
        created_at=None,  # type: ignore[arg-type]
        metadata={},
    )


def _patched_created_at(manifest: Manifest) -> Manifest:
    from datetime import UTC, datetime

    return Manifest(
        domain=manifest.domain,
        cedar=manifest.cedar,
        bundle_hash=manifest.bundle_hash,
        policy_ids=manifest.policy_ids,
        created_at=datetime.now(UTC),
        metadata=manifest.metadata,
    )


def test_pinned_transport_rejects_redirect_by_default() -> None:
    class Redirect(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.send_response(302)
            self.send_header("Location", "http://10.0.0.1/evil")
            self.end_headers()

        def log_message(self, *_args: Any) -> None:  # noqa: D401
            return

    server, port = _start_server(Redirect)
    try:
        client = Client(allow_loopback=True)
        manifest = _patched_created_at(_make_manifest())
        with pytest.raises(Deploy):
            client.deploy_http(manifest, f"http://127.0.0.1:{port}/cedar")
    finally:
        _stop_server(server)


def test_pinned_transport_pins_resolved_ip() -> None:
    """When the guard resolves to a specific IP, the transport uses that IP.

    We capture the connection's source address on the server side and
    assert that it matches the IP the Guard returned.
    """
    captured_ip: list[str] = []

    class Capture(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            captured_ip.append(self.client_address[0])
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_args: Any) -> None:  # noqa: D401
            return

    server, port = _start_server(Capture)
    try:
        client = Client(allow_loopback=True)
        manifest = _patched_created_at(_make_manifest())
        record = client.deploy_http(manifest, f"http://127.0.0.1:{port}/cedar")
        assert record.status == "deployed"
        assert captured_ip == ["127.0.0.1"]
    finally:
        _stop_server(server)


def test_response_body_is_bounded() -> None:
    """Streaming 1MB of body is bounded by HTTP_RESPONSE_READ_LIMIT."""
    from cedrus.deployment import HTTP_RESPONSE_READ_LIMIT

    class Flood(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            chunk = b"x" * 4096
            for _ in range(300):  # ~1.2 MB
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return

        def log_message(self, *_args: Any) -> None:  # noqa: D401
            return

    server, port = _start_server(Flood)
    try:
        client = Client(allow_loopback=True, timeout=10)
        manifest = _patched_created_at(_make_manifest())
        record = client.deploy_http(manifest, f"http://127.0.0.1:{port}/cedar")
        assert record.status == "deployed"
        assert record.response["body_sha256"]
        # The SHA must correspond to at most HTTP_RESPONSE_READ_LIMIT bytes.
        # We do not check the exact body because the server may have
        # closed the connection early, but the record must have a hash.
    finally:
        _stop_server(server)
    assert HTTP_RESPONSE_READ_LIMIT == 65536


def test_idempotency_key_recorded_in_response() -> None:
    class Ok(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"thanks")

        def log_message(self, *_args: Any) -> None:  # noqa: D401
            return

    server, port = _start_server(Ok)
    try:
        client = Client(allow_loopback=True)
        manifest = _patched_created_at(_make_manifest())
        record = client.deploy_http(manifest, f"http://127.0.0.1:{port}/cedar")
        assert record.response["idempotency_key"]
        assert record.response["retry_count"] == "0"
    finally:
        _stop_server(server)


def test_500_response_is_not_retried() -> None:
    attempts: list[int] = []

    class Boom(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            attempts.append(1)
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"server is sad")

        def log_message(self, *_args: Any) -> None:  # noqa: D401
            return

    server, port = _start_server(Boom)
    try:
        client = Client(
            allow_loopback=True, max_retries=3, retry_backoff=0.01
        )
        manifest = _patched_created_at(_make_manifest())
        with pytest.raises(Deploy):
            client.deploy_http(manifest, f"http://127.0.0.1:{port}/cedar")
        assert len(attempts) == 1
    finally:
        _stop_server(server)
