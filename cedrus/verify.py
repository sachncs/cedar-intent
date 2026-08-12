"""Static symbolic verification for Cedar policy sets.

The :meth:`Verifier.verify` method performs a static analysis of a
domain's policy set and reports:

* **shadowing** - a ``forbid`` whose scope dominates a ``permit``,
  making the permit unreachable in practice;
* **redundancy** - two policies with equivalent scopes, the same
  effect, and the same conditions (one is implied by the other);
* **requirement coverage** - whether every loaded requirement has at
  least one compiled policy;
* **action coverage** - whether every action declared in the schema
  has at least one policy that references it, with action-group
  membership expanded;
* **entity-type coverage** - whether every entity type in the schema
  is referenced by at least one policy.

The verifier analyzes the deployed Cedar source directly rather than
the typed intent metadata, so coverage and shadowing reflect what
will actually run.

Algorithm notes:
    Scope dominance is approximated by comparing the *signature* of a
    scope: a tuple of (kind, type_name, entity_id, group_type,
    group_id) for principals, an analogous tuple for resources, and a
    tuple that includes the namespace and ``"named"``/``"in_group"``
    flag for actions. Two policies are considered to share a shadow
    or a redundancy only when their scope signatures match across
    every slot AND their condition signatures match.

    ``any`` does not subsume a non-``any`` scope: a forbid on Alice
    does not shadow a permit on ``any`` principal.

    Action coverage expands action-group membership:
    ``action in Action::"readers"`` counts as covering every member
    action of the ``readers`` group. This keeps coverage faithful to
    Cedar's authorization semantics.

    Cedar parsing uses :func:`cedarpy.policies_to_json_str` to obtain
    a structured AST rather than a regex. The verifier therefore
    cannot be tricked by comments, embedded semicolons, or syntax that
    a regex would silently misclassify. When cedarpy cannot parse a
    policy, the verifier emits a ``malformed-policy`` warning rather
    than falling back to a permissive default.

    Conditions are compared by hashing the canonical JSON form of
    their AST bodies, so ``principal == User::"alice"`` and equivalent
    reorderings produce identical signatures.

    Complexity is O(n^2) for shadowing/redundancy across n policies
    and O(n*m) for coverage across n policies and m schema entries.
    That is acceptable for typical domain sizes (dozens to low hundreds
    of policies). A full SMT-backed equivalence check via
    cedar-policy-symcc would replace these approximations when needed.

The AST parsing helpers, the coverage algorithms, and the policy
accessors are all classmethods / staticmethods of :class:`Verifier`
and :class:`Extraction`; there are no module-level free functions.

Attributes:
    Finding: A single finding emitted by verification.
    Report: Aggregate result of a verification run.
    Extraction: Scope and condition data extracted from a policy.
    Parse: Raised when cedarpy cannot parse a Cedar policy.
    Verifier: Static symbolic verifier.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import cedarpy

from cedrus.schema import Schema

VerificationSeverity = str  # "warning" | "info"


class Parse(Exception):
    """Raised when cedarpy cannot parse a Cedar policy."""


@dataclass(frozen=True, slots=True)
class Finding:
    """A single finding emitted by :meth:`Verifier.verify`.

    Attributes:
        kind: Finding category (for example ``"shadowing"``).
        severity: ``"warning"`` or ``"info"``.
        policy_id: Identifier of the policy the finding concerns.
        message: Human-readable explanation.
        relatedpolicy_id: Optional identifier of a related policy.
    """

    kind: str
    severity: VerificationSeverity
    policy_id: str
    message: str
    relatedpolicy_id: str | None = None

    def to_dict(self) -> Mapping[str, Any]:
        """Return a JSON-friendly representation of the finding.

        Returns:
            A dict with ``kind``, ``severity``, ``policy_id``,
            ``message`` and ``relatedpolicy_id`` keys.
        """
        return {
            "kind": self.kind,
            "severity": self.severity,
            "policy_id": self.policy_id,
            "message": self.message,
            "relatedpolicy_id": self.relatedpolicy_id,
        }


@dataclass(frozen=True, slots=True)
class Report:
    """Aggregate result of :meth:`Verifier.verify`.

    Attributes:
        domain: Domain the report applies to.
        findings: Findings collected during verification.
        requirements_covered: Requirements addressed by at least one
            policy.
        requirements_uncovered: Requirements with no compiled policy.
        actions_covered: Schema actions referenced by at least one
            policy.
        actions_uncovered: Schema actions not referenced by any policy.
    """

    domain: str
    findings: tuple[Finding, ...]
    requirements_covered: tuple[str, ...]
    requirements_uncovered: tuple[str, ...]
    actions_covered: tuple[tuple[str, str], ...]
    actions_uncovered: tuple[tuple[str, str], ...]

    @property
    def passed(self) -> bool:
        """Return ``True`` when no warning-level findings exist."""
        return not any(finding.severity == "warning" for finding in self.findings)

    def to_dict(self) -> Mapping[str, Any]:
        """Return a JSON-friendly representation of the report.

        Returns:
            A dict with ``domain``, ``passed``, ``findings``,
            ``requirements_covered``, ``requirements_uncovered``,
            ``actions_covered`` and ``actions_uncovered`` keys.
        """
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
class Extraction:
    """Scope and condition data extracted from a Cedar policy's source.

    The verifier analyzes the deployed Cedar rather than the typed
    intent metadata so that imported policies (whose intent is
    ``None``) participate in coverage and shadowing checks.

    Attributes:
        principal: Tuple identifying the principal slot.
        action: Tuple identifying the action slot (including
            namespace).
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

    @classmethod
    def from_policy(
        cls,
        policy: Any,
        schema_actions_by_namespace: Mapping[
            str, Mapping[str, tuple[str, ...]]
        ],
    ) -> "Extraction":
        """Extract an :class:`Extraction` from one policy via cedarpy.

        Args:
            policy: Policy-like object (must expose ``policy.cedar`` or
                ``policy.notes["cedar_text"]``).
            schema_actions_by_namespace: Action-group membership
                mapping for namespace resolution.

        Returns:
            The :class:`Extraction` for ``policy``.

        Raises:
            Parse: When cedarpy cannot parse the policy's Cedar.
        """
        return parse_ast(cls.policy_cedar_text(policy), schema_actions_by_namespace)

    @staticmethod
    def policy_id_of(policy: Any) -> str:
        """Return the policy id, accepting Policy or Intent."""
        return (
            getattr(policy, "id", None)
            or getattr(policy, "intent_id", None)
            or ""
        )

    @staticmethod
    def policy_requirement_id_of(policy: Any) -> str:
        """Return the requirement id associated with a policy-like object."""
        requirement = getattr(policy, "requirement", None)
        if requirement is not None:
            return getattr(requirement, "id", "")
        return getattr(policy, "requirement_id", "")

    @staticmethod
    def policy_cedar_text(policy: Any) -> str:
        """Return the Cedar source text associated with a policy-like object.

        Accepts any of:
        * a :class:`~cedrus.compile.Intent` — calls ``policy.compile().cedar``
        * an object with a ``cedar`` attribute (e.g., :class:`Compiled`,
          :class:`Draft`, :class:`Existing`) — uses it directly
        * an object whose ``notes`` mapping carries ``"cedar_text"``
        """
        cedar = getattr(policy, "cedar", None)
        if cedar:
            return str(cedar)
        if hasattr(policy, "compile") and callable(policy.compile):
            try:
                return str(policy.compile().cedar)
            except Exception:
                pass
        notes = getattr(policy, "notes", None)
        if isinstance(notes, Mapping):
            return str(notes.get("cedar_text", ""))
        return ""


@dataclass(frozen=True, slots=True)
class Verifier:
    """Static symbolic verifier.

    The default implementation analyzes Cedar source via the cedarpy
    AST. Subclass and override individual methods to customize the
    verification strategy (e.g., an SMT-based backend).

    The class is stateless; construction is cheap.
    """

    schema: Schema

    def verify(
        self,
        policies: Sequence[Any],
        requirement_ids: Sequence[str] = (),
        action_names: Sequence[tuple[str, str]] = (),
        entity_type_names: Iterable[str] = (),
        domain: str = "",
    ) -> Report:
        """Verify ``policies`` and return a structured report.

        Args:
            policies: Policy-like objects to inspect. Each must
                expose ``policy.cedar`` (or ``policy.notes["cedar_text"]``).
            requirement_ids: All known requirement identifiers.
            action_names: All known ``(namespace, action_id)`` pairs.
            entity_type_names: All known entity type identifiers.
            domain: Domain name reported in the result.

        Returns:
            A :class:`Report` aggregating findings and coverage.
        """
        extracted: list[tuple[Any, Extraction]] = []
        malformed: list[tuple[Any, str]] = []
        for policy in policies:
            try:
                extraction = self.extract_one(policy)
            except Parse as error:
                malformed.append((policy, str(error)))
                continue
            extracted.append((policy, extraction))

        findings: list[Finding] = []
        for policy, parse_error in malformed:
            findings.append(
                Finding(
                    kind="malformed-policy",
                    severity="warning",
                    policy_id=Extraction.policy_id_of(policy),
                    message=(
                        f"policy {Extraction.policy_id_of(policy) or '(unknown)'} "
                        f"could not be parsed by cedarpy and was skipped: "
                        f"{parse_error}"
                    ),
                )
            )
        findings.extend(self.detect_shadowing(extracted))
        findings.extend(self.detect_redundancy(extracted))
        covered_action_names, uncovered_action_names = self.action_coverage(
            extracted, action_names
        )
        covered_requirements, uncovered_requirements = (
            self.requirement_coverage(extracted, requirement_ids)
        )
        entity_type_set = set(entity_type_names)
        findings.extend(
            self.missing_coverage_finding(
                "uncovered-action",
                domain,
                sorted(uncovered_action_names),
                "No policy references action {actions}.",
            )
        )
        findings.extend(
            self.missing_coverage_finding(
                "uncovered-requirement",
                domain,
                sorted(uncovered_requirements),
                "No compiled policy addresses requirement {items}.",
            )
        )
        findings.extend(
            self.missing_coverage_finding(
                "uncovered-entity-type",
                domain,
                sorted(entity_type_set - self.collect_entity_types(extracted)),
                "No policy references entity type {items}.",
            )
        )
        return Report(
            domain=domain,
            findings=tuple(findings),
            requirements_covered=tuple(sorted(covered_requirements)),
            requirements_uncovered=tuple(sorted(uncovered_requirements)),
            actions_covered=tuple(sorted(covered_action_names)),
            actions_uncovered=tuple(sorted(uncovered_action_names)),
        )

    def extract(self, policy: Any) -> Extraction:
        """Extract scope signature from a single policy.

        Public hook so callers can build their own analyses; the
        internal ``extract_one`` does the actual work.

        Args:
            policy: Policy-like object to extract.

        Returns:
            The :class:`Extraction` for ``policy``.

        Raises:
            Parse: When cedarpy cannot parse the policy.
        """
        return self.extract_one(policy)

    def shadow(self, policies: Sequence[Any]) -> list[Finding]:
        """Detect shadowed permits.

        Args:
            policies: Policies to inspect.

        Returns:
            A list of shadowing findings (empty when none found).
        """
        return self.detect_shadowing(
            [(policy, self.extract_one(policy)) for policy in policies]
        )

    def redundant(self, policies: Sequence[Any]) -> list[Finding]:
        """Detect redundant duplicate policies.

        Args:
            policies: Policies to inspect.

        Returns:
            A list of redundancy findings (empty when none found).
        """
        return self.detect_redundancy(
            [(policy, self.extract_one(policy)) for policy in policies]
        )

    def types(self, policies: Sequence[Any]) -> set[str]:
        """Collect every entity type referenced in ``policies``.

        Args:
            policies: Policies to inspect.

        Returns:
            Set of entity type identifiers referenced anywhere.
        """
        return self.collect_entity_types(
            [(policy, self.extract_one(policy)) for policy in policies]
        )

    def coverage_action(
        self,
        policies: Sequence[Any],
        names: Sequence[tuple[str, str]],
    ) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
        """Coverage split for the actions in ``names``.

        Args:
            policies: Policies to inspect.
            names: All known ``(namespace, action_id)`` pairs.

        Returns:
            Two disjoint sets of ``(namespace, action_id)`` tuples:
            covered and uncovered.
        """
        return self.action_coverage(
            [(policy, self.extract_one(policy)) for policy in policies],
            names,
        )

    def coverage_need(
        self,
        policies: Sequence[Any],
        ids: Sequence[str],
    ) -> tuple[set[str], set[str]]:
        """Coverage split for the requirement ids in ``ids``.

        Args:
            policies: Policies to inspect.
            ids: All known requirement identifiers.

        Returns:
            Two disjoint sets of requirement ids: covered and
            uncovered.
        """
        return self.requirement_coverage(
            [(policy, self.extract_one(policy)) for policy in policies],
            ids,
        )

    def uncovered(
        self,
        items: list[Any],
        kind: str,
        template: str,
    ) -> list[Finding]:
        """Emit a coverage-finding list when ``items`` is non-empty.

        Args:
            items: Uncovered items; the finding is empty when this
                list is empty.
            kind: Finding ``kind`` (e.g., ``"uncovered-action"``).
            template: Message template with ``{items}`` placeholder.

        Returns:
            A list of :class:`Finding` (empty when ``items`` is empty).
        """
        return self.missing_coverage_finding(kind, "", items, template)

    def extract_one(self, policy: Any) -> Extraction:
        return parse_ast(
            Extraction.policy_cedar_text(policy),
            self.schema.actions_by_namespace(),
        )

    def detect_shadowing(
        self,
        policies: Sequence[tuple[Any, Extraction]],
    ) -> list[Finding]:
        """Detect ``forbid`` policies that shadow ``permit`` policies.

        A forbid shadows a permit when the forbid's scope equals the
        permit's scope across every slot AND the forbid's conditions
        equal the permit's conditions. ``any`` does not subsume a
        non-``any`` scope, so a forbid on Alice does not shadow a
        permit on ``any`` principal.

        Args:
            policies: Pairs of (Policy-like object, Extraction) to
                analyze.

        Returns:
            A list of shadowing findings. Empty when no shadowing is
            found.
        """
        findings: list[Finding] = []
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
                        Finding(
                            kind="shadowing",
                            severity="warning",
                            policy_id=Extraction.policy_id_of(permit),
                            relatedpolicy_id=Extraction.policy_id_of(forbid),
                            message=(
                                f"permit {Extraction.policy_id_of(permit)} is "
                                f"shadowed by forbid {Extraction.policy_id_of(forbid)}; "
                                "the permit will never produce Allow."
                            ),
                        )
                    )
        return findings

    def detect_redundancy(
        self,
        policies: Sequence[tuple[Any, Extraction]],
    ) -> list[Finding]:
        """Detect policies that duplicate the scope, effect, and conditions of another.

        Two policies are redundant when they share the same effect,
        the same scope signature across principal, action, and
        resource, AND the same sorted list of condition (kind, body)
        pairs. Partial subsumption (one policy implies another without
        matching) is not detected by this conservative check.

        Args:
            policies: Pairs of (Policy-like object, Extraction) to
                analyze.

        Returns:
            A list of redundancy findings. Empty when no duplication
            is found.
        """
        findings: list[Finding] = []
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
                    Finding(
                        kind="redundancy",
                        severity="warning",
                        policy_id=Extraction.policy_id_of(policy),
                        relatedpolicy_id=existing,
                        message=(
                            f"policy {Extraction.policy_id_of(policy)} has the same "
                            f"scope, effect, and conditions as policy {existing}; "
                            "one is redundant."
                        ),
                    )
                )
            else:
                seen[extraction.signature] = Extraction.policy_id_of(policy)
        return findings

    def action_coverage(
        self,
        policies: Sequence[tuple[Any, Extraction]],
        action_names: Sequence[tuple[str, str]],
    ) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
        """Return ``(covered, uncovered)`` action identifiers.

        A policy with ``action in Action::"group"`` covers every
        member action of that group. A policy with a specific action
        covers only that action. ``any`` does not cover any specific
        action.

        Args:
            policies: Pairs of (Policy-like object, Extraction).
            action_names: All known ``(namespace, action_id)`` pairs.

        Returns:
            Two disjoint sets of ``(namespace, action_id)`` tuples.
        """
        actions_by_namespace = self.schema.actions_by_namespace()
        covered: set[tuple[str, str]] = set()
        referenced: set[tuple[str, str]] = set()
        for _, extraction in policies:
            signature = resolve_action_namespace(
                extraction.action, actions_by_namespace, action_names
            )
            kind = action_kind(signature)
            if kind == "named":
                namespace, name = action_named(signature)
                referenced.add((namespace, name))
                for member in actions_by_namespace.get(namespace, {}).get(name, ()):
                    referenced.add((namespace, member))
            elif kind == "group":
                namespace, group_name = action_named(signature)
                for member in actions_by_namespace.get(
                    namespace, {}
                ).get(group_name, ()):
                    referenced.add((namespace, member))
        for pair in action_names:
            if pair in referenced:
                covered.add(pair)
        return covered, set(action_names) - covered

    def requirement_coverage(
        self,
        policies: Sequence[tuple[Any, Extraction]],
        requirement_ids: Sequence[str],
    ) -> tuple[set[str], set[str]]:
        """Return ``(covered, uncovered)`` requirement identifiers."""
        covered = {Extraction.policy_requirement_id_of(policy) for policy, _ in policies}
        return covered & set(requirement_ids), set(requirement_ids) - covered

    def collect_entity_types(
        self,
        policies: Sequence[tuple[Any, Extraction]],
    ) -> set[str]:
        """Return the set of entity type names referenced by ``policies``."""
        types: set[str] = set()
        for _, extraction in policies:
            for name in extract_type_names(extraction.action):
                if name:
                    types.add(name)
            for name in extract_type_names(extraction.principal):
                if name:
                    types.add(name)
            for name in extract_type_names(extraction.resource):
                if name:
                    types.add(name)
        return types

    def missing_coverage_finding(
        self,
        kind: str,
        domain: str,
        items: list[Any],
        template: str,
    ) -> list[Finding]:
        """Emit a single coverage finding when ``items`` is non-empty."""
        if not items:
            return []
        joined = ", ".join(str(item) for item in items)
        return [
            Finding(
                kind=kind,
                severity="warning",
                policy_id=domain,
                message=template.format(items=joined, actions=joined),
            )
        ]


def parse_ast(
    cedar: str,
    actions_by_namespace: Mapping[str, Mapping[str, tuple[str, ...]]],
) -> Extraction:
    """Build an :class:`Extraction` from a Cedar source string.

    Uses :func:`cedarpy.policies_to_json_str` to obtain a normalized
    JSON AST, then walks the AST to extract principal / action /
    resource signatures and a canonicalized condition signature.

    Args:
        cedar: Cedar source text to parse.
        actions_by_namespace: Action-group membership mapping
            for namespace resolution.

    Returns:
        The :class:`Extraction` for ``cedar``.

    Raises:
        Parse: When cedarpy cannot parse ``cedar`` or when the input
            is empty.
    """
    text = cedar.strip()
    if not text:
        raise Parse("empty Cedar policy text")
    try:
        json_text = cedarpy.policies_to_json_str(text + "\n")
    except (ValueError, RuntimeError) as error:
        raise Parse(str(error)) from error
    try:
        doc = json.loads(json_text)
    except json.JSONDecodeError as error:
        raise Parse(str(error)) from error
    static_policies = doc.get("staticPolicies") or {}
    if not static_policies:
        raise Parse("cedarpy produced no static policies")
    policy_node = next(iter(static_policies.values()))
    effect = policy_node.get("effect", "permit")
    principal = parse_principal_node(policy_node.get("principal") or {})
    action = parse_action_node(
        policy_node.get("action") or {}, actions_by_namespace
    )
    resource = parse_resource_node(policy_node.get("resource") or {})
    conditions = parse_conditions(policy_node.get("conditions") or [])
    return Extraction(
        principal=principal,
        action=action,
        resource=resource,
        conditions=conditions,
        effect=effect,
        cedar=cedar,
    )


def parse_principal_node(node: Mapping[str, Any]) -> tuple[str, ...]:
    """Convert a cedarpy principal node into a signature tuple."""
    op = node.get("op")
    if op == "All":
        return ("any",)
    if op == "is":
        return (str(node.get("entity_type", "")).strip(),)
    if op == "==":
        entity = node.get("entity") or {}
        return (f'{entity.get("type", "")}::{entity.get("id", "")}',)
    if op == "in":
        entity = node.get("entity") or {}
        return (str(entity.get("type", "")).strip(),)
    return (json.dumps(node, sort_keys=True),)


def parse_action_node(
    node: Mapping[str, Any],
    actions_by_namespace: Mapping[str, Mapping[str, tuple[str, ...]]],
) -> tuple[str, ...]:
    """Convert a cedarpy action node into a signature tuple.

    cedarpy emits ``"Action"`` as the type for namespace-less action
    references like ``action == Action::"view"``. The verifier treats
    that placeholder as the empty namespace so the downstream
    resolver can pick the correct schema namespace.

    Args:
        node: cedarpy action node.
        actions_by_namespace: Action-group membership mapping.

    Returns:
        The action signature tuple.
    """
    op = node.get("op")
    if op == "All":
        return ("any",)
    if op == "==":
        entity = node.get("entity") or {}
        return (
            normalize_action_type(entity.get("type", "")),
            str(entity.get("id", "")),
            "named",
        )
    if op == "in":
        # cedarpy emits ``entity`` (singular) for single-target ``in``
        # expressions like ``action in Action::"readers"`` and
        # ``entities`` (plural) for list forms like
        # ``action in [Action::"view", Action::"edit"]``.
        entities = node.get("entities")
        if entities is None and node.get("entity") is not None:
            entities = [node["entity"]]
        if entities is None:
            entities = []
        if len(entities) == 1:
            entity = entities[0]
            return (
                normalize_action_type(entity.get("type", "")),
                str(entity.get("id", "")),
                "in_group",
            )
        kinds = ",".join(
            f"{normalize_action_type(e.get('type', ''))}::{e.get('id', '')}"
            for e in entities
        )
        return (kinds, "list", "in_group")
    return (json.dumps(node, sort_keys=True),)


def normalize_action_type(type_name: Any) -> str:
    """Strip cedarpy's ``"Action"`` and ``"<Namespace>::Action"`` placeholders.

    Cedar policies reference actions as ``Action::"id"`` (no
    namespace) or ``<Namespace>::Action::"id"`` (with namespace).
    cedarpy's JSON AST emits the type as ``"Action"`` or
    ``"<Namespace>::Action"``. The verifier normalizes those to the
    empty string (no namespace) or to the bare namespace so
    downstream resolution matches the schema's flat
    ``(namespace, id)`` form.

    Args:
        type_name: The cedarpy-emitted action type.

    Returns:
        The normalized type name (empty string for ``"Action"``,
        bare namespace for ``"<Namespace>::Action"``, otherwise
        unchanged).
    """
    text = str(type_name)
    if text == "Action":
        return ""
    if text.endswith("::Action"):
        return text[: -len("::Action")]
    return text


def parse_resource_node(node: Mapping[str, Any]) -> tuple[str, ...]:
    """Convert a cedarpy resource node into a signature tuple."""
    op = node.get("op")
    if op == "All":
        return ("any",)
    if op == "is":
        entity_type = node.get("entity_type")
        in_entity = node.get("in_entity")
        in_node = node.get("in")
        if in_entity is None and isinstance(in_node, Mapping):
            in_entity = in_node.get("entity") or {}
        if in_entity:
            return (str(entity_type), str(in_entity.get("type", "")))
        return (str(entity_type).strip(),)
    if op == "==":
        entity = node.get("entity") or {}
        return (f'{entity.get("type", "")}::{entity.get("id", "")}',)
    if op == "in":
        entity = node.get("entity") or {}
        return (str(entity.get("type", "")).strip(),)
    return (json.dumps(node, sort_keys=True),)


def parse_conditions(
    raw_conditions: Sequence[Mapping[str, Any]],
) -> tuple[tuple[str, str], ...]:
    """Convert cedarpy condition nodes into ``(kind, canonical_body)`` tuples.

    The canonical body is the JSON-serialized form of the AST with
    keys sorted. This means equivalent expressions produce identical
    signatures regardless of source whitespace or operator ordering
    choices.

    Args:
        raw_conditions: cedarpy condition nodes.

    Returns:
        Sorted tuple of ``(kind, canonical_body)`` pairs.
    """
    pairs: list[tuple[str, str]] = []
    for condition in raw_conditions:
        kind = condition.get("kind", "when")
        body = condition.get("body")
        canonical = json.dumps(body, sort_keys=True) if body is not None else ""
        pairs.append((str(kind), canonical))
    return tuple(sorted(pairs))


def scopes_match(permit_ex: Extraction, forbid_ex: Extraction) -> bool:
    """Return ``True`` when ``forbid_ex`` fully shadows ``permit_ex``.

    Two policies share shadow only when every slot signature
    matches. The ``any`` kind does not subsume a more specific kind.

    Args:
        permit_ex: Extraction of the permit policy.
        forbid_ex: Extraction of the forbid policy.

    Returns:
        Whether the scopes match exactly.
    """
    return (
        permit_ex.principal == forbid_ex.principal
        and permit_ex.action == forbid_ex.action
        and permit_ex.resource == forbid_ex.resource
        and permit_ex.conditions == forbid_ex.conditions
    )


def resolve_action_namespace(
    action_signature: tuple[str, ...],
    actions_by_namespace: Mapping[str, Mapping[str, tuple[str, ...]]],
    action_names: Sequence[tuple[str, str]] | None = None,
) -> tuple[str, ...]:
    """Resolve a possibly-namespaceless action signature against the schema.

    ``action == Action::"view"`` with no namespace prefix has the
    empty-namespace form ``("", "view", "named")``. The verifier
    looks up the action across every namespace and picks the
    namespace where the action is uniquely declared. When the
    action is ambiguous (declared in multiple namespaces) or absent,
    the signature is returned unchanged.

    ``action in Action::"readers"`` carries the ``"in_group"`` marker
    and is resolved similarly by picking the namespace that hosts
    the group. When the group is ambiguous, the original signature
    is returned so downstream coverage flags the ambiguity.

    When ``actions_by_namespace`` is empty but ``action_names`` is
    provided, the resolver falls back to a single-namespace lookup
    against ``action_names`` so coverage can still match against the
    flat action list.

    Args:
        action_signature: Action signature tuple.
        actions_by_namespace: Action-group membership mapping.
        action_names: Optional flat list of all known actions.

    Returns:
        The resolved action signature.
    """
    if len(action_signature) != 3:
        return action_signature
    if action_signature[-1] not in {"named", "in_group"}:
        return action_signature
    if action_signature[0]:
        return action_signature
    action_id = action_signature[1]
    if actions_by_namespace:
        matches: list[str] = []
        for namespace, actions in actions_by_namespace.items():
            if action_id in actions:
                matches.append(namespace)
        if len(matches) == 1:
            return (matches[0], action_signature[1], action_signature[2])
        return action_signature
    if action_names is not None:
        namespaces_for_id = {ns for ns, name in action_names if name == action_id}
        if len(namespaces_for_id) == 1:
            return (next(iter(namespaces_for_id)), action_id, action_signature[2])
    return action_signature


def action_kind(action_signature: tuple[str, ...]) -> str:
    """Classify an action signature as ``any``, ``named``, or ``group``."""
    if not action_signature or action_signature == ("any",):
        return "any"
    if len(action_signature) >= 3 and action_signature[-1] == "in_group":
        return "group"
    return "named"


def action_named(action_signature: tuple[str, ...]) -> tuple[str, str]:
    """Return ``(namespace, action_id)`` from a named action signature."""
    if len(action_signature) >= 2:
        return action_signature[0], action_signature[1]
    return "", action_signature[0] if action_signature else ""


def extract_type_names(token: Any) -> list[str]:
    """Pull type-name identifiers out of a slot signature token."""
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
        if len(token) >= 3 and token[-1] in {"named", "in_group"}:
            return []
        names: list[str] = []
        for entry in token:
            names.extend(extract_type_names(entry))
        return names
    return []


def collect_entity_types(
    policies: Sequence[tuple[Any, Extraction]],
) -> set[str]:
    """Return the set of entity type names referenced by ``policies``."""
    types: set[str] = set()
    for _, extraction in policies:
        for name in extract_type_names(extraction.action):
            if name:
                types.add(name)
        for name in extract_type_names(extraction.principal):
            if name:
                types.add(name)
        for name in extract_type_names(extraction.resource):
            if name:
                types.add(name)
    return types


def missing_coverage_finding(
    kind: str,
    domain: str,
    items: list[Any],
    template: str,
) -> list[Finding]:
    """Emit a single coverage finding when ``items`` is non-empty."""
    if not items:
        return []
    joined = ", ".join(str(item) for item in items)
    return [
        Finding(
            kind=kind,
            severity="warning",
            policy_id=domain,
            message=template.format(items=joined, actions=joined),
        )
    ]


__all__ = [
    "Extraction",
    "Finding",
    "Parse",
    "Report",
    "Verifier",
]
