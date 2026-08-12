"""Persistence-shape dataclasses (the rows stored in the repository).

These types are what hits disk or SQLite. The persistence layer
holds :class:`Stored`, :class:`DraftStored`, :class:`ReportStored`,
and :class:`~cedrus.deploy.Record` rows. They are constructed from
typed in-memory shapes (``Intent``, :class:`~cedrus.policy.Draft`,
etc.) via the ``from_row`` classmethod, which parses the SQLite
column shape.

All classes are ``@dataclass(frozen=True, slots=True)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..compile import Intent


@dataclass(frozen=True, slots=True)
class Stored:
    """Policy row stored in the repository.

    Attributes:
        id: Policy identifier.
        domain: Domain the policy belongs to.
        requirement_id: Optional identifier of the originating requirement.
        intent: Optional parsed :class:`Intent`.
        cedar: Cedar source text for the policy.
        status: Lifecycle status (``"draft"``, ``"existing"``, ``"compiled"``).
        created_at: Timestamp at which the row was first inserted.
        updated_at: Timestamp of the most recent upsert.
        action_scope_json: Optional JSON-serialized :class:`Action`.
    """

    id: str
    domain: str
    requirement_id: str | None
    intent: Intent | None
    cedar: str
    status: str
    created_at: datetime
    updated_at: datetime
    action_scope_json: str | None = None


@dataclass(frozen=True, slots=True)
class DraftStored:
    """Draft proposal row stored in the repository."""

    id: str
    policy_id: str
    model: str
    request_id: str | None
    unresolved: tuple[str, ...]
    cedar: str
    created_at: datetime
    intent_json: str | None = None
    principal_scope_json: str | None = None
    action_scope_json: str | None = None
    resource_scope_json: str | None = None


@dataclass(frozen=True, slots=True)
class ReportStored:
    """Validation or test report row stored in the repository."""

    policy_id: str
    kind: str
    passed: bool
    payload_json: str
    created_at: datetime


__all__ = ["DraftStored", "ReportStored", "Stored"]
