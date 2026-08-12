"""Storage backends for cedrus.

This package ships the data shapes (:class:`Repository` Protocol,
:mod:`~cedrus.data.persist` rows) and the two backend implementations
(:class:`Memory`, :class:`Backend`).

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
        shared row dataclasses.
    :mod:`cedrus.store.memory`: :class:`Memory` implementation.
    :mod:`cedrus.store.sqlite`: :class:`Backend` implementation.
    :mod:`cedrus.data.persist`: Newer typed persistence rows.
"""

from .base import DraftStored, ReportStored, Repository, Stored
from .memory import Memory
from .sqlite import Backend

__all__ = [
    "Backend",
    "DraftStored",
    "Memory",
    "ReportStored",
    "Repository",
    "Stored",
]