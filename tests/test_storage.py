"""Tests for storage backends."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from cedar_intent import (
    DeploymentRecord,
    InMemoryRepository,
    Repository,
    SqliteRepository,
    StorageError,
)
from cedar_intent.compiler import PolicyIntent
from cedar_intent.deployment import DEPLOYMENT_KIND_LOCAL
from cedar_intent.requirements import Requirement
from cedar_intent.scopes import ActionScope, PrincipalScope, ResourceScope
from cedar_intent.storage import StoredDraft, StoredPolicy, StoredReport


def make_requirement(identifier: str, domain: str = "hr") -> Requirement:
    return Requirement(
        id=identifier,
        text=f"Body for {identifier}",
        domain=domain,
        source_path=Path(f"/tmp/{identifier}.md"),
        created_at=datetime.now(UTC),
    )


def make_intent(identifier: str) -> PolicyIntent:
    return PolicyIntent(
        id=identifier,
        requirement_id=identifier,
        effect="permit",
        principal=PrincipalScope(kind="any"),
        action=ActionScope(kind="any"),
        resource=ResourceScope(kind="any"),
    )


def make_policy(identifier: str, domain: str = "hr") -> StoredPolicy:
    intent = make_intent(identifier)
    return StoredPolicy(
        id=identifier,
        domain=domain,
        requirement_id=identifier,
        intent=intent,
        cedar="permit (principal, action, resource);",
        status="compiled",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        action_scope_json='{"kind": "any"}',
    )


def test_in_memory_repository_satisfies_protocol() -> None:
    repo: Repository = InMemoryRepository()
    assert isinstance(repo, Repository)


def test_in_memory_add_and_get_requirement() -> None:
    repo = InMemoryRepository()
    requirement = make_requirement("HR-001")
    repo.add_requirement(requirement)
    assert repo.get_requirement("HR-001").text == "Body for HR-001"


def test_in_memory_get_missing_requirement_raises() -> None:
    repo = InMemoryRepository()
    with pytest.raises(StorageError):
        repo.get_requirement("missing")


def test_in_memory_list_requirements_filtered_by_domain() -> None:
    repo = InMemoryRepository()
    repo.add_requirement(make_requirement("HR-001", domain="hr"))
    repo.add_requirement(make_requirement("FIN-001", domain="finance"))
    assert {r.id for r in repo.list_requirements()} == {"HR-001", "FIN-001"}
    assert {r.id for r in repo.list_requirements(domain="hr")} == {"HR-001"}


def test_in_memory_remove_requirement() -> None:
    repo = InMemoryRepository()
    repo.add_requirement(make_requirement("HR-001"))
    repo.remove_requirement("HR-001")
    with pytest.raises(StorageError):
        repo.get_requirement("HR-001")
    with pytest.raises(StorageError):
        repo.remove_requirement("HR-001")


def test_in_memory_upsert_and_get_policy() -> None:
    repo = InMemoryRepository()
    repo.add_requirement(make_requirement("HR-001"))
    policy = make_policy("HR-001")
    repo.upsert_policy(policy)
    fetched = repo.get_policy("HR-001")
    assert fetched.intent is not None
    assert fetched.intent.effect == "permit"


def test_in_memory_get_missing_policy_raises() -> None:
    repo = InMemoryRepository()
    with pytest.raises(StorageError):
        repo.get_policy("missing")


def test_in_memory_list_policies_by_domain() -> None:
    repo = InMemoryRepository()
    repo.add_requirement(make_requirement("HR-001", domain="hr"))
    repo.add_requirement(make_requirement("FIN-001", domain="finance"))
    repo.upsert_policy(make_policy("HR-001", domain="hr"))
    repo.upsert_policy(make_policy("FIN-001", domain="finance"))
    assert {p.id for p in repo.list_policies(domain="hr")} == {"HR-001"}


def test_in_memory_remove_policy() -> None:
    repo = InMemoryRepository()
    repo.add_requirement(make_requirement("HR-001"))
    repo.upsert_policy(make_policy("HR-001"))
    repo.remove_policy("HR-001")
    with pytest.raises(StorageError):
        repo.get_policy("HR-001")


def test_in_memory_record_and_latest_draft() -> None:
    repo = InMemoryRepository()
    repo.record_draft(
        StoredDraft(
            id="d1",
            policy_id="HR-001",
            model="offline",
            request_id=None,
            unresolved=("note",),
            cedar="permit (...) ;",
            created_at=datetime.now(UTC),
        )
    )
    latest = repo.latest_draft("HR-001")
    assert latest.id == "d1"
    assert latest.unresolved == ("note",)


def test_in_memory_latest_draft_missing_raises() -> None:
    repo = InMemoryRepository()
    with pytest.raises(StorageError):
        repo.latest_draft("missing")


def test_in_memory_list_drafts_filter() -> None:
    repo = InMemoryRepository()
    repo.record_draft(
        StoredDraft(
            id="d1",
            policy_id="HR-001",
            model="m",
            request_id=None,
            unresolved=(),
            cedar="...",
            created_at=datetime.now(UTC),
        )
    )
    repo.record_draft(
        StoredDraft(
            id="d2",
            policy_id="HR-002",
            model="m",
            request_id=None,
            unresolved=(),
            cedar="...",
            created_at=datetime.now(UTC),
        )
    )
    assert {d.id for d in repo.list_drafts()} == {"d1", "d2"}
    assert {d.id for d in repo.list_drafts(policy_id="HR-001")} == {"d1"}


def test_in_memory_record_and_latest_report() -> None:
    repo = InMemoryRepository()
    repo.record_report(
        StoredReport(policy_id="HR-001", kind="validation", passed=True, payload={"k": 1})
    )
    repo.record_report(
        StoredReport(policy_id="HR-001", kind="validation", passed=False, payload={})
    )
    latest = repo.latest_report("HR-001", "validation")
    assert latest.passed is False
    assert latest.payload == {}
    assert latest.created_at is not None


def test_in_memory_latest_report_missing_raises() -> None:
    repo = InMemoryRepository()
    with pytest.raises(StorageError):
        repo.latest_report("missing", "validation")


def test_sqlite_repository_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "store.db"
    repo = SqliteRepository(db_path)
    try:
        repo.add_requirement(make_requirement("HR-001"))
        repo.upsert_policy(make_policy("HR-001"))
        repo.record_draft(
            StoredDraft(
                id="d1",
                policy_id="HR-001",
                model="offline",
                request_id=None,
                unresolved=(),
                cedar="permit (principal, action, resource);",
                created_at=datetime.now(UTC),
            )
        )
        repo.record_report(
            StoredReport(policy_id="HR-001", kind="validation", passed=True, payload={"k": "v"})
        )
        assert repo.get_requirement("HR-001").id == "HR-001"
        assert repo.get_policy("HR-001").cedar.startswith("permit")
        assert repo.latest_draft("HR-001").id == "d1"
        assert repo.latest_report("HR-001", "validation").payload == {"k": "v"}
        assert {r.id for r in repo.list_requirements(domain="hr")} == {"HR-001"}
    finally:
        repo.close()


def test_sqlite_repository_handles_missing_records(tmp_path: Path) -> None:
    db_path = tmp_path / "store.db"
    repo = SqliteRepository(db_path)
    try:
        with pytest.raises(StorageError):
            repo.get_requirement("missing")
        with pytest.raises(StorageError):
            repo.get_policy("missing")
        with pytest.raises(StorageError):
            repo.latest_draft("missing")
        with pytest.raises(StorageError):
            repo.latest_report("missing", "validation")
        with pytest.raises(StorageError):
            repo.remove_requirement("missing")
        with pytest.raises(StorageError):
            repo.remove_policy("missing")
    finally:
        repo.close()


def test_sqlite_repository_persists_across_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "store.db"
    first = SqliteRepository(db_path)
    try:
        first.add_requirement(make_requirement("HR-001"))
        first.upsert_policy(make_policy("HR-001"))
    finally:
        first.close()
    second = SqliteRepository(db_path)
    try:
        assert second.get_requirement("HR-001").id == "HR-001"
        assert second.get_policy("HR-001").cedar.startswith("permit")
    finally:
        second.close()


def test_sqlite_repository_listing_filters(tmp_path: Path) -> None:
    db_path = tmp_path / "store.db"
    repo = SqliteRepository(db_path)
    try:
        repo.add_requirement(make_requirement("HR-001", domain="hr"))
        repo.add_requirement(make_requirement("FIN-001", domain="finance"))
        repo.upsert_policy(make_policy("HR-001", domain="hr"))
        repo.upsert_policy(make_policy("FIN-001", domain="finance"))
        assert {p.id for p in repo.list_policies()} == {"HR-001", "FIN-001"}
        assert {p.id for p in repo.list_policies(domain="hr")} == {"HR-001"}
    finally:
        repo.close()


def test_sqlite_repository_drafts_survive_policy_removal(tmp_path: Path) -> None:
    db_path = tmp_path / "store.db"
    repo = SqliteRepository(db_path)
    try:
        repo.add_requirement(make_requirement("HR-001"))
        repo.upsert_policy(make_policy("HR-001"))
        repo.record_draft(
            StoredDraft(
                id="d1",
                policy_id="HR-001",
                model="offline",
                request_id=None,
                unresolved=(),
                cedar="permit (...) ;",
                created_at=datetime.now(UTC),
            )
        )
        repo.remove_policy("HR-001")
        # Without an FK, drafts are preserved by their string policy_id;
        # latest_draft filters by policy_id, so the row is still discoverable.
        assert repo.latest_draft("HR-001").id == "d1"
    finally:
        repo.close()


def test_sqlite_repository_upsert_replaces(tmp_path: Path) -> None:
    db_path = tmp_path / "store.db"
    repo = SqliteRepository(db_path)
    try:
        repo.add_requirement(make_requirement("HR-001"))
        first = make_policy("HR-001")
        second = make_policy("HR-001")
        repo.upsert_policy(first)
        repo.upsert_policy(second)
        assert repo.get_policy("HR-001").updated_at == second.updated_at
    finally:
        repo.close()


def test_in_memory_repository_records_deployments() -> None:
    repo = InMemoryRepository()
    record = DeploymentRecord(
        id="d1",
        domain="hr",
        target="/tmp/hr",
        target_kind=DEPLOYMENT_KIND_LOCAL,
        bundle_hash="abc",
        status="deployed",
        created_at=datetime.now(UTC),
    )
    repo.record_deployment(record)
    assert repo.list_deployments() == [record]
    assert repo.list_deployments("hr") == [record]
    assert repo.list_deployments("finance") == []


def test_sqlite_repository_records_deployments(tmp_path: Path) -> None:
    db_path = tmp_path / "store.db"
    repo = SqliteRepository(db_path)
    try:
        record = DeploymentRecord(
            id="d1",
            domain="hr",
            target="/tmp/hr",
            target_kind=DEPLOYMENT_KIND_LOCAL,
            bundle_hash="abc",
            status="deployed",
            created_at=datetime.now(UTC),
        )
        repo.record_deployment(record)
        assert repo.list_deployments() == [record]
        assert repo.list_deployments("finance") == []
    finally:
        repo.close()
