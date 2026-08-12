"""In-memory implementation of the Repository Protocol.

Built on top of an in-memory SQLite database so the typed-object CRUD
in :mod:`cedrus.store.base` works identically against this backend
and the on-disk :class:`~cedrus.store.sqlite.Backend`.

Thread safety:
    The in-memory repository is safe for concurrent use from multiple
    threads within a single process because SQLite serializes access
    on each connection. Cross-process sharing is not supported; tests
    should construct one instance per test.

Attributes:
    Memory: In-memory repository for tests and short-lived sessions.

See Also:
    :mod:`cedrus.store.base`: :class:`Repository` Protocol this module
        implements, plus the typed-object CRUD methods that drive
        the SQL primitives on the SQLite side.
    :mod:`cedrus.store.sqlite`: On-disk SQLite implementation.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from cedrus.store.sqlite import SCHEMA_STATEMENTS, Backend


class Memory(Backend):
    """In-memory repository for tests and short-lived sessions.

    Wraps an in-memory SQLite database. State is lost when the object
    is garbage collected.
    """

    def __init__(self) -> None:
        # Initialize the path and connection directly, then run the
        # schema migration. We bypass Backend.__post_init__ because
        # the in-memory connection doesn't need PRAGMA tuning.
        self.path = Path(":memory:")
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.connection.execute("PRAGMA foreign_keys = ON")
        with self.transaction():
            for statement in SCHEMA_STATEMENTS:
                self.connection.execute(statement)
            self.stamp_schema_version()


__all__ = ["Memory"]