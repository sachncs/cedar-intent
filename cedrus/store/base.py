"""Storage Protocol and shared data structures for the persistence layer.

The :class:`Repository` Protocol is the seam between cedrus and any
backing store. Two implementations are shipped: :class:`Memory` for
tests and ephemeral use, and :class:`Sqlite` for the default
on-disk behaviour.

Storage lifecycle:
    Every repository covers the same five tables:

    * ``requirements`` - one row per loaded :class:`~cedrus.need.Need`.
    * ``policies`` - one row per compiled policy, with the typed
      :class:`~cedrus.compile.Intent` and the typed
      :class:`~cedrus.scope.Action` scope.
    * ``drafts`` - the full history of generator proposals per policy,
      including the typed intent and the three typed scopes
      (:class:`~cedrus.scope.Principal`,
      :class:`~cedrus.scope.Action`,
      :class:`~cedrus.scope.Resource`).
    * ``reports`` - the full history of validation and scenario reports,
      with a typed :class:`~cedrus.data.Payload`.
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
    typed intent and per-slot scope objects, and :class:`Stored`
    carries the typed action scope. Older databases created before
    this version are upgraded on first open by
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

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Stored:
        """Build a :class:`Stored` from the normalized ``policies`` rows.

        ``data`` carries the main ``"policies"`` row and the optional
        ``"intents"`` data dict (which in turn carries the
        ``principals`` / ``actions`` / ``resources`` / ``when_clauses``
        / ``unless_clauses`` / ``notes`` rows). The intent is hydrated
        via :meth:`Intent.parse`; ``None`` when the policy has no
        intent yet.

        Args:
            data: Assembled dict from the SQLite read path.

        Returns:
            The reconstructed :class:`Stored`.
        """
        row = data["policies"]
        intent_data = data.get("intents")
        intent = Intent.parse(int(intent_data)) if intent_data else None
        return cls(
            id=row["id"],
            domain=row["domain"],
            requirement_id=row["requirement_id"],
            intent=intent,
            cedar=row["cedar"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def to_rows(self) -> dict[str, Any]:
        """Return the multi-row dict for this :class:`Stored`.

        Includes the main ``policies`` row plus the
        :meth:`Intent.to_data` dict (when ``self.intent`` is set).

        Returns:
            A dict with ``"policies"`` row and optional
            ``"intents"`` / typed-object / composition rows.
        """
        rows: dict[str, Any] = {
            "policies": {
                "id": self.id,
                "domain": self.domain,
                "requirement_id": self.requirement_id,
                "cedar": self.cedar,
                "status": self.status,
                "created_at": self.created_at.isoformat(),
                "updated_at": self.updated_at.isoformat(),
            },
        }
        if self.intent is not None:
            intent_data = self.intent.to_data()
            rows.update(intent_data)
        return rows


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

    @classmethod
    def parse(cls, data: dict[str, Any]) -> DraftStored:
        """Build a :class:`DraftStored` from the normalized ``drafts`` rows.

        ``data`` carries the main ``"drafts"`` row plus the
        ``"intents"`` / ``"principals"`` / ``"actions"`` /
        ``"resources"`` / ``"unresolved"`` row lists.

        Args:
            data: Assembled dict from the SQLite read path.

        Returns:
            The reconstructed :class:`DraftStored`.
        """
        row = data["drafts"]
        unresolved = tuple(item["item"] for item in data.get("unresolved", ()))
        return cls(
            id=row["id"],
            policy_id=row["policy_id"],
            model=row["model"],
            request_id=row["request_id"],
            unresolved=unresolved,
            cedar=row["cedar"],
            created_at=datetime.fromisoformat(row["created_at"]),
            intent=Intent.parse(data["intents"]),
            principal=Principal.parse(data["principals"]),
            action=Action.parse(data["actions"]),
            resource=Resource.parse(data["resources"]),
        )

    def to_rows(self) -> dict[str, Any]:
        """Return the multi-row dict for this :class:`DraftStored`.

        Returns:
            A dict with the ``drafts`` main row, the typed-object
            rows (intent + 3 scopes), and the ``draft_unresolved``
            rows.
        """
        intent_data = self.intent.to_data()
        return {
            "drafts": {
                "id": self.id,
                "policy_id": self.policy_id,
                "model": self.model,
                "request_id": self.request_id,
                "cedar": self.cedar,
                "created_at": self.created_at.isoformat(),
            },
            **intent_data,
            "principals": intent_data.get("principals", []),
            "actions": intent_data.get("actions", []),
            "resources": intent_data.get("resources", []),
            "unresolved": [
                {"position": i, "item": item}
                for i, item in enumerate(self.unresolved)
            ],
        }


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

    @classmethod
    def parse(cls, data: dict[str, Any]) -> ReportStored:
        """Build a :class:`ReportStored` from the normalized ``reports`` rows.

        ``data`` carries the main ``"reports"`` row plus the
        ``"payload"`` (report_payload) row list.

        Args:
            data: Assembled dict from the SQLite read path.

        Returns:
            The reconstructed :class:`ReportStored`.
        """
        row = data["reports"]
        return cls(
            policy_id=row["policy_id"],
            kind=row["kind"],
            passed=bool(row["passed"]),
            payload=Payload.parse(data),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def to_rows(self) -> dict[str, Any]:
        """Return the multi-row dict for this :class:`ReportStored`.

        Returns:
            A dict with the ``reports`` main row and the
            ``report_payload`` rows.
        """
        payload_data = self.payload.to_data()
        return {
            "reports": {
                "policy_id": self.policy_id,
                "kind": self.kind,
                "passed": 1 if self.passed else 0,
                "created_at": self.created_at.isoformat(),
            },
            **payload_data,
        }


@runtime_checkable
class Repository(Protocol):
    """Minimum surface every storage backend must implement.

    The Protocol is runtime-checkable so the workspace and tests can
    verify conformance with ``isinstance``. New backends (for example,
    a Postgres or DynamoDB implementation) can satisfy the Protocol
    without inheriting from any base class.

    CRUD lives on the typed objects themselves
    (``Need.save`` / ``Need.get`` / ``Need.list``,
    ``Stored.upsert`` / ``Stored.latest_draft`` / ``Stored.list_drafts``,
    ``DraftStored.save`` / ``DraftStored.update`` / ``DraftStored.latest`` /
    ``DraftStored.list``, ``ReportStored.save`` / ``ReportStored.latest``,
    ``Record.save`` / ``Record.list``); the backend only exposes the
    SQL primitives those calls need.
    """

    def fetch(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Execute ``query`` and return rows as dicts.

        Single general row fetcher. Every typed-object CRUD method
        builds its own SQL (with whatever JOINs it needs) and calls
        ``fetch`` once or as many times as it needs.
        """
        ...

    def transaction(self) -> Any:
        """Return a context manager that runs the body inside one transaction.

        Used by the workspace's :meth:`Workspace.apply` to record
        every typed-object graph (policy + intent + scopes + clauses,
        draft + scope graph, etc.) atomically. For the SQLite backend
        this wraps the connection's transaction context manager; for
        the in-memory backend it is a no-op.

        Returns:
            A context manager.
        """
        ...

    def remove_requirement(self, requirement_id: str) -> None: ...
    def remove_policy(self, policy_id: str) -> None: ...


__all__ = [
    "DraftStored",
    "ReportStored",
    "Repository",
    "Stored",
]