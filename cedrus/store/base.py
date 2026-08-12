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
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from cedrus.compile import Intent
from cedrus.data import Payload
from cedrus.deploy import Record
from cedrus.need import Need
from cedrus.scope import Action, Principal, Resource

if TYPE_CHECKING:
    from .sqlite import Backend


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

    def upsert(self, repo: Backend) -> None:
        """Persist this policy (insert or replace by ``id``).

        Writes the main ``policies`` row plus the full intent graph
        (principals / actions / resources / when_clauses /
        unless_clauses / notes) in one transaction.

        Args:
            repo: Storage backend to write through.
        """
        rows = self.to_rows()
        with repo.transaction():
            repo.execute(
                "INSERT OR REPLACE INTO policies "
                "(id, domain, requirement_id, cedar, status, "
                "created_at, updated_at, intent_id) "
                "VALUES (:id, :domain, :requirement_id, :cedar, :status, "
                ":created_at, :updated_at, :intent_id)",
                {**rows["policies"], "intent_id": rows["policies"].get("intent_id")},
            )
            if self.intent is not None:
                write_intent(repo, rows)

    def latest_draft(self, repo: Backend) -> DraftStored | None:
        """Most recent draft for this policy's id, or ``None``.

        Args:
            repo: Storage backend to read from.

        Returns:
            The most recent :class:`DraftStored` for ``self.id``, or
            ``None`` when there are no drafts.
        """
        rows = repo.fetch(
            "SELECT * FROM drafts WHERE policy_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (self.id,),
        )
        if not rows:
            return None
        return DraftStored.parse(fetch_draft_data(repo, rows[0]))

    def list_drafts(self, repo: Backend) -> list[DraftStored]:
        """All drafts for this policy's id, in chronological order.

        Args:
            repo: Storage backend to read from.

        Returns:
            A list of :class:`DraftStored` (empty when no drafts exist).
        """
        rows = repo.fetch(
            "SELECT * FROM drafts WHERE policy_id = ? ORDER BY created_at",
            (self.id,),
        )
        return [
            DraftStored.parse(fetch_draft_data(repo, row)) for row in rows
        ]

    @classmethod
    def list(
        cls,
        repo: Backend,
        *,
        domain: str | None = None,
    ) -> list[Stored]:
        """All policies, optionally filtered by ``domain``.

        Args:
            repo: Storage backend to read from.
            domain: When provided, only policies whose ``domain``
                matches are returned.

        Returns:
            A list of :class:`Stored` in id order.
        """
        if domain is None:
            rows = repo.fetch("SELECT * FROM policies ORDER BY id")
        else:
            rows = repo.fetch(
                "SELECT * FROM policies WHERE domain = ? ORDER BY id",
                (domain,),
            )
        result: list[Stored] = []
        for row in rows:
            intent_data = (
                load_intent_data(repo, row["intent_id"])
                if row.get("intent_id")
                else None
            )
            data: dict[str, Any] = {"policies": row}
            if intent_data is not None:
                data.update(intent_data)
            result.append(cls.parse(data))
        return result

    @classmethod
    def get(cls, repo: Backend, policy_id: str) -> Stored:
        """Load the policy with ``policy_id``.

        Args:
            repo: Storage backend to read from.
            policy_id: Identifier of the policy to fetch.

        Returns:
            The stored :class:`Stored`.

        Raises:
            Store: If no policy exists with that id.
        """
        rows = repo.fetch(
            "SELECT * FROM policies WHERE id = ?", (policy_id,),
        )
        if not rows:
            raise Store(f"policy {policy_id!r} not found")
        row = rows[0]
        intent_data = (
            load_intent_data(repo, row["intent_id"])
            if row.get("intent_id")
            else None
        )
        data: dict[str, Any] = {"policies": row}
        if intent_data is not None:
            data.update(intent_data)
        return cls.parse(data)


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

    def save(self, repo: Backend) -> None:
        """Persist this draft (insert by id, full intent graph).

        Writes the main ``drafts`` row plus the intent + 3 scopes +
        unresolved items in one transaction. Uses :func:`write_intent`
        so the schema shape matches ``Stored.upsert`` exactly.

        Args:
            repo: Storage backend to write through.
        """
        rows = self.to_rows()
        with repo.transaction():
            repo.execute(
                "INSERT OR REPLACE INTO drafts "
                "(id, policy_id, model, request_id, cedar, created_at, "
                "intent_id, principal_id, action_id, resource_id) "
                "VALUES (:id, :policy_id, :model, :request_id, :cedar, "
                ":created_at, :intent_id, :principal_id, :action_id, "
                ":resource_id)",
                rows["drafts"],
            )
            write_intent(repo, rows)
            repo.execute(
                "DELETE FROM draft_unresolved WHERE draft_id = :id",
                {"id": self.id},
            )
            for u in rows.get("unresolved", ()):
                repo.execute(
                    "INSERT INTO draft_unresolved (draft_id, position, item) "
                    "VALUES (:draft_id, :position, :item)",
                    {**u, "draft_id": self.id},
                )

    def update(
        self,
        repo: Backend,
        *,
        intent: Intent | None = None,
        principal: Principal | None = None,
        action: Action | None = None,
        resource: Resource | None = None,
    ) -> None:
        """Update one or more typed-scope fields on this stored draft.

        Each typed-object keyword is optional; passing ``None`` (the
        default) leaves the corresponding FK column (and the typed
        sub-table row) untouched.

        Args:
            repo: Storage backend to write through.
            intent: Replacement :class:`Intent`, or ``None`` to leave
                the existing value in place.
            principal: Replacement :class:`Principal`, or ``None`` to
                leave the existing value in place.
            action: Replacement :class:`Action`, or ``None`` to leave
                the existing value in place.
            resource: Replacement :class:`Resource`, or ``None`` to
                leave the existing value in place.
        """
        assignments: list[str] = []
        if intent is not None:
            assignments.append("intent_id = :intent_id")
        if principal is not None:
            assignments.append("principal_id = :principal_id")
        if action is not None:
            assignments.append("action_id = :action_id")
        if resource is not None:
            assignments.append("resource_id = :resource_id")
        if not assignments:
            return
        params: dict[str, Any] = {"id": self.id}
        if intent is not None:
            rows = self.to_rows()
            with repo.transaction():
                write_intent(repo, rows)
            params["intent_id"] = intent.id
        if principal is not None:
            params["principal_id"] = principal.id
        if action is not None:
            params["action_id"] = action.id
        if resource is not None:
            params["resource_id"] = resource.id
        with repo.transaction():
            repo.execute(
                f"UPDATE drafts SET {', '.join(assignments)} WHERE id = :id",
                params,
            )

    @classmethod
    def latest(cls, repo: Backend, policy_id: str) -> DraftStored:
        """Most recent draft for ``policy_id``.

        Args:
            repo: Storage backend to read from.
            policy_id: Identifier of the policy to query.

        Returns:
            The most recent :class:`DraftStored` for ``policy_id``.

        Raises:
            Store: If no drafts exist for ``policy_id``.
        """
        rows = repo.fetch(
            "SELECT * FROM drafts WHERE policy_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (policy_id,),
        )
        if not rows:
            raise Store(f"no drafts for policy {policy_id!r}")
        return cls.parse(fetch_draft_data(repo, rows[0]))

    @classmethod
    def list(
        cls,
        repo: Backend,
        *,
        policy_id: str | None = None,
    ) -> list[DraftStored]:
        """All drafts, optionally filtered by ``policy_id``.

        Args:
            repo: Storage backend to read from.
            policy_id: When provided, only drafts whose ``policy_id``
                matches are returned.

        Returns:
            A list of :class:`DraftStored` in chronological order.
        """
        if policy_id is None:
            rows = repo.fetch("SELECT * FROM drafts ORDER BY created_at")
        else:
            rows = repo.fetch(
                "SELECT * FROM drafts WHERE policy_id = ? ORDER BY created_at",
                (policy_id,),
            )
        return [cls.parse(fetch_draft_data(repo, row)) for row in rows]


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

    def save(self, repo: Backend) -> None:
        """Persist this report (insert + payload rows).

        Args:
            repo: Storage backend to write through.
        """
        rows = self.to_rows()
        with repo.transaction():
            repo.execute(
                "INSERT INTO reports (policy_id, kind, passed, created_at) "
                "VALUES (:policy_id, :kind, :passed, :created_at)",
                rows["reports"],
            )
            last_id_row = repo.fetch("SELECT last_insert_rowid() AS id")
            report_id = last_id_row[0]["id"]
            repo.execute(
                "DELETE FROM report_payload WHERE report_id = :id",
                {"id": report_id},
            )
            for payload_row in rows.get("report_payload", ()):
                repo.execute(
                    "INSERT INTO report_payload (report_id, position, key, value) "
                    "VALUES (:report_id, :position, :key, :value)",
                    {**payload_row, "report_id": report_id},
                )

    @classmethod
    def latest(cls, repo: Backend, policy_id: str, kind: str) -> ReportStored:
        """Most recent report for ``(policy_id, kind)``.

        Args:
            repo: Storage backend to read from.
            policy_id: Identifier of the policy to query.
            kind: Report kind (``"validation"`` or ``"test"``).

        Returns:
            The most recent matching :class:`ReportStored`.

        Raises:
            Store: If no matching report exists.
        """
        rows = repo.fetch(
            "SELECT * FROM reports WHERE policy_id = ? AND kind = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (policy_id, kind),
        )
        if not rows:
            raise Store(f"no {kind} report for policy {policy_id!r}")
        report = cls.parse({"reports": rows[0]})
        payload_rows = repo.fetch(
            "SELECT key, value FROM report_payload WHERE report_id = ? "
            "ORDER BY position",
            (rows[0]["id"],),
        )
        return cls(
            policy_id=report.policy_id,
            kind=report.kind,
            passed=report.passed,
            payload=Payload(data=tuple((r["key"], r["value"]) for r in payload_rows)),
            created_at=report.created_at,
        )


def write_intent(repo: Backend, rows: dict[str, Any]) -> None:
    """Persist the typed intent graph from a multi-row dict.

    Public module-level function shared by ``Stored.upsert`` and
    ``DraftStored.save`` so the clauses / notes / scope rows are
    written identically from both callers. Must be called inside a
    ``repo.transaction()`` block.

    Args:
        repo: Storage backend to write through.
        rows: Multi-row dict from :meth:`Intent.to_data`. Must contain
            ``"intents"`` and the typed-object row lists.
    """
    for principal in rows.get("principals", ()):
        repo.execute(
            "INSERT OR REPLACE INTO principals "
            "(id, kind, type_name, entity_id, group_type, group_id) "
            "VALUES (:id, :kind, :type_name, :entity_id, :group_type, :group_id)",
            principal,
        )
    for action in rows.get("actions", ()):
        repo.execute(
            "INSERT OR REPLACE INTO actions "
            "(id, kind, name, group) "
            "VALUES (:id, :kind, :name, :group)",
            action,
        )
    for resource in rows.get("resources", ()):
        repo.execute(
            "INSERT OR REPLACE INTO resources "
            "(id, kind, type_name, entity_id, parent_type, parent_id) "
            "VALUES (:id, :kind, :type_name, :entity_id, :parent_type, :parent_id)",
            resource,
        )
    for clause_data in rows.get("when_clause_rows", ()):
        repo.execute(
            "INSERT OR REPLACE INTO clauses (id, body) "
            "VALUES (:id, :body)",
            clause_data["clauses"],
        )
        repo.execute(
            "DELETE FROM clause_attributes WHERE clause_id = :id",
            {"id": clause_data["clauses"]["id"]},
        )
        for attr in clause_data["clause_attributes"]:
            repo.execute(
                "INSERT INTO clause_attributes (clause_id, key, value) "
                "VALUES (:clause_id, :key, :value)",
                attr,
            )
    for clause_data in rows.get("unless_clause_rows", ()):
        repo.execute(
            "INSERT OR REPLACE INTO clauses (id, body) "
            "VALUES (:id, :body)",
            clause_data["clauses"],
        )
        repo.execute(
            "DELETE FROM clause_attributes WHERE clause_id = :id",
            {"id": clause_data["clauses"]["id"]},
        )
        for attr in clause_data["clause_attributes"]:
            repo.execute(
                "INSERT INTO clause_attributes (clause_id, key, value) "
                "VALUES (:clause_id, :key, :value)",
                attr,
            )
    repo.execute(
        "INSERT OR REPLACE INTO intents "
        "(id, effect, requirement_id, principal_id, action_id, resource_id) "
        "VALUES (:id, :effect, :requirement_id, :principal_id, :action_id, :resource_id)",
        rows["intents"],
    )
    intent_id = rows["intents"]["id"]
    repo.execute(
        "DELETE FROM intent_when_clauses WHERE intent_id = :id",
        {"id": intent_id},
    )
    repo.execute(
        "DELETE FROM intent_unless_clauses WHERE intent_id = :id",
        {"id": intent_id},
    )
    repo.execute(
        "DELETE FROM intent_notes WHERE intent_id = :id",
        {"id": intent_id},
    )
    for w in rows.get("intent_when_clauses", ()):
        repo.execute(
            "INSERT INTO intent_when_clauses (intent_id, position, clause_id) "
            "VALUES (:intent_id, :position, :clause_id)",
            w,
        )
    for u in rows.get("intent_unless_clauses", ()):
        repo.execute(
            "INSERT INTO intent_unless_clauses (intent_id, position, clause_id) "
            "VALUES (:intent_id, :position, :clause_id)",
            u,
        )
    for n in rows.get("intent_notes", ()):
        repo.execute(
            "INSERT INTO intent_notes (intent_id, key, value) "
            "VALUES (:intent_id, :key, :value)",
            n,
        )


def load_intent_data(repo: Backend, intent_id: str) -> dict[str, Any]:
    """Load the typed intent graph for ``intent_id``.

    Public module-level function used by
    :func:`fetch_draft_data` and other typed-object reads that need
    to rehydrate a complete intent from its FK.

    Args:
        repo: Storage backend to read from.
        intent_id: Identifier of the intent row to load.

    Returns:
        A dict with the ``"intents"`` main row plus the
        ``principals`` / ``actions`` / ``resources`` /
        ``when_clauses`` / ``unless_clauses`` / ``notes`` row lists,
        ready to feed into :meth:`Intent._parse_sql_shape`.
    """
    intent_row = repo.fetch(
        "SELECT * FROM intents WHERE id = ?", (intent_id,),
    )[0]
    principal_row = repo.fetch(
        "SELECT * FROM principals WHERE id = ?", (intent_row["principal_id"],),
    )[0]
    action_row = repo.fetch(
        "SELECT * FROM actions WHERE id = ?", (intent_row["action_id"],),
    )[0]
    resource_row = repo.fetch(
        "SELECT * FROM resources WHERE id = ?", (intent_row["resource_id"],),
    )[0]
    when_rows = repo.fetch(
        "SELECT c.*, iwc.position AS _position FROM clauses c "
        "JOIN intent_when_clauses iwc ON iwc.clause_id = c.id "
        "WHERE iwc.intent_id = ? ORDER BY iwc.position",
        (intent_id,),
    )
    unless_rows = repo.fetch(
        "SELECT c.*, iuc.position AS _position FROM clauses c "
        "JOIN intent_unless_clauses iuc ON iuc.clause_id = c.id "
        "WHERE iuc.intent_id = ? ORDER BY iuc.position",
        (intent_id,),
    )
    note_rows = repo.fetch(
        "SELECT key, value FROM intent_notes WHERE intent_id = ?",
        (intent_id,),
    )
    return {
        "intents": intent_row,
        "principals": principal_row,
        "actions": action_row,
        "resources": resource_row,
        "when_clauses": [
            {"clauses": {k: v for k, v in r.items() if k != "_position"},
             "clause_attributes": []}
            for r in when_rows
        ],
        "unless_clauses": [
            {"clauses": {k: v for k, v in r.items() if k != "_position"},
             "clause_attributes": []}
            for r in unless_rows
        ],
        "notes": note_rows,
    }


def fetch_draft_data(repo: Backend, row: dict[str, Any]) -> dict[str, Any]:
    """Assemble the multi-row dict for one ``drafts`` row.

    Public module-level function used by
    :meth:`Stored.latest_draft` / :meth:`Stored.list_drafts` /
    :meth:`DraftStored.latest` / :meth:`DraftStored.list` to share
    the typed-object JOIN + fetch logic.

    Args:
        repo: Storage backend to read from.
        row: Main ``drafts`` row dict.

    Returns:
        Dict with ``"drafts"`` + the typed-object / composition
        row lists, ready to feed into :meth:`DraftStored.parse`.
    """
    draft_id = row["id"]
    intent_data = (
        load_intent_data(repo, row["intent_id"])
        if row.get("intent_id")
        else None
    )
    principal = (
        Principal.parse(repo.fetch(
            "SELECT * FROM principals WHERE id = ?", (row["principal_id"],),
        )[0]) if row.get("principal_id") else Principal()
    )
    action = (
        Action.parse(repo.fetch(
            "SELECT * FROM actions WHERE id = ?", (row["action_id"],),
        )[0]) if row.get("action_id") else Action()
    )
    resource = (
        Resource.parse(repo.fetch(
            "SELECT * FROM resources WHERE id = ?", (row["resource_id"],),
        )[0]) if row.get("resource_id") else Resource()
    )
    unresolved_rows = repo.fetch(
        "SELECT item FROM draft_unresolved WHERE draft_id = ? ORDER BY position",
        (draft_id,),
    )
    unresolved = tuple(r["item"] for r in unresolved_rows)
    return {
        "drafts": row,
        "intents": intent_data["intents"] if intent_data else None,
        "principals": principal.to_data(),
        "actions": action.to_data(),
        "resources": resource.to_data(),
        "unresolved": [{"position": i, "item": item}
                       for i, item in enumerate(unresolved)],
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

    def execute(self, query: str, params: dict[str, Any] | tuple = ()) -> None:
        """Execute a write statement (``INSERT`` / ``UPDATE`` / ``DELETE``).

        Used by typed-object ``save`` / ``update`` methods inside a
        ``transaction()`` block. Use named (``:key``) placeholders with
        a dict, or positional (``?``) placeholders with a tuple.
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