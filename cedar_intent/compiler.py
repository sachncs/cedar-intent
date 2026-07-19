"""Deterministic Cedar compiler.

A :class:`PolicyIntent` is the typed intermediate representation produced
by a generator. The compiler walks the intent and emits Cedar source text
without any LLM involvement. The result is the only place Cedar syntax is
constructed.
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

    Attributes:
        id: Stable intent identifier.
        requirement_id: Identifier of the originating requirement.
        effect: ``"permit"`` or ``"forbid"``.
        principal: Scope applied to the principal slot.
        action: Scope applied to the action slot.
        resource: Scope applied to the resource slot.
        when_clauses: Optional list of ``when`` clauses.
        unless_clauses: Optional list of ``unless`` clauses.
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
    """Render a :class:`PrincipalScope` to its Cedar source representation."""
    if scope.kind == "any":
        return "principal"
    if scope.kind == "type":
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
    """Render an :class:`ActionScope` to its Cedar source representation."""
    if scope.kind == "any":
        return "action"
    namespace_prefix = f"{scope.namespace}::" if scope.namespace else ""
    if scope.kind == "named":
        return f"action == {namespace_prefix}Action::{json.dumps(scope.name)}"
    if scope.kind == "in_group":
        return f"action in {namespace_prefix}Action::{json.dumps(scope.group)}"
    raise CompilationError(f"unsupported action scope: {scope.kind}")


def render_resource(scope: ResourceScope) -> str:
    """Render a :class:`ResourceScope` to its Cedar source representation."""
    if scope.kind == "any":
        return "resource"
    if scope.kind == "type":
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
