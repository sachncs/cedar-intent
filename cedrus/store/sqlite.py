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
    Older databases are upgraded in place by :meth:`Sqlite.migrate`
    followed by a strict-refusal check in :meth:`Sqlite.__post_init__`
    that raises :class:`Store` when any legacy row remains.

Concurrency:
    ``Sqlite`` enables ``journal_mode=WAL`` and
    ``busy_timeout=5000`` so concurrent readers do not block writers
    and transient lock contention waits instead of raising
    immediately. The class connects with ``check_same_thread=False``
    and guards every mutating call with an ``RLock``, so the same
    instance can be shared between threads. The Python GIL plus
    SQLite's connection-level serialization make this safe; the RLock
    is documentation as much as defense.

    For parallel use across processes, each process should open its
    own :class:`Sqlite` instance; SQLite's WAL mode handles the
    cross-process locking.

Attributes:
    Sqlite: SQLite-backed :class:`Repository` implementation.
    serialize_intent: Convert a typed :class:`Intent` to a JSON string
        for SQLite storage.
    deserialize_intent: Rehydrate a typed :class:`Intent` from its
        SQLite JSON column.
    serialize_scope: Convert a typed :class:`Scope` to a JSON string.
    deserialize_scope: Rehydrate a typed :class:`Scope` from its
        SQLite JSON column (typed on the caller-supplied scope class).
    serialize_payload: Convert a typed :class:`Payload` to a JSON string.
    deserialize_payload: Rehydrate a typed :class:`Payload` from its
        SQLite JSON column.
    requirement_from_row: Build a :class:`Need` from a ``requirements``
        SQLite row dict.
    policy_from_row: Build a :class:`Stored` from a ``policies`` SQLite
        row dict.
    draft_from_row: Build a :class:`DraftStored` from a ``drafts``
        SQLite row dict.
    report_from_row: Build a :class:`ReportStored` from a ``reports``
        SQLite row dict.
    deployment_from_row: Build a :class:`~cedrus.deploy.Record` from a
        ``deployments`` SQLite row dict.

See Also:
    :mod:`cedrus.store.base`: :class:`Repository` Protocol this module
        implements.
    :mod:`cedrus.store.memory`: In-memory repository implementation.
    :mod:`cedrus.migrate`: Migration helpers for pre-0.6.0 databases.
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
from cedrus.scope import Action, Principal, Resource, Scope

#: Current schema version. Bump whenever the SQLite schema changes in
#: a way that requires row data to be migrated.
SCHEMA_VERSION = 2

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
        action_scope_json TEXT,
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
        created_at TEXT NOT NULL,
        intent_json TEXT,
        principal_scope_json TEXT,
        action_scope_json TEXT,
        resource_scope_json TEXT
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
    """
    CREATE TABLE IF NOT EXISTS meta (
        schema_version INTEGER PRIMARY KEY
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_policies_domain ON policies(domain)",
    "CREATE INDEX IF NOT EXISTS idx_drafts_policy ON drafts(policy_id)",
    "CREATE INDEX IF NOT EXISTS idx_reports_policy ON reports(policy_id)",
    "CREATE INDEX IF NOT EXISTS idx_deployments_domain ON deployments(domain)",
)


#: ALTER TABLE statements that add the new ``*_json`` columns
#: introduced in 0.6.0. Each statement is wrapped in a check against
#: ``sqlite_master`` so it is idempotent. ``ALTER TABLE ...
#: ADD COLUMN`` does not accept ``IF NOT EXISTS`` on older SQLite
#: versions, hence the manual guard.
ALTER_INTENT_JSON = (
    "ALTER TABLE policies ADD COLUMN action_scope_json TEXT",
)
ALTER_DRAFT_COLUMNS = (
    "ALTER TABLE drafts ADD COLUMN intent_json TEXT",
    "ALTER TABLE drafts ADD COLUMN principal_scope_json TEXT",
    "ALTER TABLE drafts ADD COLUMN action_scope_json TEXT",
    "ALTER TABLE drafts ADD COLUMN resource_scope_json TEXT",
)


#: Tables whose names are allowed in dynamic SQL. Anything outside
#: this allow-list is rejected, preventing the f-string interpolation
#: in :meth:`Sqlite.column_exists` from becoming a SQL injection
#: vector.
KNOWN_TABLES = frozenset(
    {"requirements", "policies", "drafts", "reports", "deployments", "meta"}
)


# ---------------------------------------------------------------------------
# Typed serialization helpers
# ---------------------------------------------------------------------------


def serialize_intent(intent: Intent | None) -> str | None:
    """Convert a typed :class:`Intent` to a JSON string for SQLite storage.

    Thin wrapper around :meth:`Intent.to_dict`. ``None`` is persisted
    as SQL ``NULL``.

    Args:
        intent: The intent to serialize, or ``None``.

    Returns:
        The JSON string, or ``None`` if ``intent`` is ``None``.
    """
    if intent is None:
        return None
    return json.dumps(intent.to_dict(), sort_keys=True)


def deserialize_intent(payload: str | None) -> Intent | None:
    """Rehydrate a typed :class:`Intent` from its SQLite JSON column.

    Thin wrapper around :meth:`Intent.from_dict`. Returns ``None``
    for empty payloads (the legacy form for "no intent yet").

    Args:
        payload: JSON string previously produced by
            :func:`serialize_intent`, or ``None``.

    Returns:
        The reconstructed :class:`Intent`, or ``None`` if
        ``payload`` is empty.
    """
    if not payload:
        return None
    return Intent.from_dict(json.loads(payload))


def serialize_scope(scope: Scope | None) -> str | None:
    """Convert a typed :class:`Scope` to a JSON string for SQLite storage.

    Polymorphic: dispatches on the runtime scope type via
    :meth:`Scope.to_dict`. ``None`` is persisted as SQL ``NULL``.

    Args:
        scope: The scope to serialize, or ``None``.

    Returns:
        The JSON string, or ``None`` if ``scope`` is ``None``.
    """
    if scope is None:
        return None
    return json.dumps(scope.to_dict(), sort_keys=True)


def deserialize_scope(
    payload: str | None, cls: type[Scope]
) -> Scope | None:
    """Rehydrate a typed :class:`Scope` from its SQLite JSON column.

    Polymorphic: the caller supplies the concrete scope class
    (:class:`Principal`, :class:`Action`, or :class:`Resource`) so the
    matching :meth:`from_dict` classmethod is used.

    Args:
        payload: JSON string previously produced by
            :func:`serialize_scope`, or ``None``.
        cls: Concrete scope subclass to instantiate.

    Returns:
        The reconstructed :class:`Scope`, or ``None`` if ``payload``
        is empty.
    """
    if not payload:
        return None
    return cls.from_dict(json.loads(payload))


def serialize_payload(payload: Payload) -> str:
    """Convert a typed :class:`Payload` to a JSON string for SQLite storage.

    Args:
        payload: The payload to serialize.

    Returns:
        The JSON string.
    """
    return json.dumps(payload.to_dict(), sort_keys=True)


def deserialize_payload(payload: str) -> Payload:
    """Rehydrate a typed :class:`Payload` from its SQLite JSON column.

    Args:
        payload: JSON string previously produced by
            :func:`serialize_payload`.

    Returns:
        The reconstructed :class:`Payload`.
    """
    return Payload.from_dict(json.loads(payload))


# ---------------------------------------------------------------------------
# Row adapters
# ---------------------------------------------------------------------------


def requirement_from_row(row: dict[str, Any]) -> Need:
    """Build a :class:`Need` from a SQLite requirements row.

    Args:
        row: Dict produced by ``SELECT * FROM requirements``.

    Returns:
        The reconstructed :class:`Need`.
    """
    from pathlib import Path

    return Need(
        id=row["id"],
        text=row["text"],
        domain=row["domain"],
        source_path=Path(row["source_path"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def policy_from_row(row: dict[str, Any]) -> Stored:
    """Build a :class:`Stored` from a SQLite policies row.

    Args:
        row: Dict produced by ``SELECT * FROM policies``.

    Returns:
        The reconstructed :class:`Stored`.
    """
    return Stored(
        id=row["id"],
        domain=row["domain"],
        requirement_id=row["requirement_id"],
        intent=deserialize_intent(row["intent_json"]),
        cedar=row["cedar"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        action=deserialize_scope(row["action_scope_json"], Action),
    )


def draft_from_row(row: dict[str, Any]) -> DraftStored:
    """Build a :class:`DraftStored` from a SQLite drafts row.

    Args:
        row: Dict produced by ``SELECT * FROM drafts``.

    Returns:
        The reconstructed :class:`DraftStored`.
    """
    return DraftStored(
        id=row["id"],
        policy_id=row["policy_id"],
        model=row["model"],
        request_id=row["request_id"],
        unresolved=tuple(json.loads(row["unresolved_json"])),
        cedar=row["cedar"],
        created_at=datetime.fromisoformat(row["created_at"]),
        intent=deserialize_intent(row["intent_json"]) or Intent(
            id=row["id"],
            requirement_id=row["policy_id"] or "",
            effect="permit",
            principal=Principal(),
            action=Action(),
            resource=Resource(),
        ),
        principal=deserialize_scope(row["principal_scope_json"], Principal) or Principal(),
        action=deserialize_scope(row["action_scope_json"], Action) or Action(),
        resource=deserialize_scope(row["resource_scope_json"], Resource) or Resource(),
    )


def report_from_row(row: dict[str, Any]) -> ReportStored:
    """Build a :class:`ReportStored` from a SQLite reports row.

    Args:
        row: Dict produced by ``SELECT * FROM reports``.

    Returns:
        The reconstructed :class:`ReportStored`.
    """
    return ReportStored(
        policy_id=row["policy_id"],
        kind=row["kind"],
        passed=bool(row["passed"]),
        payload=deserialize_payload(row["payload_json"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def deployment_from_row(row: dict[str, Any]) -> Record:
    """Build a :class:`~cedrus.deploy.Record` from a SQLite deployments row.

    Args:
        row: Dict produced by ``SELECT * FROM deployments``.

    Returns:
        The reconstructed :class:`Record`.
    """
    return Record(
        id=row["id"],
        domain=row["domain"],
        target=row["target"],
        target_kind=row["target_kind"],
        bundle_hash=row["bundle_hash"],
        status=row["status"],
        response=dict(json.loads(row["response_json"])),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


# ---------------------------------------------------------------------------
# Sqlite repository
# ---------------------------------------------------------------------------


@dataclass
class Sqlite:
    """SQLite-backed repository.

    Attributes:
        path: Filesystem location of the SQLite database file. The
            parent directory is created on construction.
        allow_legacy: When ``True``, skip the legacy-row refusal
            check in :meth:`__post_init__`. Only the migration CLI
            should set this; every other caller should leave it
            ``False`` so a legacy workspace is rejected loudly.
        connection: Open :class:`sqlite3.Connection` to the database.
    """

    path: Path
    allow_legacy: bool = False
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
        if not self.allow_legacy:
            self.refuse_legacy_rows()

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
            self._stamp_schema_version()

    def _stamp_schema_version(self) -> None:
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

    def refuse_legacy_rows(self) -> None:
        """Refuse to operate on a workspace that still has legacy rows.

        Hard-refuses per the 0.6.0 migration policy: any row whose new
        ``*_json`` columns are ``NULL`` is treated as a hard error
        because the verification and deployment paths rely on those
        columns being populated. The CLI exposes ``cedrus migrate`` to
        upgrade legacy rows in place.

        Detection is inlined against the SQL columns so it stays
        authoritative even after the typed-object dataclass refactor
        (where the typed fields always deserialize via fallbacks).

        Raises:
            Store: When one or more legacy rows remain.
        """
        if self.schema_version() < SCHEMA_VERSION:
            raise Store(
                f"workspace at {self.path} has not been migrated to schema "
                f"version {SCHEMA_VERSION}; run 'cedrus migrate --apply'"
            )
        # Schema is at current version; count rows that still have
        # NULL in any of the 0.6.0 columns.
        legacy_policies = self.connection.execute(
            "SELECT COUNT(*) FROM policies WHERE action_scope_json IS NULL"
        ).fetchone()[0]
        legacy_drafts = self.connection.execute(
            "SELECT COUNT(*) FROM drafts "
            "WHERE intent_json IS NULL "
            "OR principal_scope_json IS NULL "
            "OR action_scope_json IS NULL "
            "OR resource_scope_json IS NULL"
        ).fetchone()[0]
        pending = int(legacy_policies) + int(legacy_drafts)
        if pending:
            raise Store(
                f"workspace at {self.path} contains {pending} legacy rows; "
                "run 'cedrus migrate --apply' to upgrade to the 0.6.0 schema"
            )

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
        return requirement_from_row(dict(row))

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
        return [requirement_from_row(dict(row)) for row in rows]

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
                    serialize_intent(policy.intent),
                    policy.cedar,
                    policy.status,
                    policy.created_at.isoformat(),
                    policy.updated_at.isoformat(),
                    serialize_scope(policy.action),
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
        return policy_from_row(dict(row))

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
        return [policy_from_row(dict(row)) for row in rows]

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
        storage and rehydrated by :func:`draft_from_row` on read.

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
                    serialize_intent(draft.intent),
                    serialize_scope(draft.principal),
                    serialize_scope(draft.action),
                    serialize_scope(draft.resource),
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
        values: list[str | None] = []
        if intent is not None:
            assignments.append("intent_json = ?")
            values.append(serialize_intent(intent))
        if principal is not None:
            assignments.append("principal_scope_json = ?")
            values.append(serialize_scope(principal))
        if action is not None:
            assignments.append("action_scope_json = ?")
            values.append(serialize_scope(action))
        if resource is not None:
            assignments.append("resource_scope_json = ?")
            values.append(serialize_scope(resource))
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
        return draft_from_row(dict(row))

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
        return [draft_from_row(dict(row)) for row in rows]

    def record_report(self, report: ReportStored) -> None:
        """Append ``report`` to the report history.

        The typed :class:`Payload` is serialized to JSON for storage
        and rehydrated by :func:`report_from_row` on read. ``passed``
        is persisted as ``0``/``1`` to match the column type.

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
                    serialize_payload(report.payload),
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
        return report_from_row(dict(row))

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
        return [deployment_from_row(dict(row)) for row in rows]


__all__ = [
    "Sqlite",
    "deployment_from_row",
    "deserialize_intent",
    "deserialize_payload",
    "deserialize_scope",
    "draft_from_row",
    "policy_from_row",
    "report_from_row",
    "requirement_from_row",
    "serialize_intent",
    "serialize_payload",
    "serialize_scope",
]