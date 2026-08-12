"""Persistence-shape dataclasses (the rows stored in the repository).

These types are what hits disk or SQLite. The persistence layer
holds :class:`Stored`, :class:`DraftStored`, :class:`ReportStored`,
and :class:`~cedrus.deploy.Record` rows. They are constructed from
typed in-memory shapes (``Intent``, :class:`~cedrus.policy.Draft`,
etc.) via the ``from_row`` classmethod, which parses the SQLite
column shape.

All classes are ``@dataclass(frozen=True, slots=True)``.

Attributes:
    Stored: A persisted policy row.
    DraftStored: A persisted draft proposal row.
    ReportStored: A persisted validation or test report row.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import UTC, datetime

from cedrus.compile import Intent
from cedrus.data.wire import Payload
from cedrus.scope import Action, Principal, Resource


@dataclass(frozen=True, slots=True)
class Stored:
    """Policy row stored in the repository.

    Maps to the ``policies`` SQLite table. Carries the typed :class:`Action`
    scope alongside the parsed :class:`Intent` and the raw Cedar source.

    Attributes:
        id: Policy identifier.
        domain: Domain the policy belongs to.
        requirement_id: Identifier of the originating requirement.
        intent: Parsed :class:`Intent`.
        cedar: Cedar source text for the policy.
        status: Lifecycle status (``"draft"``, ``"existing"``, ``"compiled"``).
        updated_at: Timestamp of the most recent upsert.
        action: :class:`Action` scope attached to the policy.
        created_at: Timestamp at which the row was first inserted;
            defaults to ``datetime.now(UTC)`` if not provided.
    """

    id: str
    domain: str
    requirement_id: str
    intent: Intent
    cedar: str
    status: str
    updated_at: datetime
    action: Action
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class DraftStored:
    """Draft proposal row stored in the repository.

    Maps to the ``drafts`` SQLite table. Carries the parsed :class:`Intent`
    and its three scope objects (:class:`Principal`, :class:`Action`,
    :class:`Resource`) alongside the raw Cedar source produced by the model.

    Attributes:
        id: Draft identifier.
        policy_id: Identifier of the policy this draft proposes.
        model: Model that produced the draft.
        request_id: Identifier of the originating generation request.
        unresolved: Tuple of unresolved reference keys.
        cedar: Cedar source text for the draft.
        intent: :class:`Intent` carried by the draft.
        principal: :class:`Principal` scope carried by the draft.
        action: :class:`Action` scope carried by the draft.
        resource: :class:`Resource` scope carried by the draft.
        created_at: Timestamp at which the row was first inserted;
            defaults to ``datetime.now(UTC)`` if not provided.
    """

    id: str
    policy_id: str
    model: str
    request_id: str
    unresolved: tuple[str, ...]
    cedar: str
    intent: Intent
    principal: Principal
    action: Action
    resource: Resource
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class ReportStored:
    """Validation or test report row stored in the repository.

    Maps to the ``reports`` SQLite table. Holds the outcome of a
    validation or test pass and the typed :class:`Payload` with the
    detailed findings.

    Attributes:
        policy_id: Identifier of the policy the report pertains to.
        kind: Report kind (e.g. ``"validation"``, ``"test"``).
        passed: Whether the report's checks passed.
        payload: Typed report payload.
        created_at: Timestamp at which the row was first inserted;
            defaults to ``datetime.now(UTC)`` if not provided.
    """

    policy_id: str
    kind: str
    passed: bool
    payload: Payload
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


__all__ = ["DraftStored", "ReportStored", "Stored"]
