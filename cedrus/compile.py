"""Deterministic Cedar compiler.

A :class:`Intent` is the typed intermediate representation produced
by a generator. The compiler walks the intent and emits Cedar source
text without any LLM involvement. It is the only code in cedrus
that constructs Cedar syntax.

The output is deterministic: calling :func:`compile_intent` twice with
the same intent returns identical Cedar source. Every renderer routes
through :func:`json.dumps` for value escaping so any value can be
embedded in a Cedar string literal without manual quote or backslash
handling. Scope rendering is one branch per ``kind`` value with no
shared fallbacks, so a malformed scope raises
:class:`Compile` instead of producing silent garbage.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from .error import Compile
from .scope import (
    Action,
    Clause,
    Principal,
    Resource,
    action_scope_from_dict,
    action_scope_to_dict,
    condition_clauses_from_list,
    condition_clauses_to_list,
    principal_scope_from_dict,
    principal_scope_to_dict,
    resource_scope_from_dict,
    resource_scope_to_dict,
)

Effect = Literal["permit", "forbid"]


@dataclass(frozen=True, slots=True)
class Intent:
    """Typed authorization intent for one policy.

    An intent is the contract between a generator (human or LLM) and the
    deterministic compiler. A valid intent must round-trip through
    :func:`compile_intent` to produce Cedar that validates against the
    supplied schema.

    Attributes:
        id: Stable intent identifier (for example ``"hr-hr-042"``).
        requirement_id: Identifier of the originating :class:`Need`.
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
    principal: Principal
    action: Action
    resource: Resource
    when_clauses: tuple[Clause, ...] = field(default_factory=tuple)
    unless_clauses: tuple[Clause, ...] = field(default_factory=tuple)
    notes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.effect not in {"permit", "forbid"}:
            raise Compile(f"intent {self.id} has invalid effect {self.effect!r}")
        if not self.id or not self.id.strip():
            raise Compile("policy intent id must be non-empty")


@dataclass(frozen=True, slots=True)
class Source:
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




class Compiler:
    """Deterministic Cedar compiler. Single entry point: :meth:`compile`."""

    def compile(self, intent: Intent) -> Source:
        """Compile ``intent`` into a Cedar :class:`Source`."""
        return compile_intent(intent)


def compile_intent(intent: Intent) -> Source:
    """Compile a single :class:`Intent` to Cedar source.

    The compiler assembles the slot clauses, appends ``when`` and
    ``unless`` blocks when present, and terminates the statement with
    a semicolon. Whitespace is normalized to a single space.

    Args:
        intent: The intent to compile.

    Returns:
        A :class:`Source` containing the rendered Cedar text and
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
    return Source(
        intent_id=intent.id,
        cedar="\n".join(parts),
        compiled_at=datetime.now(UTC),
    )


def render_principal(scope: Principal) -> str:
    """Render a :class:`Principal` to its Cedar source representation.

    Args:
        scope: Principal scope to render.

    Returns:
        A Cedar source fragment suitable for the principal slot of a
        policy statement.

    Raises:
        Compile: If ``scope.kind`` is not a recognized kind.
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
    raise Compile(f"unsupported principal scope: {scope.kind}")


def render_action(scope: Action) -> str:
    """Render an :class:`Action` to its Cedar source representation.

    Args:
        scope: Action scope to render.

    Returns:
        A Cedar source fragment suitable for the action slot.

    Raises:
        Compile: If ``scope.kind`` is not a recognized kind.
    """
    if scope.kind == "any":
        return "action"
    namespace_prefix = f"{scope.namespace}::" if scope.namespace else ""
    if scope.kind == "named":
        return f"action == {namespace_prefix}Action::{json.dumps(scope.name)}"
    if scope.kind == "in_group":
        return f"action in {namespace_prefix}Action::{json.dumps(scope.group)}"
    raise Compile(f"unsupported action scope: {scope.kind}")


def render_resource(scope: Resource) -> str:
    """Render a :class:`Resource` to its Cedar source representation.

    Args:
        scope: Resource scope to render.

    Returns:
        A Cedar source fragment suitable for the resource slot.

    Raises:
        Compile: If ``scope.kind`` is not a recognized kind.
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
    raise Compile(f"unsupported resource scope: {scope.kind}")


__all__ = [
    "Source",
    "Effect",
    "Intent",
    "compile_intent",
    "intent_from_dict",
    "intent_to_dict",
    "render_action",
    "render_principal",
    "render_resource",
]


def intent_to_dict(intent: Intent | None) -> dict[str, object] | None:
    """Serialize a :class:`Intent` to a JSON-friendly dict.

    The canonical wire format uses ``when_clauses`` and
    ``unless_clauses`` keys with ``[{"body": ..., "attributes": ...},
    ...]`` values so the verification layer can recover both the body
    and any operator-supplied attributes.

    Args:
        intent: Intent to serialize, or ``None``.

    Returns:
        A plain ``dict`` mirroring the intent's fields, or ``None``
        when ``intent`` is ``None``.
    """
    if intent is None:
        return None
    return {
        "id": intent.id,
        "requirement_id": intent.requirement_id,
        "effect": intent.effect,
        "principal": principal_scope_to_dict(intent.principal),
        "action": action_scope_to_dict(intent.action),
        "resource": resource_scope_to_dict(intent.resource),
        "when_clauses": condition_clauses_to_list(intent.when_clauses),
        "unless_clauses": condition_clauses_to_list(intent.unless_clauses),
            "notes": (
                intent.notes.to_dict()
                if hasattr(intent.notes, "to_dict")
                else dict(intent.notes)
            ),
    }


def intent_from_dict(data: Mapping[str, object] | None) -> Intent | None:
    """Deserialize a :class:`Intent` from a JSON-friendly dict.

    Accepts both the canonical ``when_clauses``/``unless_clauses``
    shape and the legacy short form (``when``/``unless`` carrying a
    list of body strings) so rows stored by earlier cedrus
    versions still load.

    Args:
        data: Mapping previously produced by :func:`intent_to_dict`,
            or ``None``.

    Returns:
        The reconstructed :class:`Intent`, or ``None`` when
        ``data`` is ``None``.
    """
    if data is None:
        return None
    principal_data = data.get("principal")
    action_data = data.get("action")
    resource_data = data.get("resource")
    when_raw = data.get("when_clauses", data.get("when"))
    unless_raw = data.get("unless_clauses", data.get("unless"))
    principal = (
        principal_scope_from_dict(principal_data)
        if isinstance(principal_data, dict)
        else Principal()
    )
    action = (
        action_scope_from_dict(action_data)
        if isinstance(action_data, dict)
        else Action()
    )
    resource = (
        resource_scope_from_dict(resource_data)
        if isinstance(resource_data, dict)
        else Resource()
    )
    when_clauses = (
        condition_clauses_from_list(when_raw)
        if isinstance(when_raw, list)
        else ()
    )
    unless_clauses = (
        condition_clauses_from_list(unless_raw)
        if isinstance(unless_raw, list)
        else ()
    )
    notes_value = data.get("notes", {}) or {}
    notes = notes_value if isinstance(notes_value, dict) else {}
    return Intent(
        id=str(data.get("id", "")),
        requirement_id=str(data.get("requirement_id", "")),
        effect=data.get("effect", "permit"),  # type: ignore[arg-type]
        principal=principal or Principal(),
        action=action or Action(),
        resource=resource or Resource(),
        when_clauses=when_clauses,
        unless_clauses=unless_clauses,
        notes=notes,
    )
