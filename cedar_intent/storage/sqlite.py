"""SQLite-backed implementation of the Repository Protocol.

Uses only the standard library ``sqlite3`` module. The database schema is
created on demand and migrations are idempotent.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..compiler import PolicyIntent
from ..deployment import DeploymentRecord
from ..errors import StorageError
from ..requirements import Requirement
from ..scopes import ActionScope, ConditionClause, PrincipalScope, ResourceScope
from .base import StoredDraft, StoredPolicy, StoredReport

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS requirements (
        id TEXT PRIMARY KEY,
        domain TEXT NOT NULL,
        text TEXT NOT NULL,
        source_path TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS policies (
        id TEXT PRIMARY KEY,
        domain TEXT NOT NULL,
        requirement_id TEXT,
        intent_json TEXT,
        cedar TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (requirement_id) REFERENCES requirements(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS drafts (
        id TEXT PRIMARY KEY,
        policy_id TEXT,
        model TEXT NOT NULL,
        request_id TEXT,
        unresolved_json TEXT NOT NULL,
        cedar TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_id TEXT,
        kind TEXT NOT NULL,
        passed INTEGER NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS deployments (
        id TEXT PRIMARY KEY,
        domain TEXT NOT NULL,
        target TEXT NOT NULL,
        target_kind TEXT NOT NULL,
        bundle_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        response_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_policies_domain ON policies(domain)",
    "CREATE INDEX IF NOT EXISTS idx_drafts_policy ON drafts(policy_id)",
    "CREATE INDEX IF NOT EXISTS idx_reports_policy ON reports(policy_id)",
    "CREATE INDEX IF NOT EXISTS idx_deployments_domain ON deployments(domain)",
)


@dataclass
class SqliteRepository:
    """SQLite-backed repository.

    Attributes:
        path: Filesystem location of the SQLite database file.
        connection: Open connection to the database.
    """

    path: Path
    connection: sqlite3.Connection = field(init=False)

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.migrate()

    def migrate(self) -> None:
        """Create schema objects that do not already exist."""
        with self.connection:
            for statement in SCHEMA_STATEMENTS:
                self.connection.execute(statement)

    def close(self) -> None:
        """Close the underlying database connection."""
        self.connection.close()

    def add_requirement(self, requirement: Requirement) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO requirements (id, domain, text, source_path, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    domain = excluded.domain,
                    text = excluded.text,
                    source_path = excluded.source_path
                """,
                (
                    requirement.id,
                    requirement.domain,
                    requirement.text,
                    str(requirement.source_path),
                    requirement.created_at.isoformat(),
                ),
            )

    def get_requirement(self, requirement_id: str) -> Requirement:
        row = self.connection.execute(
            "SELECT * FROM requirements WHERE id = ?", (requirement_id,)
        ).fetchone()
        if row is None:
            raise StorageError(f"requirement {requirement_id!r} not found")
        return requirement_from_row(dict(row))

    def list_requirements(self, domain: str | None = None) -> Sequence[Requirement]:
        if domain is None:
            rows = self.connection.execute(
                "SELECT * FROM requirements ORDER BY id"
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM requirements WHERE domain = ? ORDER BY id", (domain,)
            ).fetchall()
        return [requirement_from_row(dict(row)) for row in rows]

    def remove_requirement(self, requirement_id: str) -> None:
        with self.connection:
            cursor = self.connection.execute(
                "DELETE FROM requirements WHERE id = ?", (requirement_id,)
            )
            if cursor.rowcount == 0:
                raise StorageError(f"requirement {requirement_id!r} not found")

    def upsert_policy(self, policy: StoredPolicy) -> None:
        intent_payload = serialize_intent(policy.intent)
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO policies
                    (id, domain, requirement_id, intent_json, cedar, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    domain = excluded.domain,
                    requirement_id = excluded.requirement_id,
                    intent_json = excluded.intent_json,
                    cedar = excluded.cedar,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    policy.id,
                    policy.domain,
                    policy.requirement_id,
                    intent_payload,
                    policy.cedar,
                    policy.status,
                    policy.created_at.isoformat(),
                    policy.updated_at.isoformat(),
                ),
            )

    def get_policy(self, policy_id: str) -> StoredPolicy:
        row = self.connection.execute(
            "SELECT * FROM policies WHERE id = ?", (policy_id,)
        ).fetchone()
        if row is None:
            raise StorageError(f"policy {policy_id!r} not found")
        return policy_from_row(dict(row))

    def list_policies(self, domain: str | None = None) -> Sequence[StoredPolicy]:
        if domain is None:
            rows = self.connection.execute(
                "SELECT * FROM policies ORDER BY id"
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM policies WHERE domain = ? ORDER BY id", (domain,)
            ).fetchall()
        return [policy_from_row(dict(row)) for row in rows]

    def remove_policy(self, policy_id: str) -> None:
        with self.connection:
            cursor = self.connection.execute(
                "DELETE FROM policies WHERE id = ?", (policy_id,)
            )
            if cursor.rowcount == 0:
                raise StorageError(f"policy {policy_id!r} not found")

    def record_draft(self, draft: StoredDraft) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO drafts
                    (id, policy_id, model, request_id,
                     unresolved_json, cedar, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft.id,
                    draft.policy_id,
                    draft.model,
                    draft.request_id,
                    json.dumps(list(draft.unresolved)),
                    draft.cedar,
                    draft.created_at.isoformat(),
                ),
            )

    def latest_draft(self, policy_id: str) -> StoredDraft:
        row = self.connection.execute(
            "SELECT * FROM drafts WHERE policy_id = ? ORDER BY created_at DESC LIMIT 1",
            (policy_id,),
        ).fetchone()
        if row is None:
            raise StorageError(f"no drafts for policy {policy_id!r}")
        return draft_from_row(dict(row))

    def list_drafts(self, policy_id: str | None = None) -> Sequence[StoredDraft]:
        if policy_id is None:
            rows = self.connection.execute(
                "SELECT * FROM drafts ORDER BY created_at"
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM drafts WHERE policy_id = ? ORDER BY created_at",
                (policy_id,),
            ).fetchall()
        return [draft_from_row(dict(row)) for row in rows]

    def record_report(self, report: StoredReport) -> None:
        created_at = report.created_at or datetime.now(UTC)
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO reports (policy_id, kind, passed, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    report.policy_id,
                    report.kind,
                    1 if report.passed else 0,
                    json.dumps(report.payload),
                    created_at.isoformat(),
                ),
            )

    def latest_report(self, policy_id: str, kind: str) -> StoredReport:
        row = self.connection.execute(
            "SELECT * FROM reports WHERE policy_id = ? AND kind = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (policy_id, kind),
        ).fetchone()
        if row is None:
            raise StorageError(f"no {kind} report for policy {policy_id!r}")
        return report_from_row(dict(row))

    def record_deployment(self, deployment: DeploymentRecord) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO deployments
                    (id, domain, target, target_kind,
                     bundle_hash, status, response_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    deployment.id,
                    deployment.domain,
                    deployment.target,
                    deployment.target_kind,
                    deployment.bundle_hash,
                    deployment.status,
                    json.dumps(dict(deployment.response)),
                    deployment.created_at.isoformat(),
                ),
            )

    def list_deployments(
        self, domain: str | None = None
    ) -> Sequence[DeploymentRecord]:
        if domain is None:
            rows = self.connection.execute(
                "SELECT * FROM deployments ORDER BY created_at"
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM deployments WHERE domain = ? ORDER BY created_at",
                (domain,),
            ).fetchall()
        return [deployment_from_row(dict(row)) for row in rows]


def serialize_intent(intent: PolicyIntent | None) -> str | None:
    """Serialize a :class:`PolicyIntent` to a JSON string."""
    if intent is None:
        return None
    payload = {
        "id": intent.id,
        "requirement_id": intent.requirement_id,
        "effect": intent.effect,
        "principal": {
            "kind": intent.principal.kind,
            "type_name": intent.principal.type_name,
            "entity_id": intent.principal.entity_id,
            "group_type": intent.principal.group_type,
            "group_id": intent.principal.group_id,
        },
        "action": {
            "kind": intent.action.kind,
            "name": intent.action.name,
            "group": intent.action.group,
        },
        "resource": {
            "kind": intent.resource.kind,
            "type_name": intent.resource.type_name,
            "entity_id": intent.resource.entity_id,
            "parent_type": intent.resource.parent_type,
            "parent_id": intent.resource.parent_id,
        },
        "when_clauses": [clause.body for clause in intent.when_clauses],
        "unless_clauses": [clause.body for clause in intent.unless_clauses],
        "notes": dict(intent.notes),
    }
    return json.dumps(payload, sort_keys=True)


def deserialize_intent(payload: str | None) -> PolicyIntent | None:
    """Deserialize a :class:`PolicyIntent` from its JSON representation."""
    if not payload:
        return None
    data = json.loads(payload)
    return PolicyIntent(
        id=data["id"],
        requirement_id=data["requirement_id"],
        effect=data["effect"],
        principal=PrincipalScope(
            kind=data["principal"]["kind"],
            type_name=data["principal"].get("type_name"),
            entity_id=data["principal"].get("entity_id"),
            group_type=data["principal"].get("group_type"),
            group_id=data["principal"].get("group_id"),
        ),
        action=ActionScope(
            kind=data["action"]["kind"],
            name=data["action"].get("name"),
            group=data["action"].get("group"),
        ),
        resource=ResourceScope(
            kind=data["resource"]["kind"],
            type_name=data["resource"].get("type_name"),
            entity_id=data["resource"].get("entity_id"),
            parent_type=data["resource"].get("parent_type"),
            parent_id=data["resource"].get("parent_id"),
        ),
        when_clauses=tuple(ConditionClause(body=body) for body in data.get("when_clauses", [])),
        unless_clauses=tuple(
            ConditionClause(body=body) for body in data.get("unless_clauses", [])
        ),
        notes=dict(data.get("notes", {})),
    )


def requirement_from_row(row: dict[str, Any]) -> Requirement:
    """Build a :class:`Requirement` from a SQLite row dictionary."""
    from pathlib import Path

    return Requirement(
        id=row["id"],
        text=row["text"],
        domain=row["domain"],
        source_path=Path(row["source_path"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def policy_from_row(row: dict[str, Any]) -> StoredPolicy:
    """Build a :class:`StoredPolicy` from a SQLite row dictionary."""
    return StoredPolicy(
        id=row["id"],
        domain=row["domain"],
        requirement_id=row["requirement_id"],
        intent=deserialize_intent(row["intent_json"]),
        cedar=row["cedar"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def draft_from_row(row: dict[str, Any]) -> StoredDraft:
    """Build a :class:`StoredDraft` from a SQLite row dictionary."""
    return StoredDraft(
        id=row["id"],
        policy_id=row["policy_id"],
        model=row["model"],
        request_id=row["request_id"],
        unresolved=tuple(json.loads(row["unresolved_json"])),
        cedar=row["cedar"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def report_from_row(row: dict[str, Any]) -> StoredReport:
    """Build a :class:`StoredReport` from a SQLite row dictionary."""
    return StoredReport(
        policy_id=row["policy_id"],
        kind=row["kind"],
        passed=bool(row["passed"]),
        payload=json.loads(row["payload_json"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def deployment_from_row(row: dict[str, Any]) -> DeploymentRecord:
    """Build a :class:`DeploymentRecord` from a SQLite row dictionary."""
    return DeploymentRecord(
        id=row["id"],
        domain=row["domain"],
        target=row["target"],
        target_kind=row["target_kind"],
        bundle_hash=row["bundle_hash"],
        status=row["status"],
        response=dict(json.loads(row["response_json"])),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


__all__ = ["SqliteRepository"]
