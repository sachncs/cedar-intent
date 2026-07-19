"""Storage Protocol and shared data structures for the persistence layer.

The Repository Protocol is the seam between cedar-intent and any backing
store. Two implementations are shipped: :class:`InMemoryRepository` for
tests and ephemeral use, and :class:`SqliteRepository` for the default
on-disk behaviour.

Storage lifecycle
-----------------

Every repository covers the same five tables:

* ``requirements`` - one row per loaded :class:`~cedar_intent.requirements.Requirement`.
* ``policies`` - one row per compiled policy, with the typed intent
  stored as JSON.
* ``drafts`` - the full history of generator proposals per policy.
* ``reports`` - the full history of validation and scenario reports.
* ``deployments`` - the full audit log of bundle deployments.

Drafts and reports reference policies by identifier string, which
allows them to survive policy deletion. The SQLite foreign key
between ``policies.requirement_id`` and ``requirements.id`` cascades
to ``NULL`` on requirement delete, leaving orphan policies that
:func:`list_compiled_policies` skips gracefully.

Thread safety
-------------

Implementations are expected to be safe for concurrent use from a
single process. The in-memory repository is implicitly thread-safe
because it uses plain dicts and lists; the SQLite repository relies
on sqlite3's per-connection serialization, so callers should use a
single repository instance per process or open one per thread.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from ..compiler import PolicyIntent
from ..deployment import DeploymentRecord
from ..requirements import Requirement


@dataclass(frozen=True, slots=True)
class StoredPolicy:
    """Policy row stored in the repository.

    Attributes:
        id: Policy identifier.
        domain: Domain the policy belongs to.
        requirement_id: Optional identifier of the originating requirement.
            ``None`` for orphan policies whose requirement was deleted.
        intent: Optional parsed :class:`PolicyIntent`. ``None`` for
            policies imported from raw Cedar source with no parsed intent.
        cedar: Cedar source text for the policy.
        status: Lifecycle status (``"draft"``, ``"existing"``, ``"compiled"``).
        created_at: Timestamp at which the row was first inserted.
        updated_at: Timestamp of the most recent upsert.
    """

    id: str
    domain: str
    requirement_id: str | None
    intent: PolicyIntent | None
    cedar: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StoredDraft:
    """Draft proposal row stored in the repository.

    Attributes:
        id: Draft identifier (UUID).
        policy_id: Identifier of the policy this draft belongs to.
        model: Model identifier that produced the draft.
        request_id: Provider-supplied request identifier (if any).
        unresolved: Items the generator could not safely resolve.
        cedar: Cedar source text produced by the generator.
        created_at: Timestamp at which the draft was recorded.
    """

    id: str
    policy_id: str
    model: str
    request_id: str | None
    unresolved: tuple[str, ...]
    cedar: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StoredReport:
    """Validation or test report row.

    Attributes:
        policy_id: Identifier of the policy the report applies to.
        kind: Report kind (``"validation"`` or ``"test"``).
        passed: ``True`` when the report indicates success.
        payload: Raw report payload as a dictionary.
        created_at: Timestamp at which the report was recorded.
    """

    policy_id: str
    kind: str
    passed: bool
    payload: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None


@runtime_checkable
class Repository(Protocol):
    """Minimum surface every storage backend must implement.

    The Protocol is runtime-checkable so the workspace and tests can
    verify conformance with ``isinstance``. New backends (for example,
    a Postgres or DynamoDB implementation) can satisfy the Protocol
    without inheriting from any base class.
    """

    def add_requirement(self, requirement: Requirement) -> None: ...
    def get_requirement(self, requirement_id: str) -> Requirement: ...
    def list_requirements(self, domain: str | None = None) -> Sequence[Requirement]: ...
    def remove_requirement(self, requirement_id: str) -> None: ...

    def upsert_policy(self, policy: StoredPolicy) -> None: ...
    def get_policy(self, policy_id: str) -> StoredPolicy: ...
    def list_policies(self, domain: str | None = None) -> Sequence[StoredPolicy]: ...
    def remove_policy(self, policy_id: str) -> None: ...

    def record_draft(self, draft: StoredDraft) -> None: ...
    def latest_draft(self, policy_id: str) -> StoredDraft: ...
    def list_drafts(self, policy_id: str | None = None) -> Sequence[StoredDraft]: ...

    def record_report(self, report: StoredReport) -> None: ...
    def latest_report(self, policy_id: str, kind: str) -> StoredReport: ...

    def record_deployment(self, deployment: DeploymentRecord) -> None: ...
    def list_deployments(
        self, domain: str | None = None
    ) -> Sequence[DeploymentRecord]: ...


__all__ = [
    "Repository",
    "StoredDraft",
    "StoredPolicy",
    "StoredReport",
]
