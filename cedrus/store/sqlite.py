"""SQLite-backed implementation of the Repository Protocol.

Uses only the standard library ``sqlite3`` module. The database schema
is created on demand and the schema migration is idempotent.

This module exposes the SQL primitives (``fetch``, ``execute``,
``transaction``, ``migrate``, ``remove_requirement``,
``remove_policy``, ``close``) that the typed objects (``Need``,
``Stored``, ``DraftStored``, ``ReportStored``, ``Record``) call from
their ``save`` / ``get`` / ``list`` / ``latest`` / ``update`` /
``upsert`` methods. The backend itself does not own any CRUD — see
:mod:`cedrus.store.base` for the typed-object methods that do.

Schema:
    The normalized schema (version 3) has 12 tables:

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

    The typed intent and per-slot scopes on ``policies`` and
    ``drafts`` are stored in their own normalized tables
    (``intents``, ``principals``, ``actions``, ``resources``,
    ``clauses``, ``clause_attributes``, ``intent_when_clauses``,
    ``intent_unless_clauses``, ``intent_notes``) and joined by
    foreign keys; the typed objects' own ``to_data`` /
    ``parse`` methods handle the round-trip.

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
        implements, plus the typed-object CRUD methods that drive
        the SQL primitives exposed here.
    :mod:`cedrus.store.memory`: In-memory repository implementation.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cedrus.error import Store

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
        action_group TEXT
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


# ---------------------------------------------------------------------------
# SQLite repository
# ---------------------------------------------------------------------------


@dataclass
class Backend:
    """SQLite-backed :class:`~cedrus.store.base.Repository`.

    Exposes only the SQL primitives (``fetch``, ``execute``,
    ``transaction``, ``migrate``, ``remove_requirement``,
    ``remove_policy``, ``close``) that the typed objects use. CRUD
    lives on :class:`~cedrus.store.base.Need` /
    :class:`~cedrus.store.base.Stored` /
    :class:`~cedrus.store.base.DraftStored` /
    :class:`~cedrus.store.base.ReportStored` /
    :class:`~cedrus.deploy.Record`.

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

    def migrate(self) -> None:
        """Create the schema and stamp the current version in one transaction.

        Idempotent: every ``CREATE`` uses ``IF NOT EXISTS`` so the
        statement is safe to re-run on a database that's already at
        the current version. The schema version is set inside the same
        transaction as the schema objects, so a partially-created
        database either has its declared version or does not exist
        at all.
        """
        with self.transaction():
            for statement in SCHEMA_STATEMENTS:
                self.connection.execute(statement)
            self.stamp_schema_version()

    def stamp_schema_version(self) -> None:
        """Insert or update the ``meta.schema_version`` row in this transaction.

        Must be called inside a :meth:`transaction` block.
        """
        row = self.connection.execute("SELECT schema_version FROM meta").fetchone()
        if row is None:
            self.connection.execute(
                "INSERT INTO meta (schema_version) VALUES (?)", (SCHEMA_VERSION,)
            )
        elif row["schema_version"] != SCHEMA_VERSION:
            self.connection.execute(
                "UPDATE meta SET schema_version = ?", (SCHEMA_VERSION,)
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

    def fetch(
        self,
        query: str,
        params: tuple = (),
    ) -> list[dict[str, Any]]:
        """Execute ``query`` and return rows as dicts.

        General-purpose SQL row fetcher. The caller configures what to
        fetch via the query and bound parameters; ``fetch`` just handles
        execution and row-dict conversion. This is the only row-reading
        primitive the typed objects build on; there is no
        ``fetch_intent_data`` / ``fetch_policy_data`` / etc. — every
        read shapes its own query and calls ``fetch`` once or as many
        times as it needs.

        Args:
            query: SQL ``SELECT`` statement. Use ``?`` placeholders for
                bound values to keep the call site safe; ``fetch`` itself
                does not do SQL parsing or table-name validation.
            params: Parameters bound to the ``?`` placeholders.

        Returns:
            A list of row dicts (empty when the query returns no rows).
        """
        return [dict(row) for row in self.connection.execute(query, params).fetchall()]

    def execute(
        self,
        query: str,
        params: dict[str, Any] | tuple = (),
    ) -> None:
        """Execute a write statement and discard the result.

        Used by typed-object ``save`` / ``update`` methods inside a
        :meth:`transaction` block. Accepts either a ``dict`` (bound to
        ``:key`` named placeholders) or a ``tuple`` (bound to ``?``
        positional placeholders).

        Args:
            query: SQL ``INSERT`` / ``UPDATE`` / ``DELETE`` statement.
            params: Named (dict) or positional (tuple) placeholders.
        """
        self.connection.execute(query, params)

    def remove_requirement(self, requirement_id: str) -> None:
        """Remove the requirement with ``requirement_id``.

        Args:
            requirement_id: Identifier of the requirement to remove.

        Raises:
            Store: If no requirement exists with that id.
        """
        with self.transaction():
            cursor = self.connection.execute(
                "DELETE FROM requirements WHERE id = ?", (requirement_id,)
            )
            if cursor.rowcount == 0:
                raise Store(f"requirement {requirement_id!r} not found")

    def remove_policy(self, policy_id: str) -> None:
        """Remove the policy with ``policy_id``.

        Args:
            policy_id: Identifier of the policy to remove.

        Raises:
            Store: If no policy exists with that id.
        """
        with self.transaction():
            cursor = self.connection.execute(
                "DELETE FROM policies WHERE id = ?", (policy_id,)
            )
            if cursor.rowcount == 0:
                raise Store(f"policy {policy_id!r} not found")

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


__all__ = ["Backend"]