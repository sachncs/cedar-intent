"""Static symbolic verification for Cedar policy sets.

The :func:`verify_policies` function performs a static analysis of a
domain's policy set and reports:

* **shadowing** - a ``forbid`` whose scope dominates a ``permit``, making
  the permit unreachable in practice;
* **redundancy** - two policies with equivalent scopes and the same
  effect (one is implied by the other);
* **requirement coverage** - whether every loaded requirement has at
  least one compiled policy;
* **action coverage** - whether every action declared in the schema has
  at least one policy that references it;
* **entity-type coverage** - whether every entity type in the schema is
  referenced by at least one policy.

The checks are conservative approximations based on scope dominance. Full
formal equivalence proofs require cedar-policy-symcc; this module ships
practical checks that run without extra dependencies.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .policies import CompiledPolicy, Policy
from .scopes import ActionScope, PrincipalScope, ResourceScope

VerificationSeverity = str  # "warning" | "info"


@dataclass(frozen=True, slots=True)
class VerificationFinding:
    """A single finding emitted by :func:`verify_policies`.

    Attributes:
        kind: Finding category (for example ``"shadowing"``).
        severity: ``"warning"`` or ``"info"``.
        policy_id: Identifier of the policy the finding concerns.
        message: Human-readable explanation.
        related_policy_id: Optional identifier of a related policy.
    """

    kind: str
    severity: VerificationSeverity
    policy_id: str
    message: str
    related_policy_id: str | None = None

    def to_dict(self) -> Mapping[str, Any]:
        """Return a JSON-friendly representation of the finding."""
        return {
            "kind": self.kind,
            "severity": self.severity,
            "policy_id": self.policy_id,
            "message": self.message,
            "related_policy_id": self.related_policy_id,
        }


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """Aggregate result of :func:`verify_policies`.

    Attributes:
        domain: Domain the report applies to.
        findings: Findings collected during verification.
        requirements_covered: Requirements addressed by at least one policy.
        requirements_uncovered: Requirements with no compiled policy.
        actions_covered: Schema actions referenced by at least one policy.
        actions_uncovered: Schema actions not referenced by any policy.
    """

    domain: str
    findings: tuple[VerificationFinding, ...]
    requirements_covered: tuple[str, ...]
    requirements_uncovered: tuple[str, ...]
    actions_covered: tuple[str, ...]
    actions_uncovered: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Return ``True`` when no warning-level findings exist."""
        return not any(finding.severity == "warning" for finding in self.findings)

    def to_dict(self) -> Mapping[str, Any]:
        """Return a JSON-friendly representation of the report."""
        return {
            "domain": self.domain,
            "passed": self.passed,
            "findings": [finding.to_dict() for finding in self.findings],
            "requirements_covered": list(self.requirements_covered),
            "requirements_uncovered": list(self.requirements_uncovered),
            "actions_covered": list(self.actions_covered),
            "actions_uncovered": list(self.actions_uncovered),
        }


def verify_policies(
    domain: str,
    policies: Sequence[Policy],
    requirement_ids: Sequence[str],
    action_names: Sequence[str],
    entity_type_names: Iterable[str],
) -> VerificationReport:
    """Run static verification on ``policies`` and return a structured report.

    Args:
        domain: Domain name reported in the result.
        policies: Policies to inspect.
        requirement_ids: All known requirement identifiers.
        action_names: All known action identifiers.
        entity_type_names: All known entity type identifiers.

    Returns:
        A :class:`VerificationReport` aggregating findings and coverage.
    """
    compiled = [policy for policy in policies if isinstance(policy, CompiledPolicy)]
    findings: list[VerificationFinding] = []
    findings.extend(detect_shadowing(compiled))
    findings.extend(detect_redundancy(compiled))

    covered_action_names, uncovered_action_names = action_coverage(
        compiled, action_names
    )
    covered_requirements, uncovered_requirements = requirement_coverage(
        compiled, requirement_ids
    )
    entity_type_set = set(entity_type_names)
    findings.extend(
        missing_coverage_finding(
            "uncovered-action",
            domain,
            sorted(uncovered_action_names),
            "No policy references action {actions}.",
        )
    )
    findings.extend(
        missing_coverage_finding(
            "uncovered-requirement",
            domain,
            sorted(uncovered_requirements),
            "No compiled policy addresses requirement {items}.",
        )
    )
    findings.extend(
        missing_coverage_finding(
            "uncovered-entity-type",
            domain,
            sorted(entity_type_set - extract_entity_types(compiled)),
            "No policy references entity type {items}.",
        )
    )
    return VerificationReport(
        domain=domain,
        findings=tuple(findings),
        requirements_covered=tuple(sorted(covered_requirements)),
        requirements_uncovered=tuple(sorted(uncovered_requirements)),
        actions_covered=tuple(sorted(covered_action_names)),
        actions_uncovered=tuple(sorted(uncovered_action_names)),
    )


def detect_shadowing(policies: Sequence[Policy]) -> list[VerificationFinding]:
    """Detect ``forbid`` policies that shadow ``permit`` policies."""
    findings: list[VerificationFinding] = []
    permits = [
        policy for policy in policies if policy.intent_for_verification().effect == "permit"
    ]
    forbids = [
        policy for policy in policies if policy.intent_for_verification().effect == "forbid"
    ]
    for permit in permits:
        permit_intent = permit.intent_for_verification()
        for forbid in forbids:
            forbid_intent = forbid.intent_for_verification()
            if scopes_match_and_subsume(
                forbid_intent.principal, permit_intent.principal
            ) and scopes_match_and_subsume(
                forbid_intent.action, permit_intent.action
            ) and scopes_match_and_subsume(
                forbid_intent.resource, permit_intent.resource
            ):
                findings.append(
                    VerificationFinding(
                        kind="shadowing",
                        severity="warning",
                        policy_id=permit.id,
                        related_policy_id=forbid.id,
                        message=(
                            f"permit {permit.id} is shadowed by forbid {forbid.id}; "
                            "the permit will never produce Allow."
                        ),
                    )
                )
    return findings


def detect_redundancy(policies: Sequence[Policy]) -> list[VerificationFinding]:
    """Detect policies that duplicate the scope and effect of another policy."""
    findings: list[VerificationFinding] = []
    seen: dict[
        tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]], str
    ] = {}
    for policy in policies:
        intent = policy.intent_for_verification()
        key = (
            intent.effect,
            scope_signature(intent.principal),
            scope_signature(intent.action),
            scope_signature(intent.resource),
        )
        existing = seen.get(key)
        if existing is not None:
            findings.append(
                VerificationFinding(
                    kind="redundancy",
                    severity="warning",
                    policy_id=policy.id,
                    related_policy_id=existing,
                    message=(
                        f"policy {policy.id} has the same scope and effect as "
                        f"policy {existing}; one is redundant."
                    ),
                )
            )
        else:
            seen[key] = policy.id
    return findings


def action_coverage(
    policies: Sequence[Policy],
    action_names: Sequence[str],
) -> tuple[set[str], set[str]]:
    """Return ``(covered, uncovered)`` action identifiers."""
    covered: set[str] = set()
    referenced: set[str] = set()
    for policy in policies:
        intent = policy.intent_for_verification()
        if intent.action.kind != "any" and intent.action.name:
            referenced.add(intent.action.name)
        if intent.action.kind != "any" and intent.action.group:
            referenced.add(intent.action.group)
    for name in action_names:
        if name in referenced:
            covered.add(name)
    return covered, set(action_names) - covered


def requirement_coverage(
    policies: Sequence[Policy],
    requirement_ids: Sequence[str],
) -> tuple[set[str], set[str]]:
    """Return ``(covered, uncovered)`` requirement identifiers."""
    covered = {policy.requirement.id for policy in policies}
    return covered & set(requirement_ids), set(requirement_ids) - covered


def extract_entity_types(policies: Sequence[Policy]) -> set[str]:
    """Return the set of entity type names referenced by ``policies``."""
    types: set[str] = set()
    for policy in policies:
        intent = policy.intent_for_verification()
        for scope in (intent.principal, intent.resource):
            for name in scope_entity_type_names(scope):
                if name:
                    types.add(name)
    return types


def scope_entity_type_names(
    scope: PrincipalScope | ActionScope | ResourceScope,
) -> tuple[str | None, ...]:
    """Return the type-name fields from a scope, regardless of its concrete type."""
    if isinstance(scope, PrincipalScope):
        return (scope.type_name, scope.group_type)
    if isinstance(scope, ActionScope):
        return ()
    return (scope.type_name, scope.parent_type)


def missing_coverage_finding(
    kind: str,
    domain: str,
    items: list[str],
    template: str,
) -> list[VerificationFinding]:
    """Emit a single coverage finding when ``items`` is non-empty."""
    if not items:
        return []
    joined = ", ".join(items)
    return [
        VerificationFinding(
            kind=kind,
            severity="warning",
            policy_id=domain,
            message=template.format(items=joined, actions=joined),
        )
    ]


def scopes_match_and_subsume(
    outer: PrincipalScope | ActionScope | ResourceScope,
    inner: PrincipalScope | ActionScope | ResourceScope,
) -> bool:
    """Return True when ``outer`` and ``inner`` are compatible and ``outer`` subsumes ``inner``."""
    if outer.kind == "any":
        return True
    if inner.kind == "any":
        return True
    if type(outer) is not type(inner):
        return False
    return scope_signature(outer) == scope_signature(inner)


def scope_signature(scope: PrincipalScope | ActionScope | ResourceScope) -> tuple[str, ...]:
    """Return a tuple that uniquely identifies the scope."""
    if isinstance(scope, PrincipalScope):
        return (
            scope.kind,
            scope.type_name or "",
            scope.entity_id or "",
            scope.group_type or "",
            scope.group_id or "",
        )
    if isinstance(scope, ActionScope):
        return (scope.kind, scope.name or "", scope.group or "", scope.namespace or "")
    return (
        scope.kind,
        scope.type_name or "",
        scope.entity_id or "",
        scope.parent_type or "",
        scope.parent_id or "",
    )


__all__ = [
    "VerificationFinding",
    "VerificationReport",
    "extract_entity_types",
    "verify_policies",
]
