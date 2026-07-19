"""Storage Protocol and shared data structures for the persistence layer.

The Repository Protocol is the seam between cedar-intent and any backing
store. Two implementations are shipped: :class:`InMemoryRepository` for
tests and ephemeral use, and :class:`SqliteRepository` for the default
on-disk behaviour.
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
        intent: Optional parsed :class:`PolicyIntent`.
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
        id: Draft identifier.
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
    """Minimum surface every storage backend must implement."""

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
