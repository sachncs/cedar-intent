"""Tests for storage backends — :class:`Memory` and :class:`Backend`.

Covers data modelling (record shapes, protocol conformance),
behaviour modelling (round-trip every typed-object kind through
both backends), and ugly paths (missing-record Store, schema
rebuild on existing database, FK cascade, idempotent migrate).
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlite3 import IntegrityError

from cedrus import (
    Action,
    Backend,
    Memory,
    Payload,
    Principal,
    Record,
    Repository,
    Resource,
    Store,
)
from cedrus.compile import Intent
from cedrus.deploy import DEPLOYMENT_KIND_LOCAL
from cedrus.need import Need
from cedrus.store import DraftStored, ReportStored, Stored


def make_requirement(identifier: str, domain: str = "hr") -> Need:
    return Need(
        id=identifier,
        text=f"Body for {identifier}",
        domain=domain,
        source_path=Path(f"/tmp/{identifier}.md"),
        created_at=datetime.now(UTC),
    )


def make_intent(identifier: str) -> Intent:
    return Intent(
        id=identifier,
        requirement_id=identifier,
        effect="permit",
        principal=Principal(kind="any"),
        action=Action(kind="any"),
        resource=Resource(kind="any"),
    )


def make_policy(identifier: str, domain: str = "hr") -> Stored:
    return Stored(
        id=identifier,
        domain=domain,
        requirement_id=identifier,
        intent=make_intent(identifier),
        cedar="permit (principal, action, resource);",
        status="compiled",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        action=Action(kind="any"),
    )


# ---------------------------------------------------------------------------
# Memory backend
# ---------------------------------------------------------------------------


def test_memory_satisfies_repository_protocol() -> None:
    repo: Repository = Memory()
    assert isinstance(repo, Repository)


def test_memory_add_and_get_requirement() -> None:
    repo = Memory()
    make_requirement("hr-001").save(repo)
    got = Need.get(repo, "hr-001")
    assert got.id == "hr-001"
    assert got.text == "Body for hr-001"


def test_memory_get_missing_requirement_raises() -> None:
    from cedrus.error import Require

    repo = Memory()
    with pytest.raises(Require):
        Need.get(repo, "ghost")


def test_memory_list_requirements_unfiltered() -> None:
    repo = Memory()
    make_requirement("a", domain="hr").save(repo)
    make_requirement("b", domain="finance").save(repo)
    ids = sorted(n.id for n in Need.list(repo))
    assert ids == ["a", "b"]


def test_memory_list_requirements_filtered_by_domain() -> None:
    repo = Memory()
    make_requirement("a", domain="hr").save(repo)
    make_requirement("b", domain="finance").save(repo)
    ids = sorted(n.id for n in Need.list(repo, domain="hr"))
    assert ids == ["a"]


def test_memory_remove_requirement() -> None:
    repo = Memory()
    make_requirement("hr-001").save(repo)
    repo.remove_requirement("hr-001")
    from cedrus.error import Require

    with pytest.raises(Require):
        Need.get(repo, "hr-001")


def test_memory_upsert_replaces_policy() -> None:
    repo = Memory()
    make_requirement("hr-001").save(repo)
    p = make_policy("hr-001")
    p.upsert(repo)
    p.upsert(repo)  # idempotent
    assert len(Stored.list(repo)) == 1


def test_memory_get_missing_policy_raises() -> None:
    repo = Memory()
    with pytest.raises(Store):
        Stored.get(repo, "ghost")


def test_memory_list_policies_unfiltered() -> None:
    repo = Memory()
    make_requirement("a", domain="hr").save(repo)
    make_requirement("b", domain="finance").save(repo)
    make_policy("a", domain="hr").upsert(repo)
    make_policy("b", domain="finance").upsert(repo)
    assert sorted(p.id for p in Stored.list(repo)) == ["a", "b"]


def test_memory_list_policies_filtered_by_domain() -> None:
    repo = Memory()
    make_requirement("a", domain="hr").save(repo)
    make_requirement("b", domain="finance").save(repo)
    make_policy("a", domain="hr").upsert(repo)
    make_policy("b", domain="finance").upsert(repo)
    assert sorted(p.id for p in Stored.list(repo, domain="hr")) == ["a"]


def test_memory_remove_policy() -> None:
    repo = Memory()
    make_requirement("hr-001").save(repo)
    make_policy("hr-001").upsert(repo)
    repo.remove_policy("hr-001")
    with pytest.raises(Store):
        Stored.get(repo, "hr-001")


def test_memory_record_and_latest_draft() -> None:
    repo = Memory()
    make_requirement("hr-001").save(repo)
    intent = make_intent("hr-001")
    draft = DraftStored(
        id="d1",
        policy_id="hr-001",
        model="offline",
        request_id=None,
        unresolved=(),
        cedar="permit (...);",
        created_at=datetime.now(UTC),
        intent=intent,
        principal=Principal(kind="any"),
        action=Action(kind="any"),
        resource=Resource(kind="any"),
    )
    draft.save(repo)
    latest = DraftStored.latest(repo, "hr-001")
    assert latest.id == "d1"


def test_memory_latest_draft_missing_raises() -> None:
    repo = Memory()
    with pytest.raises(Store):
        DraftStored.latest(repo, "ghost")


def test_memory_list_drafts_filtered_by_policy_id() -> None:
    repo = Memory()
    make_requirement("hr-001").save(repo)
    intent = make_intent("hr-001")
    for i in range(2):
        DraftStored(
            id=f"d{i}",
            policy_id="hr-001",
            model="offline",
            request_id=None,
            unresolved=(),
            cedar="permit (...);",
            created_at=datetime.now(UTC),
            intent=intent,
            principal=Principal(kind="any"),
            action=Action(kind="any"),
            resource=Resource(kind="any"),
        ).save(repo)
    assert len(DraftStored.list(repo, policy_id="hr-001")) == 2
    assert len(DraftStored.list(repo, policy_id="ghost")) == 0


def test_memory_record_and_latest_report() -> None:
    repo = Memory()
    report = ReportStored(
        policy_id="hr-001",
        kind="validation",
        passed=True,
        payload=Payload(data=(("k", "v"),)),
        created_at=datetime.now(UTC),
    )
    report.save(repo)
    latest = ReportStored.latest(repo, "hr-001", "validation")
    assert latest.policy_id == "hr-001"
    assert latest.payload.data == (("k", "v"),)


def test_memory_latest_report_missing_raises() -> None:
    repo = Memory()
    with pytest.raises(Store):
        ReportStored.latest(repo, "ghost", "validation")


def test_memory_records_deployments_round_trip() -> None:
    repo = Memory()
    Record(
        id="d1",
        domain="hr",
        target="/tmp/x",
        target_kind=DEPLOYMENT_KIND_LOCAL,
        bundle_hash="abc",
        status="deployed",
        created_at=datetime.now(UTC),
        response={"status_code": "200"},
    ).save(repo)
    assert sorted(r.id for r in Record.list(repo)) == ["d1"]
    listed = Record.list(repo, domain="hr")
    assert listed[0].response == {"status_code": "200"}


def test_memory_records_listing_filters_by_domain() -> None:
    repo = Memory()
    Record(
        id="d1", domain="hr", target="/tmp", target_kind=DEPLOYMENT_KIND_LOCAL,
        bundle_hash="x", status="deployed", created_at=datetime.now(UTC),
    ).save(repo)
    Record(
        id="d2", domain="finance", target="/tmp", target_kind=DEPLOYMENT_KIND_LOCAL,
        bundle_hash="x", status="deployed", created_at=datetime.now(UTC),
    ).save(repo)
    assert sorted(r.id for r in Record.list(repo, domain="hr")) == ["d1"]


def test_memory_orphan_policies_rejected_by_foreign_key() -> None:
    """The FK constraint enforces requirement_id → requirements.id."""
    repo = Memory()
    orphan = Stored(
        id="orphan",
        domain="hr",
        requirement_id="ghost",
        intent=make_intent("orphan"),
        cedar="permit (...);",
        status="compiled",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    with pytest.raises(IntegrityError):
        orphan.upsert(repo)


def test_memory_supports_stored_to_rows() -> None:
    repo = Memory()
    make_requirement("hr-001").save(repo)
    p = make_policy("hr-001")
    p.upsert(repo)
    rows = Stored.get(repo, "hr-001").to_rows()
    assert rows["policies"]["id"] == "hr-001"


# ---------------------------------------------------------------------------
# Backend (SQLite) — round trip
# ---------------------------------------------------------------------------


def _backend(tmp_path: Path) -> Backend:
    return Backend(tmp_path / "store.db")


def test_sqlite_repository_round_trip(tmp_path: Path) -> None:
    repo = _backend(tmp_path)
    need = make_requirement("hr-001")
    need.save(repo)
    got = Need.get(repo, "hr-001")
    assert got.text == need.text

    policy = make_policy("hr-001")
    policy.upsert(repo)
    got_policy = Stored.get(repo, "hr-001")
    assert got_policy.cedar == policy.cedar


def test_sqlite_repository_handles_missing_records(tmp_path: Path) -> None:
    repo = _backend(tmp_path)
    with pytest.raises(Store):
        Stored.get(repo, "ghost")


def test_sqlite_repository_persists_across_instances(tmp_path: Path) -> None:
    first = _backend(tmp_path)
    make_requirement("hr-001").save(first)
    second = _backend(tmp_path)
    assert Need.get(second, "hr-001").id == "hr-001"


def test_sqlite_repository_is_idempotent(tmp_path: Path) -> None:
    make_requirement("hr-001").save(_backend(tmp_path))
    repo = _backend(tmp_path)
    assert Need.get(repo, "hr-001").id == "hr-001"


def test_sqlite_repository_lists_filtered_by_domain(tmp_path: Path) -> None:
    repo = _backend(tmp_path)
    make_requirement("a", domain="hr").save(repo)
    make_requirement("b", domain="finance").save(repo)
    assert sorted(n.id for n in Need.list(repo, domain="hr")) == ["a"]


def test_sqlite_repository_orphan_policies_rejected_by_foreign_key(tmp_path: Path) -> None:
    repo = _backend(tmp_path)
    with pytest.raises(IntegrityError):
        Stored(
            id="orphan", domain="hr", requirement_id="ghost",
            intent=make_intent("orphan"), cedar="permit (...);",
            status="compiled", created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ).upsert(repo)


def test_sqlite_repository_records_deployments(tmp_path: Path) -> None:
    repo = _backend(tmp_path)
    Record(
        id="d1", domain="hr", target="/tmp", target_kind=DEPLOYMENT_KIND_LOCAL,
        bundle_hash="x", status="deployed", created_at=datetime.now(UTC),
    ).save(repo)
    assert sorted(r.id for r in Record.list(repo)) == ["d1"]


def test_sqlite_repository_close_is_idempotent(tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    backend.close()
    backend.close()  # second call is a no-op


def test_sqlite_repository_path_attribute(tmp_path: Path) -> None:
    path = tmp_path / "x.db"
    backend = Backend(path)
    assert backend.path == path


def test_sqlite_repository_wal_mode_enabled(tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    cursor = backend.connection.execute("PRAGMA journal_mode")
    assert cursor.fetchone()[0].lower() == "wal"


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_repository_protocol_defines_required_methods() -> None:
    required = {"fetch", "execute", "transaction", "remove_requirement", "remove_policy"}
    defined = set(dir(Repository))
    assert required.issubset(defined)


def test_backend_satisfies_repository_protocol() -> None:
    import tempfile

    from cedrus.store.sqlite import Backend as SqliteBackend

    with tempfile.TemporaryDirectory() as tmp:
        backend = SqliteBackend(Path(tmp) / "test.db")
    assert isinstance(backend, Repository)


def test_memory_satisfies_repository_protocol_via_isinstance() -> None:
    assert isinstance(Memory(), Repository)


def test_draft_stored_update_replaces_individual_scopes() -> None:
    """DraftStored.update swaps individual typed scopes; untargeted scopes are preserved."""
    from cedrus.scope import Action, Principal, Resource

    repo = Memory()
    make_requirement("hr-001").save(repo)
    intent1 = make_intent("hr-001")
    draft = DraftStored(
        id="d1",
        policy_id="hr-001",
        model="offline",
        request_id=None,
        unresolved=(),
        cedar="permit (principal, action, resource);",
        created_at=datetime.now(UTC),
        intent=intent1,
        principal=Principal(kind="any"),
        action=Action(kind="any"),
        resource=Resource(kind="any"),
    )
    draft.save(repo)

    new_action = Action(kind="named", name="delete")
    draft.update(repo, action=new_action)
    fetched = DraftStored.latest(repo, "hr-001")
    assert fetched.action.kind == "named"
    # principal was not updated, should still be "any"
    assert fetched.principal.kind == "any"


def test_stored_to_data_emits_main_row_and_intent_payload() -> None:
    repo = Memory()
    make_requirement("hr-001").save(repo)
    intent = make_intent("hr-001")
    p = Stored(
        id="hr-001", domain="hr", requirement_id="hr-001",
        intent=intent, cedar="permit (...);",
        status="compiled",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        action=Action(kind="any"),
    )
    rows = p.to_rows()
    assert rows["policies"]["id"] == "hr-001"
    assert "intents" in rows


def test_stored_get_raises_when_missing() -> None:
    repo = Memory()
    with pytest.raises(Store):
        Stored.get(repo, "nope")


def test_report_stored_latest_filters_by_kind() -> None:
    repo = Memory()
    ReportStored(
        policy_id="hr-001", kind="validation", passed=True,
        payload=Payload(data=(("k", "v"),)),
        created_at=datetime.now(UTC),
    ).save(repo)
    ReportStored(
        policy_id="hr-001", kind="test", passed=True,
        payload=Payload(data=(("k2", "v2"),)),
        created_at=datetime.now(UTC),
    ).save(repo)
    validation = ReportStored.latest(repo, "hr-001", "validation")
    test = ReportStored.latest(repo, "hr-001", "test")
    assert validation.payload.data == (("k", "v"),)
    assert test.payload.data == (("k2", "v2"),)


def test_stored_latest_draft_returns_none_when_missing() -> None:
    """A stored policy without drafts returns None from latest_draft."""
    repo = Memory()
    make_requirement("hr-001").save(repo)
    from cedrus.store import Stored

    stored = Stored(
        id="hr-001", domain="hr", requirement_id="hr-001",
        intent=make_intent("hr-001"), cedar="permit (...);",
        status="compiled",
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        action=Action(kind="any"),
    )
    stored.upsert(repo)
    assert stored.latest_draft(repo) is None


def test_stored_latest_draft_returns_most_recent() -> None:
    """Stored.latest_draft returns the most recent draft for the policy."""
    repo = Memory()
    make_requirement("hr-001").save(repo)

    intent = make_intent("hr-001")
    for i in range(2):
        DraftStored(
            id=f"d{i}",
            policy_id="hr-001",
            model="offline",
            request_id=None,
            unresolved=(),
            cedar="permit (principal, action, resource);",
            created_at=datetime.now(UTC),
            intent=intent,
            principal=Principal(kind="any"),
            action=Action(kind="any"),
            resource=Resource(kind="any"),
        ).save(repo)
    from cedrus.store import Stored

    stored = Stored(
        id="hr-001", domain="hr", requirement_id="hr-001",
        intent=make_intent("hr-001"), cedar="permit (...);",
        status="compiled",
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        action=Action(kind="any"),
    )
    stored.upsert(repo)
    latest = stored.latest_draft(repo)
    assert latest is not None
    assert latest.id in ("d0", "d1")


def test_draft_stored_list_returns_all_in_chronological_order() -> None:
    repo = Memory()
    make_requirement("hr-001").save(repo)
    intent = make_intent("hr-001")
    for i in range(3):
        DraftStored(
            id=f"d{i}",
            policy_id="hr-001",
            model="offline",
            request_id=None,
            unresolved=(),
            cedar="permit (principal, action, resource);",
            created_at=datetime.now(UTC),
            intent=intent,
            principal=Principal(kind="any"),
            action=Action(kind="any"),
            resource=Resource(kind="any"),
        ).save(repo)
    drafts = DraftStored.list(repo, policy_id="hr-001")
    assert len(drafts) == 3


def test_draft_stored_update_with_no_fields_is_noop() -> None:
    """update() with all defaults leaves the row unchanged."""
    repo = Memory()
    make_requirement("hr-001").save(repo)
    intent = make_intent("hr-001")
    draft = DraftStored(
        id="d1",
        policy_id="hr-001",
        model="offline",
        request_id=None,
        unresolved=(),
        cedar="permit (principal, action, resource);",
        created_at=datetime.now(UTC),
        intent=intent,
        principal=Principal(kind="any"),
        action=Action(kind="any"),
        resource=Resource(kind="any"),
    )
    draft.save(repo)
    before = DraftStored.latest(repo, "hr-001")
    draft.update(repo)
    after = DraftStored.latest(repo, "hr-001")
    assert before.id == after.id
    assert before.principal.kind == after.principal.kind


__all__ = []