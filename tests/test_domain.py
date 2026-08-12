"""Tests for the Domain dataclass and the data package."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from cedrus import Domain, Need
from cedrus.data import (
    Body,
    Headers,
    Metadata,
    Notes,
    Payload,
    Receipt,
    Target,
    TargetKind,
    Unresolved,
    Usage,
)
from cedrus.error import Space


def test_domain_create_classmethod(tmp_path: Path) -> None:
    """Domain.create creates the directory layout and returns a Domain."""
    domain = Domain.create("hr", tmp_path / "acme")
    assert domain.name == "hr"
    assert domain.root == tmp_path / "acme"
    assert (tmp_path / "acme" / "requirements").is_dir()
    assert (tmp_path / "acme" / "policies").is_dir()
    assert domain.schema_path == tmp_path / "acme" / "schema.json"
    assert domain.scenarios_path == tmp_path / "acme" / "scenarios.json"
    assert domain.needs == []
    assert domain.policies == []


def test_domain_load_classmethod(tmp_path: Path) -> None:
    """Domain.load returns an existing Domain, optionally with a Schema."""
    schema = object()  # placeholder for a Schema
    domain = Domain.load("hr", tmp_path / "acme", schema=schema)
    assert domain.schema_loaded is schema


def test_domain_mutate_updates_fields(tmp_path: Path) -> None:
    """Domain.mutate updates declared fields in place."""
    domain = Domain.create("hr", tmp_path / "acme")
    new_need = Need(
        id="HR-001",
        text="Body",
        domain="hr",
        source_path=tmp_path / "requirements" / "HR-001.md",
        created_at=datetime.now(UTC),
    )
    domain.mutate(needs=[new_need])
    assert domain.needs == [new_need]
    domain.mutate(name="finance")
    assert domain.name == "finance"


def test_domain_mutate_raises_on_unknown_field(tmp_path: Path) -> None:
    """Domain.mutate raises Space for fields that don't exist."""
    domain = Domain.create("hr", tmp_path / "acme")
    with pytest.raises(Space):
        domain.mutate(nonexistent_field="x")


def test_domain_to_dict(tmp_path: Path) -> None:
    """Domain.to_dict returns a JSON-friendly representation."""
    domain = Domain.create("hr", tmp_path / "acme")
    payload = domain.to_dict()
    assert payload["name"] == "hr"
    assert payload["needs"] == []
    assert "schema_path" in payload


def test_headers_rejects_reserved_name() -> None:
    """Headers.from_strings rejects Authorization, Host, Cookie, etc."""
    from cedrus.error import Config

    with pytest.raises(Config):
        Headers.from_strings(["Authorization: Bearer xyz"])


def test_headers_rejects_crlf() -> None:
    """Headers.from_strings rejects CR/LF in name or value."""
    from cedrus.error import Config

    with pytest.raises(Config):
        Headers.from_strings(["X-Foo: bar\r\nX-Admin: true"])


def test_headers_rejects_empty_name() -> None:
    """Headers.from_strings rejects empty header names."""
    from cedrus.error import Config

    with pytest.raises(Config):
        Headers.from_strings([": value"])


def test_headers_preserves_order() -> None:
    """Headers items preserve insertion order."""
    headers = Headers.from_strings(["X-A: 1", "X-B: 2", "X-C: 3"])
    assert [name for name, _ in headers.items] == ["X-A", "X-B", "X-C"]


def test_body_computes_sha256() -> None:
    """Body.sha256 is computed from the payload at construction time."""
    body = Body(payload=b"hello world")
    assert body.sha256 == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    assert body.content_type == "application/json"


def test_target_local_factory(tmp_path: Path) -> None:
    target = Target.local(tmp_path / "deploy")
    assert target.kind == TargetKind.LOCAL
    assert target.value == str(tmp_path / "deploy")
    assert target.is_local()
    assert not target.is_remote()


def test_target_remote_factory() -> None:
    target = Target.remote("https://example.com/deploy")
    assert target.kind == TargetKind.REMOTE
    assert target.is_remote()
    assert not target.is_local()


def test_receipt_round_trip() -> None:
    receipt = Receipt(status_code=200, body_sha256="abc", idempotency_key="k", retry_count=0)
    data = receipt.to_dict()
    restored = Receipt.from_dict(data)
    assert restored.status_code == 200
    assert restored.body_sha256 == "abc"
    assert restored.idempotency_key == "k"
    assert restored.retry_count == 0


def test_unresolved_add_and_merge() -> None:
    base = Unresolved(items=("a",))
    added = base.add("b")
    assert added.items == ("a", "b")

    merged = Unresolved.merge(["x", "y"], ["y", "z"])
    assert merged.items == ("x", "y", "z")


def test_notes_round_trip() -> None:
    notes = Notes.from_dict({"author": "alice"})
    data = notes.to_dict()
    assert data == {"author": "alice"}
    restored = Notes.from_dict(data)
    assert restored.to_dict() == {"author": "alice"}


def test_metadata_round_trip() -> None:
    meta = Metadata.from_dict({"env": "prod"})
    assert meta.to_dict() == {"env": "prod"}


def test_usage_to_dict() -> None:
    usage = Usage(prompt=10, completion=20, total=30)
    assert usage.to_dict() == {"prompt": 10, "completion": 20, "total": 30}


def test_payload_round_trip() -> None:
    payload = Payload.from_dict({"passed": True, "errors": ["x"]})
    assert payload.to_dict() == {"passed": True, "errors": ["x"]}


def test_target_kind_strenum_values() -> None:
    """TargetKind values are the wire-format strings."""
    assert str(TargetKind.LOCAL) == "local"
    assert str(TargetKind.REMOTE) == "remote"
    assert TargetKind("local") is TargetKind.LOCAL


def test_domain_refresh_scans_directories(tmp_path: Path) -> None:
    """Domain.refresh rescans the requirements and policies directories."""
    requirements_dir = tmp_path / "acme" / "requirements"
    policies_dir = tmp_path / "acme" / "policies"
    requirements_dir.mkdir(parents=True)
    policies_dir.mkdir(parents=True)
    (requirements_dir / "HR-001.md").write_text(
        "---\nid: HR-001\ndomain: hr\n---\n\nBody text.\n",
        encoding="utf-8",
    )
    (policies_dir / "HR-001.cedar").write_text(
        "permit (principal, action, resource);",
        encoding="utf-8",
    )
    domain = Domain.create("hr", tmp_path / "acme")
    assert domain.needs == []
    assert domain.policies == []
    domain.refresh()
    assert len(domain.needs) == 1
    assert domain.needs[0].id == "HR-001"
    assert len(domain.policies) == 1
    assert "permit" in domain.policies[0].cedar
