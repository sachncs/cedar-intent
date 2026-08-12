"""Tests for :mod:`cedrus.deploy` — Bundler, Guard, Pin, Transport, Manifest, Record."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from cedrus.deploy import (
    Bundler,
    Client,
    DEPLOYMENT_KIND_HTTP,
    DEPLOYMENT_KIND_LOCAL,
    Guard,
    HTTP_RESPONSE_BODY_LIMIT,
    HTTP_RESPONSE_READ_LIMIT,
    Manifest,
    Pin,
    Record,
    RESERVED_HEADERS,
    Transport,
)


def _validate_headers(headers):
    """Drive the validator through a Client instance."""
    Client(timeout=30).validate_headers(headers)


def _read_bounded(response):
    """Drive the reader through a Client instance."""
    return Client(timeout=30).read_bounded(response)


def _manifest(domain: str = "hr", cedar: str = "permit (principal, action, resource);") -> Manifest:
    import hashlib

    bundle_hash = hashlib.sha256(cedar.encode("utf-8")).hexdigest()
    return Manifest(
        domain=domain,
        cedar=cedar,
        bundle_hash=bundle_hash,
        policy_ids=("HR-001",),
        created_at=datetime.now(UTC),
        metadata={"env": "test"},
    )


# ---------------------------------------------------------------------------
# Manifest data modelling
# ---------------------------------------------------------------------------


def test_manifest_to_dict_includes_cedar_payload() -> None:
    manifest = _manifest()
    d = manifest.to_dict()
    assert d["domain"] == "hr"
    assert d["bundle_hash"]
    assert "permit" in d["cedar"]


def test_manifest_to_manifest_payload_excludes_cedar() -> None:
    manifest = _manifest()
    d = manifest.to_manifest_payload()
    assert "cedar" not in d
    assert d["domain"] == "hr"


# ---------------------------------------------------------------------------
# Bundler
# ---------------------------------------------------------------------------


def test_bundler_build_rejects_empty_domain() -> None:
    from cedrus.deploy import Bundler

    with pytest.raises(Exception):
        Bundler().build("", [], metadata={})


def test_bundler_build_rejects_empty_policies() -> None:
    from cedrus.deploy import Bundler

    with pytest.raises(Exception):
        Bundler().build("hr", [], metadata={})


def test_bundler_build_skips_policies_without_cedar() -> None:
    from cedrus import Compiled, Draft
    from datetime import UTC, datetime
    from pathlib import Path

    from cedrus.need import Need

    need = Need(
        id="HR-001", text="x", domain="hr",
        source_path=Path("/tmp/x"), created_at=datetime.now(UTC),
    )
    no_cedar = Compiled(id="no-cedar", requirement=need, cedar="")
    with_cedar = Compiled(
        id="ok", requirement=need,
        cedar="permit (principal, action, resource);",
    )
    manifest = Bundler().build("hr", [no_cedar, with_cedar], metadata={})
    assert "ok" in manifest.policy_ids
    assert "no-cedar" not in manifest.policy_ids


def test_bundler_write_directory_writes_bundle_and_manifest(tmp_path: Path) -> None:
    from cedrus import Compiled
    from cedrus.need import Need

    need = Need(
        id="HR-001", text="x", domain="hr",
        source_path=Path("/tmp/x"), created_at=datetime.now(UTC),
    )
    compiled = Compiled(
        id="HR-001", requirement=need,
        cedar="permit (principal, action, resource);",
    )
    manifest = Bundler().build("hr", [compiled], metadata={})
    target = tmp_path / "out"
    Bundler().write_directory(manifest, target)
    assert (target / "bundle.cedar").exists()
    assert (target / "manifest.json").exists()


def test_bundler_read_directory_round_trips(tmp_path: Path) -> None:
    from cedrus import Compiled
    from cedrus.need import Need

    need = Need(
        id="HR-001", text="x", domain="hr",
        source_path=Path("/tmp/x"), created_at=datetime.now(UTC),
    )
    compiled = Compiled(
        id="HR-001", requirement=need,
        cedar="permit (principal, action, resource);",
    )
    manifest = Bundler().build("hr", [compiled], metadata={})
    target = tmp_path / "out"
    Bundler().write_directory(manifest, target)
    rebuilt = Bundler().read_directory(target)
    assert rebuilt.domain == "hr"


def test_bundler_read_directory_raises_for_missing(tmp_path: Path) -> None:
    from cedrus.deploy import Deploy as DeployError

    with pytest.raises(Exception):
        Bundler().read_directory(tmp_path / "ghost")


def test_bundler_read_directory_raises_on_hash_mismatch(tmp_path: Path) -> None:
    from cedrus.deploy import Deploy as DeployError

    target = tmp_path / "out"
    target.mkdir()
    (target / "bundle.cedar").write_text("permit;")
    (target / "manifest.json").write_text(
        '{"domain":"hr","bundle_hash":"0"*64,"policy_ids":[],"created_at":"2026-01-01T00:00:00+00:00","metadata":{}}'
    )
    with pytest.raises(Exception):
        Bundler().read_directory(target)


# ---------------------------------------------------------------------------
# Guard / Pin
# ---------------------------------------------------------------------------


def test_guard_blocks_loopback_by_default() -> None:
    with pytest.raises(Exception):
        Guard().check("https://127.0.0.1")


def test_guard_blocks_private_by_default() -> None:
    with pytest.raises(Exception):
        Guard().check("https://10.0.0.1")


def test_guard_blocks_link_local_by_default() -> None:
    with pytest.raises(Exception):
        Guard().check("https://169.254.169.254")


def test_guard_blocks_unsupported_scheme() -> None:
    with pytest.raises(Exception):
        Guard().check("ftp://example.com")


def test_guard_blocks_missing_host() -> None:
    with pytest.raises(Exception):
        Guard().check("https://")


def test_guard_allows_loopback_when_flag_set() -> None:
    Guard(allow_loopback=True).check("https://127.0.0.1")


def test_guard_allows_private_when_flag_set() -> None:
    Guard(allow_private_targets=True).check("https://10.0.0.1")


def test_guard_returns_pin_with_resolved_ip() -> None:
    pin = Guard(allow_loopback=True).check("https://127.0.0.1")
    assert isinstance(pin, Pin)
    assert pin.ip == "127.0.0.1"
    assert pin.scheme == "https"


# ---------------------------------------------------------------------------
# validate_headers helper
# ---------------------------------------------------------------------------


def test_validate_headers_accepts_none() -> None:
    _validate_headers(None)


def test_validate_headers_accepts_valid() -> None:
    _validate_headers({"X-Custom": "value"})


def test_validate_headers_rejects_empty_name() -> None:
    from cedrus.deploy import Deploy as DeployError

    with pytest.raises(DeployError):
        _validate_headers({"": "value"})


def test_validate_headers_rejects_whitespace_name() -> None:
    from cedrus.deploy import Deploy as DeployError

    with pytest.raises(DeployError):
        _validate_headers({"   ": "value"})


def test_validate_headers_rejects_crlf_in_name() -> None:
    from cedrus.deploy import Deploy as DeployError

    with pytest.raises(DeployError):
        _validate_headers({"X-Bad\rName": "value"})


def test_validate_headers_rejects_crlf_in_value() -> None:
    from cedrus.deploy import Deploy as DeployError

    with pytest.raises(DeployError):
        _validate_headers({"X-Bad": "line1\r\nline2"})


def test_validate_headers_rejects_reserved_header_case_insensitively() -> None:
    from cedrus.deploy import Deploy as DeployError

    with pytest.raises(DeployError):
        _validate_headers({"host": "evil.example"})


def test_validate_headers_rejects_oversize_name() -> None:
    from cedrus.deploy import Deploy as DeployError

    with pytest.raises(DeployError):
        _validate_headers({"X-" + "a" * 300: "value"})


def test_validate_headers_rejects_oversize_value() -> None:
    from cedrus.deploy import Deploy as DeployError

    with pytest.raises(DeployError):
        _validate_headers({"X-Long": "v" * 10000})


# ---------------------------------------------------------------------------
# Client.deploy_local
# ---------------------------------------------------------------------------


def test_client_local_deploy_writes_to_directory(tmp_path: Path) -> None:
    client = Client(timeout=30)
    record = client.deploy_local(_manifest(), tmp_path / "out")
    assert isinstance(record, Record)
    assert record.domain == "hr"
    assert record.target_kind == DEPLOYMENT_KIND_LOCAL
    assert (tmp_path / "out" / "bundle.cedar").exists()


def test_client_local_deploy_uses_supplied_record_id(tmp_path: Path) -> None:
    client = Client(timeout=30)
    record = client.deploy_local(_manifest(), tmp_path / "out", record_id="custom-id")
    assert record.id == "custom-id"


def test_client_local_deploy_creates_parent_directories(tmp_path: Path) -> None:
    client = Client(timeout=30)
    record = client.deploy_local(_manifest(), tmp_path / "deep" / "out")
    assert (tmp_path / "deep" / "out" / "bundle.cedar").exists()


def test_client_rejects_empty_target() -> None:
    client = Client(timeout=30)
    with pytest.raises(Exception):
        client.deploy(_manifest(), "")


def test_client_rejects_whitespace_target() -> None:
    client = Client(timeout=30)
    with pytest.raises(Exception):
        client.deploy(_manifest(), "   ")


# ---------------------------------------------------------------------------
# Client constructor validation
# ---------------------------------------------------------------------------


def test_client_rejects_zero_timeout() -> None:
    from cedrus.deploy import Deploy as DeployError

    with pytest.raises(DeployError):
        Client(timeout=0)


def test_client_rejects_negative_timeout() -> None:
    from cedrus.deploy import Deploy as DeployError

    with pytest.raises(DeployError):
        Client(timeout=-1)


def test_client_rejects_infinite_timeout() -> None:
    from cedrus.deploy import Deploy as DeployError

    with pytest.raises(DeployError):
        Client(timeout=float("inf"))


def test_client_rejects_nan_timeout() -> None:
    from cedrus.deploy import Deploy as DeployError

    with pytest.raises(DeployError):
        Client(timeout=float("nan"))


def test_client_rejects_negative_max_retries() -> None:
    from cedrus.deploy import Deploy as DeployError

    with pytest.raises(DeployError):
        Client(timeout=30, max_retries=-1)


def test_client_rejects_negative_backoff() -> None:
    from cedrus.deploy import Deploy as DeployError

    with pytest.raises(DeployError):
        Client(timeout=30, retry_backoff=-0.5)


def test_client_rejects_infinite_backoff() -> None:
    from cedrus.deploy import Deploy as DeployError

    with pytest.raises(DeployError):
        Client(timeout=30, retry_backoff=float("inf"))


def test_client_rejects_nan_backoff() -> None:
    from cedrus.deploy import Deploy as DeployError

    with pytest.raises(DeployError):
        Client(timeout=30, retry_backoff=float("nan"))


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------


def test_record_to_data_contains_required_keys() -> None:
    record = Record(
        id="d1",
        domain="hr",
        target="/tmp",
        target_kind=DEPLOYMENT_KIND_LOCAL,
        bundle_hash="x",
        status="deployed",
        created_at=datetime.now(UTC),
    )
    d = record.to_data()
    assert d["deployments"]["id"] == "d1"
    assert "deployment_responses" in d


def test_record_save_and_list_round_trip(tmp_path: Path) -> None:
    from cedrus import Memory

    repo = Memory()
    record = Record(
        id="d1",
        domain="hr",
        target="/tmp",
        target_kind=DEPLOYMENT_KIND_LOCAL,
        bundle_hash="x",
        status="deployed",
        created_at=datetime.now(UTC),
        response={"status_code": "200"},
    )
    record.save(repo)
    assert sorted(r.id for r in Record.list(repo)) == ["d1"]
    assert Record.list(repo, domain="hr")[0].response == {"status_code": "200"}


def test_record_parse_round_trip() -> None:
    from cedrus import Memory

    repo = Memory()
    record = Record(
        id="d1",
        domain="hr",
        target="/tmp",
        target_kind=DEPLOYMENT_KIND_LOCAL,
        bundle_hash="x",
        status="deployed",
        created_at=datetime.now(UTC),
    )
    record.save(repo)
    fetched = Record.list(repo)[0]
    rebuilt = Record.parse({"deployments": fetched.to_data()["deployments"]})
    assert rebuilt.id == "d1"


# ---------------------------------------------------------------------------
# HTTP constants
# ---------------------------------------------------------------------------


def test_reserved_headers_contains_documented_names() -> None:
    for name in ("host", "authorization", "cookie", "content-length", "transfer-encoding"):
        assert name in RESERVED_HEADERS


def test_http_constants_are_positive() -> None:
    assert HTTP_RESPONSE_BODY_LIMIT > 0
    assert HTTP_RESPONSE_READ_LIMIT > 0
    assert HTTP_RESPONSE_READ_LIMIT > HTTP_RESPONSE_BODY_LIMIT


def test_deployment_kind_constants() -> None:
    assert DEPLOYMENT_KIND_LOCAL == "local"
    assert DEPLOYMENT_KIND_HTTP == "http"


__all__ = []