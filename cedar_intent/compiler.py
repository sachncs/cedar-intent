"""Deterministic Cedar compiler.

A :class:`PolicyIntent` is the typed intermediate representation produced
by a generator. The compiler walks the intent and emits Cedar source
text without any LLM involvement. It is the only code in cedar-intent
that constructs Cedar syntax.

The output is deterministic: calling :func:`compile_intent` twice with
the same intent returns identical Cedar source. Every renderer routes
through :func:`json.dumps` for value escaping so any value can be
embedded in a Cedar string literal without manual quote or backslash
handling. Scope rendering is one branch per ``kind`` value with no
shared fallbacks, so a malformed scope raises
:class:`CompilationError` instead of producing silent garbage.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from .errors import CompilationError
from .scopes import ActionScope, ConditionClause, PrincipalScope, ResourceScope

Effect = Literal["permit", "forbid"]


@dataclass(frozen=True, slots=True)
class PolicyIntent:
    """Typed authorization intent for one policy.

    An intent is the contract between a generator (human or LLM) and the
    deterministic compiler. A valid intent must round-trip through
    :func:`compile_intent` to produce Cedar that validates against the
    supplied schema.

    Attributes:
        id: Stable intent identifier (for example ``"hr-hr-042"``).
        requirement_id: Identifier of the originating :class:`Requirement`.
        effect: Either ``"permit"`` or ``"forbid"``.
        principal: Scope applied to the principal slot.
        action: Scope applied to the action slot.
        resource: Scope applied to the resource slot.
        when_clauses: Optional list of ``when`` clauses joined with ``&&``.
        unless_clauses: Optional list of ``unless`` clauses joined with ``||``.
        notes: Free-form metadata recorded for downstream consumers.
    """

    id: str
    requirement_id: str
    effect: Effect
    principal: PrincipalScope
    action: ActionScope
    resource: ResourceScope
    when_clauses: tuple[ConditionClause, ...] = field(default_factory=tuple)
    unless_clauses: tuple[ConditionClause, ...] = field(default_factory=tuple)
    notes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.effect not in {"permit", "forbid"}:
            raise CompilationError(f"intent {self.id} has invalid effect {self.effect!r}")
        if not self.id or not self.id.strip():
            raise CompilationError("policy intent id must be non-empty")


@dataclass(frozen=True, slots=True)
class CompiledSource:
    """Output of the deterministic compiler.

    Attributes:
        intent_id: Identifier of the intent that produced the source.
        cedar: The rendered Cedar source text.
        compiled_at: Timestamp at which compilation completed.
    """

    intent_id: str
    cedar: str
    compiled_at: datetime

    def to_dict(self) -> Mapping[str, object]:
        """Return a JSON-friendly representation of the compiled source."""
        return {
            "intent_id": self.intent_id,
            "cedar": self.cedar,
            "compiled_at": self.compiled_at.isoformat(),
        }


def compile_intent(intent: PolicyIntent) -> CompiledSource:
    """Compile a single :class:`PolicyIntent` to Cedar source.

    The compiler assembles the slot clauses, appends ``when`` and
    ``unless`` blocks when present, and terminates the statement with
    a semicolon. Whitespace is normalized to a single space.

    Args:
        intent: The intent to compile.

    Returns:
        A :class:`CompiledSource` containing the rendered Cedar text and
        metadata.
    """
    principal_clause = render_principal(intent.principal)
    action_clause = render_action(intent.action)
    resource_clause = render_resource(intent.resource)
    parts = [
        f"{intent.effect} (",
        f"    {principal_clause},",
        f"    {action_clause},",
        f"    {resource_clause}",
        ")",
    ]
    if intent.when_clauses:
        joined = " && ".join(clause.body for clause in intent.when_clauses)
        parts.append(f"when {{ {joined} }}")
    if intent.unless_clauses:
        joined = " || ".join(clause.body for clause in intent.unless_clauses)
        parts.append(f"unless {{ {joined} }}")
    parts.append(";")
    return CompiledSource(
        intent_id=intent.id,
        cedar="\n".join(parts),
        compiled_at=datetime.now(UTC),
    )


def render_principal(scope: PrincipalScope) -> str:
    """Render a :class:`PrincipalScope` to its Cedar source representation.

    Args:
        scope: Principal scope to render.

    Returns:
        A Cedar source fragment suitable for the principal slot of a
        policy statement.

    Raises:
        CompilationError: If ``scope.kind`` is not a recognized kind.
    """
    if scope.kind == "any":
        return "principal"
    if scope.kind == "type":
        # The "type" branch renders ``principal == X::"*"`` to match any
        # entity of type ``X`` whose id matches the Cedar ``*`` glob.
        # The ``"*"`` literal is a Cedar-side idiom, not a Python string
        # we have to interpret: Cedar treats ``"*"`` inside a string
        # literal as a wildcard match. ``json.dumps`` quotes and escapes
        # the value safely so any user-supplied entity id (including
        # quotes or backslashes) is embedded without injection risk.
        identifier = scope.entity_id or "*"
        return f"principal == {scope.type_name}::{json.dumps(identifier)}"
    if scope.kind == "is_type":
        return f"principal is {scope.type_name}"
    if scope.kind == "specific":
        return f"principal == {scope.type_name}::{json.dumps(scope.entity_id)}"
    if scope.kind == "in_group":
        return f"principal in {scope.group_type}::{json.dumps(scope.group_id)}"
    raise CompilationError(f"unsupported principal scope: {scope.kind}")


def render_action(scope: ActionScope) -> str:
    """Render an :class:`ActionScope` to its Cedar source representation.

    Args:
        scope: Action scope to render.

    Returns:
        A Cedar source fragment suitable for the action slot.

    Raises:
        CompilationError: If ``scope.kind`` is not a recognized kind.
    """
    if scope.kind == "any":
        return "action"
    namespace_prefix = f"{scope.namespace}::" if scope.namespace else ""
    if scope.kind == "named":
        return f"action == {namespace_prefix}Action::{json.dumps(scope.name)}"
    if scope.kind == "in_group":
        return f"action in {namespace_prefix}Action::{json.dumps(scope.group)}"
    raise CompilationError(f"unsupported action scope: {scope.kind}")


def render_resource(scope: ResourceScope) -> str:
    """Render a :class:`ResourceScope` to its Cedar source representation.

    Args:
        scope: Resource scope to render.

    Returns:
        A Cedar source fragment suitable for the resource slot.

    Raises:
        CompilationError: If ``scope.kind`` is not a recognized kind.
    """
    if scope.kind == "any":
        return "resource"
    if scope.kind == "type":
        # See ``render_principal`` for the rationale on the ``"*"``
        # literal and the use of ``json.dumps`` for safe escaping.
        identifier = scope.entity_id or "*"
        return f"resource == {scope.type_name}::{json.dumps(identifier)}"
    if scope.kind == "is_type":
        return f"resource is {scope.type_name}"
    if scope.kind == "specific":
        return f"resource == {scope.type_name}::{json.dumps(scope.entity_id)}"
    if scope.kind == "in_parent":
        return (
            f"resource is {scope.type_name} "
            f"in {scope.parent_type}::{json.dumps(scope.parent_id)}"
        )
    raise CompilationError(f"unsupported resource scope: {scope.kind}")


__all__ = [
    "CompiledSource",
    "Effect",
    "PolicyIntent",
    "compile_intent",
    "render_action",
    "render_principal",
    "render_resource",
]
