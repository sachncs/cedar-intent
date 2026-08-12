"""In-memory implementation of the Repository Protocol.

Suitable for tests and ephemeral sessions. State is stored in plain
dicts and lists and is lost when the object is garbage collected.

Thread safety:
    The in-memory repository is safe for concurrent use from multiple
    threads within a single process because Python's GIL serializes
    attribute access on dicts and lists. Cross-process sharing is not
    supported; tests should construct one instance per test.

Attributes:
    Memory: Dictionary-backed repository for tests and short-lived
        sessions.

See Also:
    :mod:`cedrus.store.base`: :class:`Repository` Protocol this module
        implements.
    :mod:`cedrus.store.sqlite`: On-disk SQLite implementation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from cedrus.compile import Intent
from cedrus.deploy import Record
from cedrus.error import Store
from cedrus.need import Need
from cedrus.scope import Action, Principal, Resource
from cedrus.store.base import DraftStored, ReportStored, Stored


@dataclass
class Memory:
    """Dictionary-backed repository for tests and short-lived sessions.

    Attributes:
        requirements: Mapping of requirement identifier to requirement.
        policies: Mapping of policy identifier to stored policy.
        drafts: Chronological list of stored drafts.
        reports: Chronological list of stored reports.
        deployments: Chronological list of deployment records.
    """

    requirements: dict[str, Need] = field(default_factory=dict)
    policies: dict[str, Stored] = field(default_factory=dict)
    drafts: list[DraftStored] = field(default_factory=list)
    reports: list[ReportStored] = field(default_factory=list)
    deployments: list[Record] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Legacy detection is a no-op for in-memory repositories; the
        # schema is always current. Kept here for protocol parity with
        # the SQLite backend.
        self._legacy_count: int = 0

    def add_requirement(self, requirement: Need) -> None:
        """Add or replace ``requirement`` in the store.

        Args:
            requirement: Need to store. Identified by ``id``.
        """
        self.requirements[requirement.id] = requirement

    def get_requirement(self, requirement_id: str) -> Need:
        """Return the requirement with ``requirement_id``.

        Args:
            requirement_id: Identifier of the requirement to fetch.

        Returns:
            The stored :class:`Need`.

        Raises:
            Store: If no requirement exists with that id.
        """
        if requirement_id not in self.requirements:
            raise Store(f"requirement {requirement_id!r} not found")
        return self.requirements[requirement_id]

    def list_requirements(self, domain: str | None = None) -> Sequence[Need]:
        """Return all requirements, optionally filtered by ``domain``.

        Args:
            domain: When provided, only requirements whose ``domain``
                attribute matches are returned.

        Returns:
            A sequence of :class:`Need` objects in insertion order.
        """
        if domain is None:
            return list(self.requirements.values())
        return [
            requirement
            for requirement in self.requirements.values()
            if requirement.domain == domain
        ]

    def remove_requirement(self, requirement_id: str) -> None:
        """Remove the requirement with ``requirement_id``.

        Args:
            requirement_id: Identifier of the requirement to remove.

        Raises:
            Store: If no requirement exists with that id.
        """
        if requirement_id not in self.requirements:
            raise Store(f"requirement {requirement_id!r} not found")
        del self.requirements[requirement_id]

    def upsert_policy(self, policy: Stored) -> None:
        """Insert or update ``policy`` in the store.

        Args:
            policy: Policy row to upsert. Identified by ``id``.
        """
        self.policies[policy.id] = policy

    def get_policy(self, policy_id: str) -> Stored:
        """Return the policy with ``policy_id``.

        Args:
            policy_id: Identifier of the policy to fetch.

        Returns:
            The stored :class:`Stored`.

        Raises:
            Store: If no policy exists with that id.
        """
        if policy_id not in self.policies:
            raise Store(f"policy {policy_id!r} not found")
        return self.policies[policy_id]

    def list_policies(self, domain: str | None = None) -> Sequence[Stored]:
        """Return all policies, optionally filtered by ``domain``.

        Args:
            domain: When provided, only policies whose domain matches
                are returned.

        Returns:
            A sequence of :class:`Stored` in insertion order.
        """
        if domain is None:
            return list(self.policies.values())
        return [policy for policy in self.policies.values() if policy.domain == domain]

    def remove_policy(self, policy_id: str) -> None:
        """Remove the policy with ``policy_id``.

        Args:
            policy_id: Identifier of the policy to remove.

        Raises:
            Store: If no policy exists with that id.
        """
        if policy_id not in self.policies:
            raise Store(f"policy {policy_id!r} not found")
        del self.policies[policy_id]

    def record_draft(self, draft: DraftStored) -> None:
        """Append ``draft`` to the draft history.

        Args:
            draft: Draft row to record.
        """
        self.drafts.append(draft)

    def update_draft_scopes(
        self,
        draft_id: str,
        *,
        intent: Intent | None = None,
        principal: Principal | None = None,
        action: Action | None = None,
        resource: Resource | None = None,
    ) -> None:
        """Update one or more typed-scope fields on a stored draft.

        Mirrors the SQLite-side migration helper so the same call
        signature works against both backends. Each typed-object
        keyword is optional; passing ``None`` (the default) leaves
        that field untouched on the matching draft.

        Args:
            draft_id: Identifier of the draft to update.
            intent: Replacement :class:`Intent`, or ``None`` to leave
                the existing value in place.
            principal: Replacement :class:`Principal`, or ``None`` to
                leave the existing value in place.
            action: Replacement :class:`Action`, or ``None`` to leave
                the existing value in place.
            resource: Replacement :class:`Resource`, or ``None`` to
                leave the existing value in place.

        Raises:
            Store: If no draft exists with that id.
        """
        for index, draft in enumerate(self.drafts):
            if draft.id == draft_id:
                self.drafts[index] = DraftStored(
                    id=draft.id,
                    policy_id=draft.policy_id,
                    model=draft.model,
                    request_id=draft.request_id,
                    unresolved=draft.unresolved,
                    cedar=draft.cedar,
                    created_at=draft.created_at,
                    intent=intent if intent is not None else draft.intent,
                    principal=(
                        principal if principal is not None else draft.principal
                    ),
                    action=action if action is not None else draft.action,
                    resource=resource if resource is not None else draft.resource,
                )
                return
        raise Store(f"no draft with id {draft_id!r}")

    def latest_draft(self, policy_id: str) -> DraftStored:
        """Return the most recent draft for ``policy_id``.

        Args:
            policy_id: Identifier of the policy to query.

        Returns:
            The most recent :class:`DraftStored` for ``policy_id``.

        Raises:
            Store: If no drafts exist for ``policy_id``.
        """
        matching = [draft for draft in self.drafts if draft.policy_id == policy_id]
        if not matching:
            raise Store(f"no drafts for policy {policy_id!r}")
        return matching[-1]

    def list_drafts(self, policy_id: str | None = None) -> Sequence[DraftStored]:
        """Return all drafts, optionally filtered by ``policy_id``.

        Args:
            policy_id: When provided, only drafts whose ``policy_id``
                matches are returned.

        Returns:
            A sequence of :class:`DraftStored` in chronological order.
        """
        if policy_id is None:
            return list(self.drafts)
        return [draft for draft in self.drafts if draft.policy_id == policy_id]

    def record_report(self, report: ReportStored) -> None:
        """Append ``report`` to the report history.

        Args:
            report: Report row to record. ``created_at`` is required;
                callers should stamp it explicitly when constructing
                the row.
        """
        self.reports.append(report)

    def latest_report(self, policy_id: str, kind: str) -> ReportStored:
        """Return the most recent report for ``policy_id`` of ``kind``.

        Args:
            policy_id: Identifier of the policy to query.
            kind: Report kind (``"validation"`` or ``"test"``).

        Returns:
            The most recent matching :class:`ReportStored`.

        Raises:
            Store: If no matching report exists.
        """
        matching = [
            report
            for report in self.reports
            if report.policy_id == policy_id and report.kind == kind
        ]
        if not matching:
            raise Store(f"no {kind} report for policy {policy_id!r}")
        return matching[-1]

    def record_deployment(self, deployment: Record) -> None:
        """Append ``deployment`` to the deployment history.

        Args:
            deployment: Deployment record to store.
        """
        self.deployments.append(deployment)

    def transaction(self) -> Any:
        """Return a no-op transaction context.

        The in-memory repository is single-threaded so transactions
        provide no additional isolation; the contract exists so
        callers can write backend-agnostic code.

        Returns:
            A context manager that yields ``None``.
        """
        import contextlib

        @contextlib.contextmanager
        def _cm() -> Any:
            yield None

        return _cm()

    def list_deployments(
        self, domain: str | None = None
    ) -> Sequence[Record]:
        """Return all deployments, optionally filtered by ``domain``.

        Args:
            domain: When provided, only deployments whose ``domain``
                matches are returned.

        Returns:
            A sequence of :class:`Record` in insertion order.
        """
        if domain is None:
            return list(self.deployments)
        return [
            record for record in self.deployments if record.domain == domain
        ]


__all__ = ["Memory"]