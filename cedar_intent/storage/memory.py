"""In-memory implementation of the Repository Protocol.

Suitable for tests and ephemeral sessions. State is stored in plain dicts
and lost when the object is garbage collected.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..deployment import DeploymentRecord
from ..errors import StorageError
from ..requirements import Requirement
from .base import StoredDraft, StoredPolicy, StoredReport


@dataclass
class InMemoryRepository:
    """Dictionary-backed repository for tests and short-lived sessions.

    Attributes:
        requirements: Mapping of requirement identifier to requirement.
        policies: Mapping of policy identifier to stored policy.
        drafts: Chronological list of stored drafts.
        reports: Chronological list of stored reports.
        deployments: Chronological list of deployment records.
    """

    requirements: dict[str, Requirement] = field(default_factory=dict)
    policies: dict[str, StoredPolicy] = field(default_factory=dict)
    drafts: list[StoredDraft] = field(default_factory=list)
    reports: list[StoredReport] = field(default_factory=list)
    deployments: list[DeploymentRecord] = field(default_factory=list)

    def add_requirement(self, requirement: Requirement) -> None:
        self.requirements[requirement.id] = requirement

    def get_requirement(self, requirement_id: str) -> Requirement:
        if requirement_id not in self.requirements:
            raise StorageError(f"requirement {requirement_id!r} not found")
        return self.requirements[requirement_id]

    def list_requirements(self, domain: str | None = None) -> Sequence[Requirement]:
        if domain is None:
            return list(self.requirements.values())
        return [
            requirement
            for requirement in self.requirements.values()
            if requirement.domain == domain
        ]

    def remove_requirement(self, requirement_id: str) -> None:
        if requirement_id not in self.requirements:
            raise StorageError(f"requirement {requirement_id!r} not found")
        del self.requirements[requirement_id]

    def upsert_policy(self, policy: StoredPolicy) -> None:
        self.policies[policy.id] = policy

    def get_policy(self, policy_id: str) -> StoredPolicy:
        if policy_id not in self.policies:
            raise StorageError(f"policy {policy_id!r} not found")
        return self.policies[policy_id]

    def list_policies(self, domain: str | None = None) -> Sequence[StoredPolicy]:
        if domain is None:
            return list(self.policies.values())
        return [policy for policy in self.policies.values() if policy.domain == domain]

    def remove_policy(self, policy_id: str) -> None:
        if policy_id not in self.policies:
            raise StorageError(f"policy {policy_id!r} not found")
        del self.policies[policy_id]

    def record_draft(self, draft: StoredDraft) -> None:
        self.drafts.append(draft)

    def latest_draft(self, policy_id: str) -> StoredDraft:
        matching = [draft for draft in self.drafts if draft.policy_id == policy_id]
        if not matching:
            raise StorageError(f"no drafts for policy {policy_id!r}")
        return matching[-1]

    def list_drafts(self, policy_id: str | None = None) -> Sequence[StoredDraft]:
        if policy_id is None:
            return list(self.drafts)
        return [draft for draft in self.drafts if draft.policy_id == policy_id]

    def record_report(self, report: StoredReport) -> None:
        stamped = StoredReport(
            policy_id=report.policy_id,
            kind=report.kind,
            passed=report.passed,
            payload=dict(report.payload),
            created_at=report.created_at or datetime.now(UTC),
        )
        self.reports.append(stamped)

    def latest_report(self, policy_id: str, kind: str) -> StoredReport:
        matching = [
            report
            for report in self.reports
            if report.policy_id == policy_id and report.kind == kind
        ]
        if not matching:
            raise StorageError(f"no {kind} report for policy {policy_id!r}")
        return matching[-1]

    def record_deployment(self, deployment: DeploymentRecord) -> None:
        self.deployments.append(deployment)

    def list_deployments(
        self, domain: str | None = None
    ) -> Sequence[DeploymentRecord]:
        if domain is None:
            return list(self.deployments)
        return [
            record for record in self.deployments if record.domain == domain
        ]


__all__ = ["InMemoryRepository"]
