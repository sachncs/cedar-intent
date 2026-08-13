"""Storage backends for cedrus.

This package ships the data shapes (:class:`Repository` Protocol and
the typed-object row dataclasses from :mod:`cedrus.store.base`) plus
the two backend implementations (:class:`Memory` for tests,
:class:`Backend` for the default on-disk behaviour).

All CRUD lives on the typed objects themselves (see
:mod:`cedrus.store.base`); the backends expose only the SQL
primitives the typed objects need.

Attributes:
    Repository: Protocol every storage backend must implement.
    Stored: Policy row stored in the repository.
    DraftStored: Draft proposal row stored in the repository.
    ReportStored: Validation or test report row.
    Memory: Dictionary-backed repository for tests and short-lived
        sessions.
    Backend: SQLite-backed repository implementation.

See Also:
    :mod:`cedrus.store.base`: :class:`Repository` Protocol and the
        shared row dataclasses (with their ``save`` / ``get`` / ``list``
        / ``upsert`` / ``update`` / ``latest`` CRUD methods).
    :mod:`cedrus.store.memory`: :class:`Memory` implementation.
    :mod:`cedrus.store.sqlite`: :class:`Backend` implementation.
"""

from cedrus.store.base import DraftStored, ReportStored, Repository, Stored
from cedrus.store.memory import Memory
from cedrus.store.sqlite import Backend

__all__ = [
    "Backend",
    "DraftStored",
    "Memory",
    "ReportStored",
    "Repository",
    "Stored",
]