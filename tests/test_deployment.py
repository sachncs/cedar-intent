"""Tests for the deployment module."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from cedrus import (
    Action,
    Bundler,
    Client,
    Compiled,
    Deploy,
    Intent,
    Manifest,
    Need,
    Principal,
    Record,
    Resource,
)


def make_requirement(identifier: str) -> Need:
    return Need(
        id=identifier,
        text=f"Body for {identifier}",
        domain="hr",
        source_path=Path(f"/tmp/{identifier}.md"),
        created_at=datetime.now(UTC),
    )


def make_policy(identifier: str) -> Compiled:
    requirement = make_requirement(identifier)
    intent = Intent(
        id=identifier,
        requirement_id=identifier,
        effect="permit",
        principal=Principal(kind="is_type", type_name="User"),
        action=Action(kind="named", name="view"),
        resource=Resource(kind="is_type", type_name="Photo"),
    )
    cedar = (
        'permit (principal is PhotoFlash::User, '
        'action == PhotoFlash::Action::"view", '
        "resource is PhotoFlash::Photo);"
    )
    return Compiled(
        id=identifier, requirement=requirement, cedar=cedar, intent=intent
    )


def test_bundle_exporter_builds_manifest() -> None:
    exporter = Bundler()
    manifest = exporter.build("hr", [make_policy("HR-001")])
    assert isinstance(manifest, Manifest)
    assert manifest.domain == "hr"
    assert manifest.bundle_hash
    assert manifest.policy_ids == ("HR-001",)
    assert "permit" in manifest.cedar


def test_bundle_exporter_rejects_empty_domain() -> None:
    exporter = Bundler()
    with pytest.raises(Deploy):
        exporter.build("hr", [])


def test_bundle_exporter_skips_policies_without_cedar() -> None:
    exporter = Bundler()
    requirement = make_requirement("HR-001")
    empty = Compiled(id="HR-002", requirement=requirement, cedar="")
    manifest = exporter.build("hr", [empty, make_policy("HR-001")])
    assert manifest.policy_ids == ("HR-001",)


def test_bundle_exporter_rejects_only_empty_policies() -> None:
    exporter = Bundler()
    requirement = make_requirement("HR-001")
    empty = Compiled(id="HR-002", requirement=requirement, cedar="")
    with pytest.raises(Deploy):
        exporter.build("hr", [empty])


def test_bundle_exporter_writes_and_reads_directory(tmp_path: Path) -> None:
    exporter = Bundler()
    manifest = exporter.build("hr", [make_policy("HR-001")])
    exporter.write_directory(manifest, tmp_path / "dist" / "hr")
    bundle = (tmp_path / "dist" / "hr" / "bundle.cedar").read_text()
    manifest_text = (tmp_path / "dist" / "hr" / "manifest.json").read_text()
    assert "permit" in bundle
    payload = json.loads(manifest_text)
    assert payload["domain"] == "hr"
    assert payload["bundle_hash"] == manifest.bundle_hash

    reloaded = exporter.read_directory(tmp_path / "dist" / "hr")
    assert reloaded.bundle_hash == manifest.bundle_hash
    assert reloaded.policy_ids == ("HR-001",)


def test_bundle_exporter_read_missing_directory(tmp_path: Path) -> None:
    exporter = Bundler()
    with pytest.raises(Deploy):
        exporter.read_directory(tmp_path / "missing")


def test_bundle_exporter_read_detects_hash_mismatch(tmp_path: Path) -> None:
    exporter = Bundler()
    manifest = exporter.build("hr", [make_policy("HR-001")])
    exporter.write_directory(manifest, tmp_path / "dist")
    (tmp_path / "dist" / "bundle.cedar").write_text("permit (principal, action, resource);")
    with pytest.raises(Deploy):
        exporter.read_directory(tmp_path / "dist")


def test_bundle_exporter_read_incomplete_directory(tmp_path: Path) -> None:
    exporter = Bundler()
    target = tmp_path / "dist"
    target.mkdir()
    with pytest.raises(Deploy):
        exporter.read_directory(target)


def test_deployment_client_local_deploy(tmp_path: Path) -> None:
    manifest = Bundler().build("hr", [make_policy("HR-001")])
    client = Client(allow_private_targets=True, allow_loopback=True)
    record = client.deploy_local(manifest, tmp_path / "out")
    assert isinstance(record, Record)
    assert record.target_kind == "local"
    assert (tmp_path / "out" / "bundle.cedar").exists()


def test_deployment_client_rejects_empty_target() -> None:
    client = Client(allow_private_targets=True, allow_loopback=True)
    manifest = Bundler().build("hr", [make_policy("HR-001")])
    with pytest.raises(Deploy):
        client.deploy(manifest, "")


def test_deployment_client_rejects_non_positive_timeout() -> None:
    with pytest.raises(Deploy):
        Client(timeout=0)


def test_deployment_client_dispatches_based_on_scheme() -> None:
    manifest = Bundler().build("hr", [make_policy("HR-001")])
    client = Client(allow_private_targets=True, allow_loopback=True)
    with pytest.raises(Deploy):
        client.deploy(manifest, "http://127.0.0.1:1/cedar", record_id="x")


def test_deployment_client_local_record_id_default() -> None:
    manifest = Bundler().build("hr", [make_policy("HR-001")])
    client = Client(allow_private_targets=True, allow_loopback=True)
    record = client.deploy_local(manifest, Path("/tmp/nonexistent-cedar-bundle"))
    assert record.id
    assert record.status == "deployed"
    assert record.bundle_hash == manifest.bundle_hash


class _BuildHandler:
    """Factory for HTTP test handlers."""


def _build_handler(received: list[bytes], status_code: int, response_body: bytes) -> type:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib API
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            received.append(body)
            self.send_response(status_code)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(response_body)

        def log_message(self, *_args: object) -> None:
            return

    return Handler


def test_deployment_client_http_push(tmp_path: Path) -> None:
    received: list[bytes] = []
    handler_class = _build_handler(received, 200, b"thanks")
    server = HTTPServer(("127.0.0.1", 0), handler_class)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/cedar"
        manifest = Bundler().build("hr", [make_policy("HR-001")])
        client = Client(allow_private_targets=True, allow_loopback=True)
        record = client.deploy_http(
            manifest, url, record_id="x", headers={"X-Test": "yes"}
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert record.target_kind == "http"
    assert record.status == "deployed"
    assert received
    payload = json.loads(received[0].decode("utf-8"))
    assert payload["bundle_hash"] == manifest.bundle_hash
    assert record.response["status_code"] == "200"
    expected_sha = hashlib.sha256(b"thanks").hexdigest()
    assert record.response["body_sha256"] == expected_sha
    assert "body" not in record.response
    assert record.response["idempotency_key"]
    assert record.response["retry_count"] == "0"


def test_deployment_client_http_push_failure(tmp_path: Path) -> None:
    received: list[bytes] = []
    handler_class = _build_handler(received, 500, b"super-secret-token-AKIA")
    server = HTTPServer(("127.0.0.1", 0), handler_class)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/cedar"
        manifest = Bundler().build("hr", [make_policy("HR-001")])
        client = Client(allow_private_targets=True, allow_loopback=True)
        with pytest.raises(Deploy) as excinfo:
            client.deploy_http(manifest, url)
        # Body must NEVER be embedded in error messages.
        assert b"super-secret-token" not in str(excinfo.value).encode("utf-8")
        assert received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_deployment_client_http_connection_error() -> None:
    manifest = Bundler().build("hr", [make_policy("HR-001")])
    client = Client(timeout=1)
    with pytest.raises(Deploy):
        client.deploy_http(manifest, "http://127.0.0.1:1/cedar")
