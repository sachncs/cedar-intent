"""Storage Protocol and shared data structures for the persistence layer.

The :class:`Repository` Protocol is the seam between cedrus and any
backing store. Two implementations are shipped: :class:`Memory` for
tests and ephemeral use, and :class:`Sqlite` for the default
on-disk behaviour.

Storage lifecycle:
    Every repository covers the same five tables:

    * ``requirements`` - one row per loaded :class:`~cedrus.need.Need`.
    * ``policies`` - one row per compiled policy, with the typed intent
      and action namespace stored as JSON.
    * ``drafts`` - the full history of generator proposals per policy,
      including the proposal's typed intent and per-slot scope JSON.
    * ``reports`` - the full history of validation and scenario reports.
    * ``deployments`` - the full audit log of bundle deployments.

    Drafts and reports reference policies by identifier string, which
    allows them to survive policy deletion. The SQLite foreign key
    between ``policies.requirement_id`` and ``requirements.id`` cascades
    to ``NULL`` on requirement delete, leaving orphan policies that
    :func:`list_compiled_policies` skips gracefully.

Thread safety:
    Implementations are expected to be safe for concurrent use from a
    single process. The in-memory repository is implicitly thread-safe
    because it uses plain dicts and lists; the SQLite repository relies
    on sqlite3's per-connection serialization, so callers should use a
    single repository instance per process or open one per thread.

Schema migration:
    Starting with cedrus 0.6.0, :class:`DraftStored` carries the
    typed intent and per-slot scope JSON, and :class:`Stored` carries
    the action namespace. Older databases created before this version
    are upgraded on first open by
    :func:`cedrus.migrate.detect_legacy_rows` and
    :func:`cedrus.migrate.migrate_legacy_rows`, exposed via the
    ``cedrus migrate`` CLI subcommand. Until the migration runs,
    :class:`Sqlite` raises :class:`Store` on open so operators cannot
    accidentally work with a half-migrated store.

Attributes:
    Stored: Policy row stored in the repository.
    DraftStored: Draft proposal row stored in the repository.
    ReportStored: Validation or test report row.
    Repository: Minimum surface every storage backend must implement.

See Also:
    :mod:`cedrus.store.memory`: In-memory repository implementation.
    :mod:`cedrus.store.sqlite`: SQLite repository implementation.
    :mod:`cedrus.data.persist`: The newer typed persistence rows.
    :mod:`cedrus.migrate`: Migration helpers for pre-0.6 databases.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from cedrus.compile import Intent
from cedrus.data import Payload
from cedrus.deploy import Record
from cedrus.need import Need
from cedrus.scope import Action, Principal, Resource


@dataclass(frozen=True, slots=True)
class Stored:
    """Policy row stored in the repository.

    Attributes:
        id: Policy identifier.
        domain: Domain the policy belongs to.
        requirement_id: Identifier of the originating requirement, or
            ``None`` for orphan policies whose requirement was deleted.
        intent: Optional parsed :class:`Intent`. ``None`` for policies
            imported from raw Cedar source with no parsed intent.
        cedar: Cedar source text for the policy.
        status: Lifecycle status (``"draft"``, ``"existing"``,
            ``"compiled"``).
        created_at: Timestamp at which the row was first inserted.
        updated_at: Timestamp of the most recent upsert.
        action: :class:`Action` scope captured when the policy was
            compiled, used to keep the action namespace authoritative
            across reloads.
    """

    id: str
    domain: str
    requirement_id: str | None
    intent: Intent | None
    cedar: str
    status: str
    created_at: datetime
    updated_at: datetime
    action: Action | None = None


@dataclass(frozen=True, slots=True)
class DraftStored:
    """Draft proposal row stored in the repository.

    Attributes:
        id: Draft identifier (UUID).
        policy_id: Identifier of the policy this draft belongs to.
        model: Model identifier that produced the draft.
        request_id: Provider-supplied request identifier (if any).
        unresolved: Items the generator could not safely resolve.
        cedar: Cedar source text produced by the generator.
        created_at: Timestamp at which the draft was recorded.
        intent: :class:`Intent` carried by the generator proposal.
        principal: :class:`Principal` scope carried by the proposal.
        action: :class:`Action` scope carried by the proposal.
        resource: :class:`Resource` scope carried by the proposal.
    """

    id: str
    policy_id: str
    model: str
    request_id: str | None
    unresolved: tuple[str, ...]
    cedar: str
    created_at: datetime
    intent: Intent
    principal: Principal
    action: Action
    resource: Resource


@dataclass(frozen=True, slots=True)
class ReportStored:
    """Validation or test report row.

    Attributes:
        policy_id: Identifier of the policy the report applies to.
        kind: Report kind (``"validation"`` or ``"test"``).
        passed: ``True`` when the report indicates success.
        payload: Typed report payload; defaults to an empty
            :class:`Payload` when the report has no findings.
        created_at: Timestamp at which the report was recorded;
            defaults to ``datetime.now(UTC)`` when not provided.
    """

    policy_id: str
    kind: str
    passed: bool
    payload: Payload = field(default_factory=Payload)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class Repository(Protocol):
    """Minimum surface every storage backend must implement.

    The Protocol is runtime-checkable so the workspace and tests can
    verify conformance with ``isinstance``. New backends (for example,
    a Postgres or DynamoDB implementation) can satisfy the Protocol
    without inheriting from any base class.
    """

    def add_requirement(self, requirement: Need) -> None: ...
    def get_requirement(self, requirement_id: str) -> Need: ...
    def list_requirements(self, domain: str | None = None) -> Sequence[Need]: ...
    def remove_requirement(self, requirement_id: str) -> None: ...

    def upsert_policy(self, policy: Stored) -> None: ...
    def get_policy(self, policy_id: str) -> Stored: ...
    def list_policies(self, domain: str | None = None) -> Sequence[Stored]: ...
    def remove_policy(self, policy_id: str) -> None: ...

    def record_draft(self, draft: DraftStored) -> None: ...
    def update_draft_scopes(
        self,
        draft_id: str,
        *,
        intent: Intent | None = None,
        principal: Principal | None = None,
        action: Action | None = None,
        resource: Resource | None = None,
    ) -> None: ...
    def latest_draft(self, policy_id: str) -> DraftStored: ...
    def list_drafts(self, policy_id: str | None = None) -> Sequence[DraftStored]: ...

    def record_report(self, report: ReportStored) -> None: ...
    def latest_report(self, policy_id: str, kind: str) -> ReportStored: ...

    def record_deployment(self, deployment: Record) -> None: ...

    def transaction(self) -> Any:
        """Return a context manager that runs the body inside one transaction.

        Used by the workspace's :meth:`Workspace.apply` to record both
        the validation and the test reports alongside the policy
        upsert in a single atomic write. For the SQLite backend this
        wraps the connection's transaction context manager; for the
        in-memory backend it is a no-op.

        Returns:
            A context manager.
        """
        ...
    def list_deployments(
        self, domain: str | None = None
    ) -> Sequence[Record]: ...


__all__ = [
    "DraftStored",
    "ReportStored",
    "Repository",
    "Stored",
]