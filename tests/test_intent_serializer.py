"""Tests for the canonical intent JSON serializer.

Before this refactor, the storage and verification layers each had
their own (incompatible) intent JSON format. The canonical format now
lives in :mod:`cedar_intent.scope_json` and both layers round-trip
through it. These tests pin the contract:

* ``intent_to_dict``/``intent_from_dict`` are inverses.
* The canonical wire format uses ``when_clauses``/``unless_clauses``.
* Readers accept the legacy ``when``/``unless`` short form for
  backward compatibility with stored rows.
* Condition attributes round-trip when present.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from cedar_intent import PolicyIntent, Workspace
from cedar_intent.compiler import PolicyIntent as CompilerPolicyIntent  # noqa: F401
from cedar_intent.scope_json import (
    intent_from_dict,
    intent_to_dict,
)
from cedar_intent.scopes import (
    ActionScope,
    ConditionClause,
    PrincipalScope,
    ResourceScope,
)


def _make_intent() -> PolicyIntent:
    return PolicyIntent(
        id="HR-042",
        requirement_id="HR-042",
        effect="permit",
        principal=PrincipalScope(kind="is_type", type_name="User"),
        action=ActionScope(kind="named", name="view", namespace="hr"),
        resource=ResourceScope(kind="is_type", type_name="Photo"),
        when_clauses=(
            ConditionClause(body="principal.owner == resource.owner"),
            ConditionClause(
                body="context.clientIp != null",
                attributes={"category": "network"},
            ),
        ),
        unless_clauses=(),
        notes={"generator": "offline"},
    )


def test_intent_to_dict_uses_canonical_keys() -> None:
    payload = intent_to_dict(_make_intent())
    assert payload is not None
    assert "when_clauses" in payload
    assert "unless_clauses" in payload
    assert "when" not in payload
    assert "unless" not in payload


def test_intent_round_trip_through_dict() -> None:
    original = _make_intent()
    payload = intent_to_dict(original)
    assert payload is not None
    rebuilt = intent_from_dict(payload)
    assert rebuilt is not None
    assert rebuilt.id == original.id
    assert rebuilt.requirement_id == original.requirement_id
    assert rebuilt.effect == original.effect
    assert rebuilt.principal == original.principal
    assert rebuilt.action == original.action
    assert rebuilt.resource == original.resource
    assert rebuilt.when_clauses == original.when_clauses
    assert rebuilt.unless_clauses == original.unless_clauses
    assert rebuilt.notes == original.notes


def test_intent_round_trip_through_json() -> None:
    """Round-trip through json.dumps/loads (the path storage uses)."""
    original = _make_intent()
    payload = intent_to_dict(original)
    assert payload is not None
    raw = json.dumps(payload, sort_keys=True)
    rebuilt = intent_from_dict(json.loads(raw))
    assert rebuilt is not None
    assert rebuilt == original


def test_intent_from_dict_accepts_legacy_when_unless() -> None:
    """The legacy short form ``when``/``unless`` is still readable."""
    legacy = {
        "id": "HR-001",
        "requirement_id": "HR-001",
        "effect": "permit",
        "principal": {"kind": "any"},
        "action": {"kind": "any"},
        "resource": {"kind": "any"},
        "when": ["principal == User::\"alice\""],
        "unless": [],
        "notes": {},
    }
    intent = intent_from_dict(legacy)
    assert intent is not None
    assert len(intent.when_clauses) == 1
    assert intent.when_clauses[0].body == "principal == User::\"alice\""
    assert intent.unless_clauses == ()


def test_intent_from_dict_accepts_short_form_string_array() -> None:
    """``condition_clauses_from_list`` accepts strings and dicts."""
    from cedar_intent.scope_json import condition_clauses_from_list

    assert condition_clauses_from_list(["body-1", "body-2"]) == (
        ConditionClause(body="body-1"),
        ConditionClause(body="body-2"),
    )
    assert condition_clauses_from_list(
        [{"body": "x", "attributes": {"k": "v"}}, "y"]
    ) == (
        ConditionClause(body="x", attributes={"k": "v"}),
        ConditionClause(body="y"),
    )


def test_intent_to_dict_none_returns_none() -> None:
    assert intent_to_dict(None) is None
    assert intent_from_dict(None) is None


def test_workspace_stored_draft_round_trip(tmp_path: Path) -> None:
    """Workspace-built StoredDraft round-trips through intent_from_dict.

    This is the integration check: build_stored_draft (workspace.py)
    writes with the canonical format, intent_from_draft (workspace.py)
    reads with the canonical format.
    """
    from cedar_intent import Requirement
    from cedar_intent.generator import DraftProposal, GenerationResult
    from cedar_intent.policies import DraftPolicy
    from cedar_intent.workspace import build_stored_draft

    requirement = Requirement(
        id="HR-042",
        text="Body",
        domain="hr",
        source_path=Path("/tmp/HR-042.md"),
        created_at=datetime.now(UTC),
    )
    intent = _make_intent()
    draft = DraftPolicy(
        id="draft-1",
        requirement=requirement,
        intent=intent,
        principal=intent.principal,
        action=intent.action,
        resource=intent.resource,
        cedar='permit (principal, action, resource);',
        unresolved=(),
        notes={},
    )
    result = GenerationResult(
        proposal=DraftProposal(
            intent=intent,
            unresolved=(),
            notes={"generator": "offline"},
        ),
        model="offline",
        request_id=None,
        usage={},
    )
    stored = build_stored_draft(draft, result, draft.cedar)
    assert stored.intent_json is not None
    payload = json.loads(stored.intent_json)
    assert "when_clauses" in payload
    rebuilt = intent_from_dict(payload)
    assert rebuilt is not None
    assert rebuilt.id == intent.id
    assert rebuilt.when_clauses == intent.when_clauses


def test_sqlite_storage_uses_canonical_keys(tmp_path: Path) -> None:
    """Stored rows use the canonical ``when_clauses`` key."""
    from cedar_intent import Requirement
    from cedar_intent.scopes import (
        ActionScope,
        PrincipalScope,
        ResourceScope,
    )

    workspace = Workspace.create(tmp_path / "acme")
    workspace.repository.add_requirement(
        Requirement(
            id="HR-042",
            text="Body",
            domain="hr",
            source_path=Path("/tmp/HR-042.md"),
            created_at=datetime.now(UTC),
        )
    )
    intent = PolicyIntent(
        id="HR-042",
        requirement_id="HR-042",
        effect="permit",
        principal=PrincipalScope(kind="any"),
        action=ActionScope(kind="named", name="view", namespace="hr"),
        resource=ResourceScope(kind="any"),
        when_clauses=(
            ConditionClause(body="principal == User::\"alice\""),
        ),
        unless_clauses=(),
    )
    cedar = 'permit (principal, action == hr::Action::"view", resource);'
    from cedar_intent.storage.base import StoredPolicy

    workspace.repository.upsert_policy(
        StoredPolicy(
            id="HR-042",
            domain="hr",
            requirement_id="HR-042",
            intent=intent,
            cedar=cedar,
            status="compiled",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            action_scope_json=json.dumps(
                {"kind": "named", "name": "view", "namespace": "hr"}
            ),
        )
    )
    with sqlite3.connect(workspace.repository.path) as conn:
        row = conn.execute(
            "SELECT intent_json FROM policies WHERE id = ?", ("HR-042",)
        ).fetchone()
    assert row is not None
    payload = json.loads(row[0])
    assert "when_clauses" in payload
    assert payload["when_clauses"][0]["body"] == "principal == User::\"alice\""


def test_migration_uses_canonical_keys(tmp_path: Path) -> None:
    """migrate_legacy_rows writes the canonical format on upgrade."""
    from cedar_intent.migrations import migrate_legacy_rows

    workspace = Workspace.create(tmp_path / "acme")
    db = workspace.repository.path
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "Body", "/tmp/HR-001.md", now),
        )
        conn.execute(
            "INSERT INTO policies (id, domain, requirement_id, intent_json, cedar, "
            "status, created_at, updated_at, action_scope_json) "
            "VALUES (?, ?, ?, NULL, ?, ?, ?, ?, NULL)",
            (
                "HR-001",
                "hr",
                "HR-001",
                'permit (principal, action == Action::"view", resource);',
                "compiled",
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO drafts (id, policy_id, model, request_id, "
            "unresolved_json, cedar, created_at, intent_json, "
            "principal_scope_json, action_scope_json, resource_scope_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL)",
            (
                "draft-1",
                "HR-001",
                "offline",
                None,
                "[]",
                'permit (principal, action == Action::"view", resource);',
                now,
            ),
        )
        conn.execute("DELETE FROM meta")
        conn.commit()
    upgraded = migrate_legacy_rows(workspace.repository)
    assert upgraded >= 1
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT intent_json FROM drafts WHERE policy_id = ?", ("HR-001",)
        ).fetchone()
    assert row is not None
    payload = json.loads(row[0])
    # The migration writes the canonical format.
    assert "when_clauses" in payload
