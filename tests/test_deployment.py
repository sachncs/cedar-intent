"""Tests for the deployment module."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from cedar_intent import (
    ActionScope,
    BundleExporter,
    CompiledPolicy,
    DeploymentClient,
    DeploymentError,
    DeploymentManifest,
    DeploymentRecord,
    PolicyIntent,
    PrincipalScope,
    Requirement,
    ResourceScope,
)


def make_requirement(identifier: str) -> Requirement:
    return Requirement(
        id=identifier,
        text=f"Body for {identifier}",
        domain="hr",
        source_path=Path(f"/tmp/{identifier}.md"),
        created_at=datetime.now(UTC),
    )


def make_policy(identifier: str) -> CompiledPolicy:
    requirement = make_requirement(identifier)
    intent = PolicyIntent(
        id=identifier,
        requirement_id=identifier,
        effect="permit",
        principal=PrincipalScope(kind="is_type", type_name="User"),
        action=ActionScope(kind="named", name="view"),
        resource=ResourceScope(kind="is_type", type_name="Photo"),
    )
    cedar = (
        'permit (principal is PhotoFlash::User, '
        'action == PhotoFlash::Action::"view", '
        "resource is PhotoFlash::Photo);"
    )
    return CompiledPolicy(
        id=identifier, requirement=requirement, cedar=cedar, intent=intent
    )


def test_bundle_exporter_builds_manifest() -> None:
    exporter = BundleExporter()
    manifest = exporter.build("hr", [make_policy("HR-001")])
    assert isinstance(manifest, DeploymentManifest)
    assert manifest.domain == "hr"
    assert manifest.bundle_hash
    assert manifest.policy_ids == ("HR-001",)
    assert "permit" in manifest.cedar


def test_bundle_exporter_rejects_empty_domain() -> None:
    exporter = BundleExporter()
    with pytest.raises(DeploymentError):
        exporter.build("hr", [])


def test_bundle_exporter_skips_policies_without_cedar() -> None:
    exporter = BundleExporter()
    requirement = make_requirement("HR-001")
    empty = CompiledPolicy(id="HR-002", requirement=requirement, cedar="")
    manifest = exporter.build("hr", [empty, make_policy("HR-001")])
    assert manifest.policy_ids == ("HR-001",)


def test_bundle_exporter_rejects_only_empty_policies() -> None:
    exporter = BundleExporter()
    requirement = make_requirement("HR-001")
    empty = CompiledPolicy(id="HR-002", requirement=requirement, cedar="")
    with pytest.raises(DeploymentError):
        exporter.build("hr", [empty])


def test_bundle_exporter_writes_and_reads_directory(tmp_path: Path) -> None:
    exporter = BundleExporter()
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
    exporter = BundleExporter()
    with pytest.raises(DeploymentError):
        exporter.read_directory(tmp_path / "missing")


def test_bundle_exporter_read_detects_hash_mismatch(tmp_path: Path) -> None:
    exporter = BundleExporter()
    manifest = exporter.build("hr", [make_policy("HR-001")])
    exporter.write_directory(manifest, tmp_path / "dist")
    (tmp_path / "dist" / "bundle.cedar").write_text("permit (principal, action, resource);")
    with pytest.raises(DeploymentError):
        exporter.read_directory(tmp_path / "dist")


def test_bundle_exporter_read_incomplete_directory(tmp_path: Path) -> None:
    exporter = BundleExporter()
    target = tmp_path / "dist"
    target.mkdir()
    with pytest.raises(DeploymentError):
        exporter.read_directory(target)


def test_deployment_client_local_deploy(tmp_path: Path) -> None:
    manifest = BundleExporter().build("hr", [make_policy("HR-001")])
    client = DeploymentClient()
    record = client.deploy_local(manifest, tmp_path / "out")
    assert isinstance(record, DeploymentRecord)
    assert record.target_kind == "local"
    assert (tmp_path / "out" / "bundle.cedar").exists()


def test_deployment_client_rejects_empty_target() -> None:
    client = DeploymentClient()
    manifest = BundleExporter().build("hr", [make_policy("HR-001")])
    with pytest.raises(DeploymentError):
        client.deploy(manifest, "")


def test_deployment_client_rejects_non_positive_timeout() -> None:
    with pytest.raises(DeploymentError):
        DeploymentClient(timeout=0)


def test_deployment_client_dispatches_based_on_scheme() -> None:
    manifest = BundleExporter().build("hr", [make_policy("HR-001")])
    client = DeploymentClient()
    with pytest.raises(DeploymentError):
        client.deploy(manifest, "http://127.0.0.1:1/cedar", record_id="x")


def test_deployment_client_local_record_id_default() -> None:
    manifest = BundleExporter().build("hr", [make_policy("HR-001")])
    client = DeploymentClient()
    record = client.deploy_local(manifest, Path("/tmp/nonexistent-cedar-bundle"))
    assert record.id
    assert record.status == "deployed"
    assert record.bundle_hash == manifest.bundle_hash


class _CaptureHandler(BaseHTTPRequestHandler):
    received: list[bytes] = []
    status_code = 200
    response_body = b"ok"

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.received.append(body)
        self.send_response(self.status_code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(self.response_body)

    def log_message(self, *_args: object) -> None:
        return


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
        manifest = BundleExporter().build("hr", [make_policy("HR-001")])
        client = DeploymentClient()
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
    assert record.response["body"] == "thanks"


def test_deployment_client_http_push_failure(tmp_path: Path) -> None:
    received: list[bytes] = []
    handler_class = _build_handler(received, 500, b"nope")
    server = HTTPServer(("127.0.0.1", 0), handler_class)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/cedar"
        manifest = BundleExporter().build("hr", [make_policy("HR-001")])
        client = DeploymentClient()
        with pytest.raises(DeploymentError):
            client.deploy_http(manifest, url)
        assert received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_deployment_client_http_connection_error() -> None:
    manifest = BundleExporter().build("hr", [make_policy("HR-001")])
    client = DeploymentClient(timeout=1)
    with pytest.raises(DeploymentError):
        client.deploy_http(manifest, "http://127.0.0.1:1/cedar")
