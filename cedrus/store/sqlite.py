"""SQLite-backed implementation of the Repository Protocol.

Uses only the standard library ``sqlite3`` module. The database schema
is created on demand and migrations are idempotent.

Schema:
    Six tables back the entity types exposed by the Protocol:

    * ``meta`` — single-row metadata table recording the current
      schema version. The version is set in the same transaction as
      the schema change, so a partially-migrated database either has
      its declared version or does not exist at all.
    * ``requirements`` (id PRIMARY KEY)
    * ``policies`` (id PRIMARY KEY, requirement_id REFERENCES
      requirements(id) ON DELETE SET NULL)
    * ``drafts`` (id PRIMARY KEY, policy_id REFERENCES policies(id)
      logical via the policy_id string)
    * ``reports`` (id AUTOINCREMENT PRIMARY KEY, policy_id logical)
    * ``deployments`` (id PRIMARY KEY, domain indexed)

    The typed intent and per-slot scopes on ``policies`` and ``drafts``
    are stored as serialized JSON in dedicated ``*_json`` columns and
    re-hydrated to the typed objects on read. The serialization goes
    through :meth:`Intent.to_dict`, ``Scope.to_dict`` and
    :meth:`Payload.to_dict` so the wire format lives in one place.
    Older databases are upgraded in place by :meth:`Backend.migrate`,
    which adds the missing ``*_json`` columns; pre-migration rows are
    still readable through the typed dataclasses' permissive
    fallbacks.

Concurrency:
    :class:`Backend` enables ``journal_mode=WAL`` and
    ``busy_timeout=5000`` so concurrent readers do not block writers
    and transient lock contention waits instead of raising
    immediately. The class connects with ``check_same_thread=False``
    and guards every mutating call with an ``RLock``, so the same
    instance can be shared between threads. The Python GIL plus
    SQLite's connection-level serialization make this safe; the RLock
    is documentation as much as defense.

    For parallel use across processes, each process should open its
    own :class:`Backend` instance; SQLite's WAL mode handles the
    cross-process locking.

Attributes:
    Backend: SQLite-backed :class:`Repository` implementation.

See Also:
    :mod:`cedrus.store.base`: :class:`Repository` Protocol this module
        implements.
    :mod:`cedrus.store.memory`: In-memory repository implementation.
    :mod:`cedrus.migrate`: Migration helpers for upgrading pre-0.6.0
        row data (the schema migration in :meth:`Backend.migrate`
        adds the missing JSON columns but doesn't repopulate them).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cedrus.compile import Intent
from cedrus.data import Payload
from cedrus.deploy import Record
from cedrus.error import Store
from cedrus.need import Need
from cedrus.scope import Action, Principal, Resource
from cedrus.store.base import DraftStored, ReportStored, Stored

#: Current schema version. Bump whenever the SQLite schema changes in
#: a way that requires row data to be migrated.
SCHEMA_VERSION = 3

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
        cedar TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        intent_id TEXT,
        FOREIGN KEY (requirement_id) REFERENCES requirements(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS drafts (
        id TEXT PRIMARY KEY,
        policy_id TEXT,
        model TEXT NOT NULL,
        request_id TEXT,
        cedar TEXT NOT NULL,
        created_at TEXT NOT NULL,
        intent_id TEXT,
        principal_id TEXT,
        action_id TEXT,
        resource_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_id TEXT,
        kind TEXT NOT NULL,
        passed INTEGER NOT NULL,
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
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS principals (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        type_name TEXT,
        entity_id TEXT,
        group_type TEXT,
        group_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS actions (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        name TEXT,
        group TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resources (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        type_name TEXT,
        entity_id TEXT,
        parent_type TEXT,
        parent_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS clauses (
        id TEXT PRIMARY KEY,
        body TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS clause_attributes (
        clause_id TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        PRIMARY KEY (clause_id, key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS intents (
        id TEXT PRIMARY KEY,
        effect TEXT NOT NULL,
        requirement_id TEXT NOT NULL,
        principal_id TEXT NOT NULL,
        action_id TEXT NOT NULL,
        resource_id TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS intent_when_clauses (
        intent_id TEXT NOT NULL,
        position INTEGER NOT NULL,
        clause_id TEXT NOT NULL,
        PRIMARY KEY (intent_id, position)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS intent_unless_clauses (
        intent_id TEXT NOT NULL,
        position INTEGER NOT NULL,
        clause_id TEXT NOT NULL,
        PRIMARY KEY (intent_id, position)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS intent_notes (
        intent_id TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        PRIMARY KEY (intent_id, key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS draft_unresolved (
        draft_id TEXT NOT NULL,
        position INTEGER NOT NULL,
        item TEXT NOT NULL,
        PRIMARY KEY (draft_id, position)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS report_payload (
        report_id INTEGER NOT NULL,
        position INTEGER NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        PRIMARY KEY (report_id, position, key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS deployment_responses (
        deployment_id TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        PRIMARY KEY (deployment_id, key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meta (
        schema_version INTEGER PRIMARY KEY
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_policies_domain ON policies(domain)",
    "CREATE INDEX IF NOT EXISTS idx_drafts_policy ON drafts(policy_id)",
    "CREATE INDEX IF NOT EXISTS idx_reports_policy ON reports(policy_id)",
    "CREATE INDEX IF NOT EXISTS idx_deployments_domain ON deployments(domain)",
    "CREATE INDEX IF NOT EXISTS idx_intent_when_clauses ON intent_when_clauses(intent_id)",
    "CREATE INDEX IF NOT EXISTS idx_intent_unless_clauses ON intent_unless_clauses(intent_id)",
    "CREATE INDEX IF NOT EXISTS idx_draft_unresolved ON draft_unresolved(draft_id)",
    "CREATE INDEX IF NOT EXISTS idx_report_payload ON report_payload(report_id)",
    "CREATE INDEX IF NOT EXISTS idx_deployment_responses ON deployment_responses(deployment_id)",
)


#: Tables whose names are allowed in dynamic SQL. Anything outside
#: this allow-list is rejected, preventing the f-string interpolation
#: in :meth:`Backend.column_exists` from becoming a SQL injection
#: vector.
KNOWN_TABLES = frozenset(
    {"requirements", "policies", "drafts", "reports", "deployments", "meta"}
)


# ---------------------------------------------------------------------------
# SQLite repository
# ---------------------------------------------------------------------------


@dataclass
class Backend:
    """SQLite-backed :class:`~cedrus.store.base.Repository`.

    Attributes:
        path: Filesystem location of the SQLite database file. The
            parent directory is created on construction.
        connection: Open :class:`sqlite3.Connection` to the database.
        lock: Re-entrant lock guarding every mutating call.
    """

    path: Path
    connection: sqlite3.Connection = field(init=False)
    lock: threading.RLock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        # Foreign keys are off by default in sqlite3; enable them so the
        # ON DELETE SET NULL clause on policies.requirement_id fires.
        self.connection.execute("PRAGMA foreign_keys = ON")
        # Production-grade PRAGMA set: WAL for concurrent readers,
        # busy_timeout for transient contention, synchronous=NORMAL
        # for the standard durability/speed trade-off.
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self.connection.execute("PRAGMA synchronous = NORMAL")
        self.migrate()

    def column_exists(self, table: str, column: str) -> bool:
        """Return ``True`` when ``table.column`` exists in the schema.

        Args:
            table: Table name to inspect. Must be a known table name
                (``requirements``, ``policies``, ``drafts``,
                ``reports``, ``deployments``, ``meta``); anything
                else raises :class:`Store` rather than interpolating
                user input into a SQL statement.
            column: Column name to look up.

        Returns:
            ``True`` if the column is present.

        Raises:
            Store: If ``table`` is not a known table.
        """
        if table not in KNOWN_TABLES:
            raise Store(f"unknown table for column_exists: {table!r}")
        rows = self.connection.execute(
            "SELECT name FROM pragma_table_info(?) WHERE name = ?", (table, column)
        ).fetchall()
        return bool(rows)

    def migrate(self) -> None:
        """Create schema objects and add 0.6.0 columns when missing.

        Idempotent: every ``CREATE`` uses ``IF NOT EXISTS`` and every
        ``ALTER`` is guarded by :meth:`column_exists`. The schema
        version is set inside the same transaction as the schema
        changes, so a partially-migrated database either has its
        declared version or does not exist at all.
        """
        with self.connection:
            for statement in SCHEMA_STATEMENTS:
                self.connection.execute(statement)
            for statement in ALTER_INTENT_JSON:
                column = statement.split("ADD COLUMN")[-1].split()[0]
                if not self.column_exists("policies", column):
                    self.connection.execute(statement)
            for statement in ALTER_DRAFT_COLUMNS:
                column = statement.split("ADD COLUMN")[-1].split()[0]
                if not self.column_exists("drafts", column):
                    self.connection.execute(statement)
            self.stamp_schema_version()

    def stamp_schema_version(self) -> None:
        """Insert or update the ``meta.schema_version`` row in this transaction."""
        row = self.connection.execute("SELECT schema_version FROM meta").fetchone()
        if row is None:
            self.connection.execute(
                "INSERT INTO meta (schema_version) VALUES (?)", (SCHEMA_VERSION,)
            )
        elif row["schema_version"] != SCHEMA_VERSION:
            self.connection.execute(
                "UPDATE meta SET schema_version = ?", (SCHEMA_VERSION,)
            )

    def schema_version(self) -> int:
        """Return the schema version recorded in the ``meta`` table.

        Returns ``0`` when the database has not yet been stamped (which
        means an empty or pre-0.6.0 database).
        """
        row = self.connection.execute("SELECT schema_version FROM meta").fetchone()
        if row is None:
            return 0
        return int(row["schema_version"])

    def close(self) -> None:
        """Close the underlying database connection.

        Idempotent: subsequent calls are no-ops because the underlying
        :class:`sqlite3.Connection.close` is itself idempotent.
        """
        try:
            self.connection.close()
        except sqlite3.ProgrammingError:
            pass

    def add_requirement(self, requirement: Need) -> None:
        """Add or replace ``requirement`` in the store.

        Uses ``ON CONFLICT(id) DO UPDATE`` so re-adding the same
        identifier updates the existing row instead of failing.

        Args:
            requirement: Need to store.
        """
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

    def get_requirement(self, requirement_id: str) -> Need:
        """Return the requirement with ``requirement_id``.

        Args:
            requirement_id: Identifier of the requirement to fetch.

        Returns:
            The stored :class:`Need`.

        Raises:
            Store: If no requirement exists with that id.
        """
        row = self.connection.execute(
            "SELECT * FROM requirements WHERE id = ?", (requirement_id,)
        ).fetchone()
        if row is None:
            raise Store(f"requirement {requirement_id!r} not found")

        return Need.from_row(dict(row))

    def list_requirements(self, domain: str | None = None) -> Sequence[Need]:
        """Return all requirements, optionally filtered by ``domain``.

        Args:
            domain: When provided, only requirements whose ``domain``
                matches are returned.

        Returns:
            A sequence of :class:`Need` objects in id order.
        """
        if domain is None:
            rows = self.connection.execute(
                "SELECT * FROM requirements ORDER BY id"
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM requirements WHERE domain = ? ORDER BY id", (domain,)
            ).fetchall()

        return [Need.from_row(dict(row)) for row in rows]

    def remove_requirement(self, requirement_id: str) -> None:
        """Remove the requirement with ``requirement_id``.

        Args:
            requirement_id: Identifier of the requirement to remove.

        Raises:
            Store: If no requirement exists with that id.
        """
        with self.connection:
            cursor = self.connection.execute(
                "DELETE FROM requirements WHERE id = ?", (requirement_id,)
            )
            if cursor.rowcount == 0:
                raise Store(f"requirement {requirement_id!r} not found")

    def upsert_policy(self, policy: Stored) -> None:
        """Insert or update ``policy`` in the store.

        The ``intent`` and ``action`` fields are serialized to JSON
        when present; ``None`` is persisted as SQL ``NULL``.

        Args:
            policy: Policy row to upsert.
        """
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO policies
                    (id, domain, requirement_id, intent_json, cedar, status,
                     created_at, updated_at, action_scope_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    domain = excluded.domain,
                    requirement_id = excluded.requirement_id,
                    intent_json = excluded.intent_json,
                    cedar = excluded.cedar,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    action_scope_json = excluded.action_scope_json
                """,
                (
                    policy.id,
                    policy.domain,
                    policy.requirement_id,
                    json.dumps(policy.intent.to_dict(), sort_keys=True)
                    if policy.intent is not None
                    else None,
                    policy.cedar,
                    policy.status,
                    policy.created_at.isoformat(),
                    policy.updated_at.isoformat(),
                    json.dumps(policy.action.to_dict(), sort_keys=True)
                    if policy.action is not None
                    else None,
                ),
            )

    def get_policy(self, policy_id: str) -> Stored:
        """Return the policy with ``policy_id``.

        Args:
            policy_id: Identifier of the policy to fetch.

        Returns:
            The stored :class:`Stored`.

        Raises:
            Store: If no policy exists with that id.
        """
        row = self.connection.execute(
            "SELECT * FROM policies WHERE id = ?", (policy_id,)
        ).fetchone()
        if row is None:
            raise Store(f"policy {policy_id!r} not found")
        return Stored.from_row(dict(row))

    def list_policies(self, domain: str | None = None) -> Sequence[Stored]:
        """Return all policies, optionally filtered by ``domain``.

        Args:
            domain: When provided, only policies whose ``domain``
                matches are returned.

        Returns:
            A sequence of :class:`Stored` in id order.
        """
        if domain is None:
            rows = self.connection.execute(
                "SELECT * FROM policies ORDER BY id"
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM policies WHERE domain = ? ORDER BY id", (domain,)
            ).fetchall()
        return [Stored.from_row(dict(row)) for row in rows]

    def remove_policy(self, policy_id: str) -> None:
        """Remove the policy with ``policy_id``.

        Args:
            policy_id: Identifier of the policy to remove.

        Raises:
            Store: If no policy exists with that id.
        """
        with self.connection:
            cursor = self.connection.execute(
                "DELETE FROM policies WHERE id = ?", (policy_id,)
            )
            if cursor.rowcount == 0:
                raise Store(f"policy {policy_id!r} not found")

    def record_draft(self, draft: DraftStored) -> None:
        """Append ``draft`` to the draft history.

        The intent and per-slot scopes are serialized to JSON for
        storage and rehydrated inline in :meth:`latest_draft` /
        :meth:`list_drafts` on read.

        Args:
            draft: Draft row to record.
        """
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO drafts
                    (id, policy_id, model, request_id, unresolved_json,
                     cedar, created_at, intent_json, principal_scope_json,
                     action_scope_json, resource_scope_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft.id,
                    draft.policy_id,
                    draft.model,
                    draft.request_id,
                    json.dumps(list(draft.unresolved)),
                    draft.cedar,
                    draft.created_at.isoformat(),
                    json.dumps(draft.intent.to_dict(), sort_keys=True),
                    json.dumps(draft.principal.to_dict(), sort_keys=True),
                    json.dumps(draft.action.to_dict(), sort_keys=True),
                    json.dumps(draft.resource.to_dict(), sort_keys=True),
                ),
            )

    def update_draft_scopes(
        self,
        draft_id: str,
        *,
        intent: Intent | None = None,
        principal: Principal | None = None,
        action: Action | None = None,
        resource: Resource | None = None,
    ) -> None:
        """Update one or more typed-scope columns on a stored draft.

        Mirrors :meth:`Memory.update_draft_scopes`. Each typed-object
        keyword is optional; passing ``None`` (the default) leaves the
        corresponding ``*_json`` column untouched. Used by the 0.6.0
        migration to populate legacy rows in place.

        Args:
            draft_id: Identifier of the draft to update.
            intent: Replacement :class:`Intent`, or ``None`` to leave
                the existing value in place.
            principal: Replacement :class:`Principal`, or ``None`` to
                leave the existing value in place.
            action: Replacement :class:`Action`, or ``None`` to leave
                the existing value in place.
            resource: Replacement :class:`Resource`, or ``None`` to
                leave the existing value in place.
        """
        assignments: list[str] = []
        values: list[str] = []
        if intent is not None:
            assignments.append("intent_json = ?")
            values.append(json.dumps(intent.to_dict(), sort_keys=True))
        if principal is not None:
            assignments.append("principal_scope_json = ?")
            values.append(json.dumps(principal.to_dict(), sort_keys=True))
        if action is not None:
            assignments.append("action_scope_json = ?")
            values.append(json.dumps(action.to_dict(), sort_keys=True))
        if resource is not None:
            assignments.append("resource_scope_json = ?")
            values.append(json.dumps(resource.to_dict(), sort_keys=True))
        if not assignments:
            return
        with self.connection:
            self.connection.execute(
                f"UPDATE drafts SET {', '.join(assignments)} WHERE id = ?",
                [*values, draft_id],
            )

    def latest_draft(self, policy_id: str) -> DraftStored:
        """Return the most recent draft for ``policy_id``.

        Args:
            policy_id: Identifier of the policy to query.

        Returns:
            The most recent :class:`DraftStored` for ``policy_id``.

        Raises:
            Store: If no drafts exist for ``policy_id``.
        """
        row = self.connection.execute(
            "SELECT * FROM drafts WHERE policy_id = ? ORDER BY created_at DESC LIMIT 1",
            (policy_id,),
        ).fetchone()
        if row is None:
            raise Store(f"no drafts for policy {policy_id!r}")
        return DraftStored.from_row(dict(row))

    def list_drafts(self, policy_id: str | None = None) -> Sequence[DraftStored]:
        """Return all drafts, optionally filtered by ``policy_id``.

        Args:
            policy_id: When provided, only drafts whose ``policy_id``
                matches are returned.

        Returns:
            A sequence of :class:`DraftStored` in insertion order.
        """
        if policy_id is None:
            rows = self.connection.execute(
                "SELECT * FROM drafts ORDER BY created_at"
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM drafts WHERE policy_id = ? ORDER BY created_at",
                (policy_id,),
            ).fetchall()
        return [DraftStored.from_row(dict(row)) for row in rows]

    def record_report(self, report: ReportStored) -> None:
        """Append ``report`` to the report history.

        The typed :class:`Payload` is serialized to JSON for storage
        and rehydrated inline in :meth:`latest_report` on read.
        ``passed`` is persisted as ``0``/``1`` to match the column type.

        Args:
            report: Report row to record. ``created_at`` is required;
                callers should stamp it explicitly when constructing
                the row.
        """
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
                    json.dumps(report.payload.to_dict(), sort_keys=True),
                    report.created_at.isoformat(),
                ),
            )

    def latest_report(self, policy_id: str, kind: str) -> ReportStored:
        """Return the most recent report for ``policy_id`` of ``kind``.

        Args:
            policy_id: Identifier of the policy to query.
            kind: Report kind (``"validation"`` or ``"test"``).

        Returns:
            The most recent matching :class:`ReportStored`.

        Raises:
            Store: If no matching report exists.
        """
        row = self.connection.execute(
            "SELECT * FROM reports WHERE policy_id = ? AND kind = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (policy_id, kind),
        ).fetchone()
        if row is None:
            raise Store(f"no {kind} report for policy {policy_id!r}")
        return ReportStored.from_row(dict(row))

    def record_deployment(self, deployment: Record) -> None:
        """Append ``deployment`` to the deployment history.

        Args:
            deployment: Deployment record to store.
        """
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

    def transaction(self) -> Any:
        """Return a context manager that wraps the body in one SQL transaction.

        Every mutating call inside the block runs under the same
        connection transaction; if any statement raises, the
        transaction rolls back and none of the writes are persisted.

        Returns:
            A context manager.
        """
        import contextlib

        @contextlib.contextmanager
        def _cm() -> Any:
            with self.connection:
                yield None

        return _cm()

    def list_deployments(
        self, domain: str | None = None
    ) -> Sequence[Record]:
        """Return all deployments, optionally filtered by ``domain``.

        Args:
            domain: When provided, only deployments whose ``domain``
                matches are returned.

        Returns:
            A sequence of :class:`Record` in insertion order.
        """
        if domain is None:
            rows = self.connection.execute(
                "SELECT * FROM deployments ORDER BY created_at"
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM deployments WHERE domain = ? ORDER BY created_at",
                (domain,),
            ).fetchall()
        return [Record.from_row(dict(row)) for row in rows]


__all__ = ["Backend"]