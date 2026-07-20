"""Static symbolic verification for Cedar policy sets.

The :func:`verify_policies` function performs a static analysis of a
domain's policy set and reports:

* **shadowing** - a ``forbid`` whose scope dominates a ``permit``,
  making the permit unreachable in practice;
* **redundancy** - two policies with equivalent scopes, the same
  effect, and the same conditions (one is implied by the other);
* **requirement coverage** - whether every loaded requirement has at
  least one compiled policy;
* **action coverage** - whether every action declared in the schema has
  at least one policy that references it, with action-group
  membership expanded;
* **entity-type coverage** - whether every entity type in the schema
  is referenced by at least one policy.

The verifier analyzes the deployed Cedar source directly rather than
the typed intent metadata, so coverage and shadowing reflect what
will actually run.

Algorithm notes
----------------

Scope dominance is approximated by comparing the *signature* of a
scope: a tuple of (kind, type_name, entity_id, group_type, group_id)
for principals, an analogous tuple for resources, and a tuple that
includes the namespace and ``"named"``/``"in_group"`` flag for
actions. Two policies are considered to share a shadow or a
redundancy only when their scope signatures match across every slot
AND their condition signatures match.

``any`` does not subsume a non-``any`` scope: a forbid on Alice does
not shadow a permit on ``any`` principal.

Action coverage expands action-group membership: ``action in
Action::"readers"`` counts as covering every member action of the
``readers`` group. This keeps coverage faithful to Cedar's
authorization semantics.

Complexity is O(n^2) for shadowing/redundancy across n policies and
O(n*m) for coverage across n policies and m schema entries. That is
acceptable for typical domain sizes (dozens to low hundreds of
policies). A full SMT-backed equivalence check via cedar-policy-symcc
would replace these approximations when needed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

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
    actions_covered: tuple[tuple[str, str], ...]
    actions_uncovered: tuple[tuple[str, str], ...]

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
            "actions_covered": [list(pair) for pair in self.actions_covered],
            "actions_uncovered": [list(pair) for pair in self.actions_uncovered],
        }


@dataclass(frozen=True, slots=True)
class CedarScopeExtraction:
    """Scope and condition data extracted from a Cedar policy's source.

    The verifier analyzes the deployed Cedar rather than the typed
    intent metadata so that imported policies (whose intent is
    ``None``) participate in coverage and shadowing checks.

    Attributes:
        principal: Tuple identifying the principal slot.
        action: Tuple identifying the action slot (including namespace).
        resource: Tuple identifying the resource slot.
        conditions: Sorted list of (kind, body) pairs for ``when`` and
            ``unless`` clauses.
        effect: ``"permit"`` or ``"forbid"``.
        cedar: Original Cedar source text.
    """

    principal: tuple[str, ...]
    action: tuple[str, ...]
    resource: tuple[str, ...]
    conditions: tuple[tuple[str, str], ...]
    effect: str
    cedar: str

    @property
    def signature(
        self,
    ) -> tuple[
        str,
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
        tuple[tuple[str, str], ...],
    ]:
        """Return the full signature used for shadow and redundancy keys."""
        return (
            self.effect,
            self.principal,
            self.action,
            self.resource,
            self.conditions,
        )


def verify_policies(
    domain: str,
    policies: Sequence[Any],
    requirement_ids: Sequence[str],
    action_names: Sequence[tuple[str, str]],
    entity_type_names: Iterable[str],
    actions_by_namespace: Mapping[str, Mapping[str, tuple[str, ...]]] | None = None,
) -> VerificationReport:
    """Run static verification on ``policies`` and return a structured report.

    Args:
        domain: Domain name reported in the result.
        policies: Policies to inspect. The Cedar source of each policy is
            parsed to extract scope and condition data.
        requirement_ids: All known requirement identifiers.
        action_names: All known ``(namespace, action_id)`` pairs.
        entity_type_names: All known entity type identifiers.
        actions_by_namespace: Optional mapping ``{namespace: {action_id:
            (member_action_ids)}}`` for action-group expansion.

    Returns:
        A :class:`VerificationReport` aggregating findings and
        coverage metrics.
    """
    extracted = [(policy, extract_scope(policy)) for policy in policies]
    return _verify_extracted(
        domain,
        extracted,
        requirement_ids,
        action_names,
        entity_type_names,
        actions_by_namespace or {},
    )


def _verify_extracted(
    domain: str,
    extracted: Sequence[tuple[Any, CedarScopeExtraction]],
    requirement_ids: Sequence[str],
    action_names: Sequence[tuple[str, str]],
    entity_type_names: Iterable[str],
    actions_by_namespace: Mapping[str, Mapping[str, tuple[str, ...]]],
) -> VerificationReport:
    findings: list[VerificationFinding] = []
    findings.extend(detect_shadowing(extracted))
    findings.extend(detect_redundancy(extracted))

    covered_action_names, uncovered_action_names = action_coverage(
        extracted, action_names, actions_by_namespace
    )
    covered_requirements, uncovered_requirements = requirement_coverage(
        extracted, requirement_ids
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
            sorted(entity_type_set - collect_entity_types(extracted)),
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


def extract_scope(policy: Any) -> CedarScopeExtraction:
    """Extract scope and condition data from ``policy``.

    Cedar source is parsed with a lenient regex parser that captures
    the effect, principal/action/resource types, and condition
    bodies. The verifier operates on regex-derived signatures so it
    can analyze imported policies whose intent is ``None`` as well as
    CLI-generated policies whose Cedar source is the authoritative
    artifact.

    Args:
        policy: Policy (or any object with a ``.cedar`` attribute or
            a ``notes`` mapping carrying ``cedar_text``).

    Returns:
        A :class:`CedarScopeExtraction` capturing principal, action,
        resource, conditions, and effect.
    """
    cedar = _policy_cedar(policy)
    return _parse_with_regex(cedar)


def _policy_id(policy: Any) -> str:
    """Return the policy id, accepting Policy or PolicyIntent."""
    return getattr(policy, "id", None) or getattr(policy, "intent_id", None) or ""


def _policy_requirement_id(policy: Any) -> str:
    """Return the requirement id associated with a policy-like object."""
    requirement = getattr(policy, "requirement", None)
    if requirement is not None:
        return getattr(requirement, "id", "")
    return getattr(policy, "requirement_id", "")


def _policy_cedar(policy: Any) -> str:
    """Return the Cedar source text associated with a policy-like object."""
    cedar = getattr(policy, "cedar", None)
    if cedar:
        return str(cedar)
    notes = getattr(policy, "notes", None)
    if isinstance(notes, Mapping):
        return str(notes.get("cedar_text", ""))
    return ""


def detect_shadowing(
    policies: Sequence[tuple[Any, CedarScopeExtraction]],
) -> list[VerificationFinding]:
    """Detect ``forbid`` policies that shadow ``permit`` policies.

    A forbid shadows a permit when the forbid's scope equals the
    permit's scope across every slot AND the forbid's conditions equal
    the permit's conditions. ``any`` does not subsume a non-``any``
    scope, so a forbid on Alice does not shadow a permit on ``any``
    principal.

    Args:
        policies: Pairs of (Policy-like object, CedarScopeExtraction)
            to analyze.

    Returns:
        A list of shadowing findings. Empty if no shadowing is found.
    """
    findings: list[VerificationFinding] = []
    permits = [
        (policy, extraction)
        for policy, extraction in policies
        if extraction.effect == "permit"
    ]
    forbids = [
        (policy, extraction)
        for policy, extraction in policies
        if extraction.effect == "forbid"
    ]
    for permit, permit_ex in permits:
        for forbid, forbid_ex in forbids:
            if scopes_match(permit_ex, forbid_ex):
                findings.append(
                    VerificationFinding(
                        kind="shadowing",
                        severity="warning",
                        policy_id=_policy_id(permit),
                        related_policy_id=_policy_id(forbid),
                        message=(
                            f"permit {_policy_id(permit)} is shadowed by forbid "
                            f"{_policy_id(forbid)}; the permit will never produce Allow."
                        ),
                    )
                )
    return findings


def detect_redundancy(
    policies: Sequence[tuple[Any, CedarScopeExtraction]],
) -> list[VerificationFinding]:
    """Detect policies that duplicate the scope, effect, and conditions of another.

    Two policies are redundant when they share the same effect, the
    same scope signature across principal, action, and resource, AND
    the same sorted list of condition (kind, body) pairs. Partial
    subsumption (one policy implies another without matching) is not
    detected by this conservative check.

    Args:
        policies: Pairs of (Policy-like object, CedarScopeExtraction)
            to analyze.

    Returns:
        A list of redundancy findings. Empty if no duplication is found.
    """
    findings: list[VerificationFinding] = []
    seen: dict[
        tuple[
            str,
            tuple[str, ...],
            tuple[str, ...],
            tuple[str, ...],
            tuple[tuple[str, str], ...],
        ],
        str,
    ] = {}
    for policy, extraction in policies:
        existing = seen.get(extraction.signature)
        if existing is not None:
            findings.append(
                VerificationFinding(
                    kind="redundancy",
                    severity="warning",
                    policy_id=_policy_id(policy),
                    related_policy_id=existing,
                    message=(
                        f"policy {_policy_id(policy)} has the same scope, effect, "
                        f"and conditions as policy {existing}; one is redundant."
                    ),
                )
            )
        else:
            seen[extraction.signature] = _policy_id(policy)
    return findings


def scopes_match(
    permit_ex: CedarScopeExtraction, forbid_ex: CedarScopeExtraction
) -> bool:
    """Return ``True`` when ``forbid_ex`` fully shadows ``permit_ex``.

    Two policies share shadow only when every slot signature matches.
    The ``any`` kind does not subsume a more specific kind.
    """
    return (
        permit_ex.principal == forbid_ex.principal
        and permit_ex.action == forbid_ex.action
        and permit_ex.resource == forbid_ex.resource
        and permit_ex.conditions == forbid_ex.conditions
    )


def _resolve_action_namespace(
    action_signature: tuple[str, ...],
    actions_by_namespace: Mapping[str, Mapping[str, tuple[str, ...]]],
) -> tuple[str, ...]:
    """Resolve a possibly-namespaceless action signature against the schema.

    ``action == Action::"view"`` with no namespace prefix has the
    empty-namespace form ``("", "view", "named")``. The verifier looks
    up the action across every namespace and picks the namespace where
    the action is uniquely declared. When the action is ambiguous
    (declared in multiple namespaces) or absent, the signature is
    returned unchanged.

    ``action in Action::"readers"`` carries the ``"in_group"`` marker
    and is resolved similarly by picking the namespace that hosts the
    group. When the group is ambiguous, the original signature is
    returned so downstream coverage flags the ambiguity.
    """
    if len(action_signature) != 3:
        return action_signature
    if action_signature[-1] not in {"named", "in_group"}:
        return action_signature
    if action_signature[0]:
        return action_signature
    action_id = action_signature[1]
    matches: list[str] = []
    for namespace, actions in actions_by_namespace.items():
        if action_id in actions:
            matches.append(namespace)
    if len(matches) == 1:
        return (matches[0], action_signature[1], action_signature[2])
    return action_signature


def action_coverage(
    policies: Sequence[tuple[Any, CedarScopeExtraction]],
    action_names: Sequence[tuple[str, str]],
    actions_by_namespace: Mapping[str, Mapping[str, tuple[str, ...]]],
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Return ``(covered, uncovered)`` action identifiers.

    A policy with ``action in Action::"group"`` covers every member
    action of that group. A policy with a specific action covers only
    that action. ``any`` does not cover any specific action.

    Args:
        policies: Pairs of (Policy-like object, CedarScopeExtraction)
            to scan.
        action_names: All known ``(namespace, action_id)`` pairs.
        actions_by_namespace: Mapping ``{namespace: {action_id:
            (member_action_ids)}}`` for action-group expansion.

    Returns:
        Two disjoint sets of ``(namespace, action_id)`` tuples.
    """
    covered: set[tuple[str, str]] = set()
    referenced: set[tuple[str, str]] = set()
    for _, extraction in policies:
        signature = _resolve_action_namespace(extraction.action, actions_by_namespace)
        kind = _action_kind(signature)
        if kind == "named":
            namespace, name = _action_named(signature)
            referenced.add((namespace, name))
            for member in actions_by_namespace.get(namespace, {}).get(name, ()):
                referenced.add((namespace, member))
        elif kind == "group":
            namespace, group_name = _action_named(signature)
            for member in actions_by_namespace.get(namespace, {}).get(group_name, ()):
                referenced.add((namespace, member))
    for pair in action_names:
        if pair in referenced:
            covered.add(pair)
    return covered, set(action_names) - covered


def _action_kind(action_signature: tuple[str, ...]) -> str:
    """Classify an action signature as ``any``, ``named``, or ``group``."""
    if not action_signature or action_signature == ("any",):
        return "any"
    if len(action_signature) >= 3 and action_signature[-1] == "in_group":
        return "group"
    return "named"


def _action_named(action_signature: tuple[str, ...]) -> tuple[str, str]:
    """Return ``(namespace, action_id)`` from a named action signature."""
    if len(action_signature) >= 2:
        return action_signature[0], action_signature[1]
    return "", action_signature[0] if action_signature else ""


def requirement_coverage(
    policies: Sequence[tuple[Any, CedarScopeExtraction]],
    requirement_ids: Sequence[str],
) -> tuple[set[str], set[str]]:
    """Return ``(covered, uncovered)`` requirement identifiers."""
    covered = {_policy_requirement_id(policy) for policy, _ in policies}
    return covered & set(requirement_ids), set(requirement_ids) - covered


def collect_entity_types(
    policies: Sequence[tuple[Any, CedarScopeExtraction]],
) -> set[str]:
    """Return the set of entity type names referenced by ``policies``."""
    types: set[str] = set()
    for _, extraction in policies:
        # Treat action slots as a unit so the action id is excluded
        # from entity-type coverage.
        action = extraction.action
        if (
            isinstance(action, tuple)
            and len(action) >= 3
            and action[-1] in {"named", "in_group"}
        ):
            # Slot 0 holds the action namespace (if any); skip the
            # action id in slot 1 because it is not an entity type.
            for entry in action[:1]:
                for name in _extract_type_names(entry):
                    if name:
                        types.add(name)
        else:
            for name in _extract_type_names(action):
                if name:
                    types.add(name)
        for token in extraction.principal:
            for name in _extract_type_names(token):
                if name:
                    types.add(name)
        for token in extraction.resource:
            for name in _extract_type_names(token):
                if name:
                    types.add(name)
    return types


def extract_entity_types(policies: Sequence[Any]) -> set[str]:
    """Return the set of entity type names referenced by ``policies``.

    This is the public helper used by callers that want a flat set of
    entity types referenced anywhere in the policy set.

    Args:
        policies: Sequence of policies (or policy-shaped objects) to scan.

    Returns:
        Set of entity type identifiers referenced by any policy.
    """
    extracted = [(policy, extract_scope(policy)) for policy in policies]
    return collect_entity_types(extracted)


def missing_coverage_finding(
    kind: str,
    domain: str,
    items: list[Any],
    template: str,
) -> list[VerificationFinding]:
    """Emit a single coverage finding when ``items`` is non-empty."""
    if not items:
        return []
    joined = ", ".join(str(item) for item in items)
    return [
        VerificationFinding(
            kind=kind,
            severity="warning",
            policy_id=domain,
            message=template.format(items=joined, actions=joined),
        )
    ]


def _parse_with_regex(cedar: str) -> CedarScopeExtraction:
    """Regex parser that extracts scope and condition data from Cedar.

    Captures the effect, principal/action/resource types, and any
    condition bodies. Returns a permissive default when no useful
    information can be extracted so verification still runs against
    every policy.
    """
    text = cedar.strip()
    if not text:
        return CedarScopeExtraction(
            principal=("any",),
            action=("any",),
            resource=("any",),
            conditions=(),
            effect="permit",
            cedar=cedar,
        )
    head_match = re.match(
        r"\s*(permit|forbid)\s*\(\s*(?P<principal>.*?)\s*,\s*action\s+(?P<action>[^,]*)\s*,\s*resource\s*(?P<resource>[^);]*?)\s*\)\s*(?P<tail>.*?);?\s*$",
        text,
        flags=re.DOTALL,
    )
    if not head_match:
        return CedarScopeExtraction(
            principal=("any",),
            action=("any",),
            resource=("any",),
            conditions=(),
            effect="permit",
            cedar=cedar,
        )
    effect = head_match.group(1).strip()
    principal_signature = _parse_principal_text(head_match.group("principal"))
    raw_action = head_match.group("action").strip()
    # Strip a leading ``action`` keyword if the head regex captured it.
    if raw_action.startswith("action"):
        raw_action = raw_action[len("action") :].lstrip()
    action_signature = _parse_action_text(raw_action)
    raw_resource = head_match.group("resource").strip()
    if raw_resource.startswith("resource"):
        raw_resource = raw_resource[len("resource") :].lstrip()
    resource_signature = _parse_resource_text(raw_resource)
    tail = head_match.group("tail") or ""
    conditions: list[tuple[str, str]] = []
    for match in re.finditer(r"\bwhen\s*\{(.*?)\}", tail, flags=re.DOTALL):
        conditions.append(("when", match.group(1).strip()))
    for match in re.finditer(r"\bunless\s*\{(.*?)\}", tail, flags=re.DOTALL):
        conditions.append(("unless", match.group(1).strip()))
    return CedarScopeExtraction(
        principal=principal_signature,
        action=action_signature,
        resource=resource_signature,
        conditions=tuple(sorted(conditions)),
        effect=effect,
        cedar=cedar,
    )


def _parse_principal_text(text: str) -> tuple[str, ...]:
    """Parse a Cedar principal expression into a signature tuple.

    Accepts both ``principal`` and the bare operator form. The ``is``
    branch uses a negative lookahead so it does not consume an
    ``in X::Y`` tail.
    """
    normalized = text.strip()
    if not normalized or normalized == "principal":
        return ("any",)
    is_match = re.match(r"^(?:principal\s+)?is\s+((?:(?!.*\s+in\s+).)+)$", normalized)
    if is_match:
        return (is_match.group(1).strip(),)
    eq_match = re.match(r'^(?:principal\s+)?==\s*(.+?)::"([^"]+)"$', normalized)
    if eq_match:
        return (f'{eq_match.group(1).strip()}::{eq_match.group(2).strip()}',)
    in_match = re.match(r'^(?:principal\s+)?in\s+(.+?)::"([^"]+)"$', normalized)
    if in_match:
        # Group membership: return the group type only (not the group id,
        # which is not an entity type).
        return (in_match.group(1).strip(),)
    return (normalized,)


def _parse_action_text(text: str) -> tuple[str, ...]:
    """Parse a Cedar action expression into a signature tuple.

    Accepts both ``action`` and the bare operator form so it works
    with both the head regex output and direct invocations from tests.
    Recognizes ``Action::"id"`` (no namespace) and
    ``Namespace::Action::"id"`` (with namespace), as well as
    ``Namespace::"group"`` action-group references.
    """
    normalized = text.strip()
    if not normalized or normalized == "action":
        return ("any",)
    eq_with_ns = re.match(
        r'^(?:action\s+)?==\s*([A-Za-z0-9_]+)::Action::"([^"]+)"$', normalized
    )
    if eq_with_ns:
        return (eq_with_ns.group(1), eq_with_ns.group(2), "named")
    eq_no_ns = re.match(r'^(?:action\s+)?==\s*Action::"([^"]+)"$', normalized)
    if eq_no_ns:
        return ("", eq_no_ns.group(1), "named")
    eq_with_id = re.match(
        r'^(?:action\s+)?==\s*([A-Za-z0-9_]+)::"([^"]+)"$', normalized
    )
    if eq_with_id:
        return (eq_with_id.group(1), eq_with_id.group(2), "named")
    eq_id_only = re.match(r'^(?:action\s+)?==\s*"([^"]+)"$', normalized)
    if eq_id_only:
        return ("", eq_id_only.group(1), "named")
    in_with_ns = re.match(
        r'^(?:action\s+)?in\s+([A-Za-z0-9_]+)::Action::"([^"]+)"$', normalized
    )
    if in_with_ns:
        return (in_with_ns.group(1), in_with_ns.group(2), "in_group")
    in_no_ns = re.match(r'^(?:action\s+)?in\s+Action::"([^"]+)"$', normalized)
    if in_no_ns:
        return ("", in_no_ns.group(1), "in_group")
    in_with_id = re.match(
        r'^(?:action\s+)?in\s+([A-Za-z0-9_]+)::"([^"]+)"$', normalized
    )
    if in_with_id:
        return (in_with_id.group(1), in_with_id.group(2), "in_group")
    in_id_only = re.match(r'^(?:action\s+)?in\s+"([^"]+)"$', normalized)
    if in_id_only:
        return ("", in_id_only.group(1), "in_group")
    return (normalized,)


def _parse_resource_text(text: str) -> tuple[str, ...]:
    """Parse a Cedar resource expression into a signature tuple.

    Accepts both ``resource`` and the bare operator form. The ``is``
    branch uses a negative lookahead so it does not consume the
    ``in X::Y`` tail. The nested ``in X::Z`` form returns a tuple
    of the child type and parent type names so coverage analysis can
    pick both up.
    """
    normalized = text.strip()
    if not normalized or normalized == "resource":
        return ("any",)
    is_match = re.match(r"^(?:resource\s+)?is\s+((?:(?!.*\s+in\s+).)+)$", normalized)
    if is_match:
        return (is_match.group(1).strip(),)
    in_match = re.match(
        r'^(?:resource\s+)?is\s+(.+?)\s+in\s+(.+?)::"([^"]+)"$', normalized
    )
    if in_match:
        return (
            in_match.group(1).strip(),
            in_match.group(2).strip(),
        )
    return (normalized,)


def _extract_type_names(token: Any) -> list[str]:
    """Pull type-name identifiers out of a slot signature token.

    Handles plain type-name strings (``Foo::User``), bare principal
    placeholders (``any``), operator tokens (``==``, ``in``,
    ``named``, ``in_group``), quoted action ids, and nested resource
    tuples produced by ``resource is X in Y::Z``.
    """
    if token is None:
        return []
    if isinstance(token, str):
        if not token or token in {"any", ""}:
            return []
        if (
            token in {"==", "in", "named", "in_group"}
            or token.endswith(" ==")
            or token.endswith(" in")
        ):
            return []
        if token.startswith('"') and token.endswith('"'):
            return []
        return [token]
    if isinstance(token, tuple):
        # If the token itself is an action tuple (namespace, id, marker),
        # skip the action id and only collect nested type references.
        if len(token) >= 3 and token[-1] in {"named", "in_group"}:
            return []
        names: list[str] = []
        for entry in token:
            names.extend(_extract_type_names(entry))
        return names
    return []


__all__ = [
    "CedarScopeExtraction",
    "VerificationFinding",
    "VerificationReport",
    "detect_redundancy",
    "detect_shadowing",
    "extract_entity_types",
    "extract_scope",
    "verify_policies",
]
