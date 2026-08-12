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
from typing import Any, Literal

from .error import Compile
from .need import slugify
from .scope import Action, Clause, Principal, Resource, Scope

Effect = Literal["permit", "forbid"]


@dataclass(frozen=True, slots=True)
class Intent:
    """Typed authorization intent for one policy.

    An intent is the contract between a generator (human or LLM) and the
    deterministic compiler. A valid intent must round-trip through
    :class:`Compiler` to produce Cedar that validates against the
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

    def compile(self) -> Source:
        """Compile this intent to Cedar source text.

        Delegates to :class:`Compiler`. Subclass :class:`Compiler` to
        customize the rendering strategy.
        """
        return Compiler().compile(self)

    def to_dict(self) -> dict[str, object]:
        """Return the canonical wire-format dict for this intent.

        Accepts both the canonical ``when_clauses``/``unless_clauses``
        shape and the legacy short form (``when``/``unless`` carrying
        a list of body strings).
        """
        return {
            "id": self.id,
            "requirement_id": self.requirement_id,
            "effect": self.effect,
            "principal": self.principal.to_dict(),
            "action": self.action.to_dict(),
            "resource": self.resource.to_dict(),
            "when_clauses": [c.to_dict() for c in self.when_clauses],
            "unless_clauses": [c.to_dict() for c in self.unless_clauses],
            "notes": (
                self.notes.to_dict()
                if hasattr(self.notes, "to_dict")
                else dict(self.notes)
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> Intent:
        """Reconstruct an Intent from its canonical wire-format dict.

        Accepts both the canonical ``when_clauses``/``unless_clauses``
        shape and the legacy short form (``when``/``unless`` carrying a
        list of body strings) so rows stored by earlier cedrus
        versions still load.
        """
        principal_data = data.get("principal")
        action_data = data.get("action")
        resource_data = data.get("resource")
        when_raw = data.get("when_clauses", data.get("when"))
        unless_raw = data.get("unless_clauses", data.get("unless"))
        principal = (
            Principal.from_dict(principal_data)
            if isinstance(principal_data, dict)
            else Principal()
        )
        action = (
            Action.from_dict(action_data) if isinstance(action_data, dict) else Action()
        )
        resource = (
            Resource.from_dict(resource_data)
            if isinstance(resource_data, dict)
            else Resource()
        )
        when_clauses = (
            tuple(Clause.from_dict(dict(item)) for item in when_raw)
            if isinstance(when_raw, list)
            else ()
        )
        unless_clauses = (
            tuple(Clause.from_dict(dict(item)) for item in unless_raw)
            if isinstance(unless_raw, list)
            else ()
        )
        notes_value = data.get("notes", {}) or {}
        notes = notes_value if isinstance(notes_value, dict) else {}
        return cls(
            id=str(data.get("id", "")),
            requirement_id=str(data.get("requirement_id", "")),
            effect=str(data.get("effect", "permit")),
            principal=principal,
            action=action,
            resource=resource,
            when_clauses=when_clauses,
            unless_clauses=unless_clauses,
            notes=notes,
        )

    @classmethod
    def parse(
        cls,
        data: Any,
        *,
        need: Any = None,
        principal: Principal | None = None,
        action: Action | None = None,
        resource: Resource | None = None,
        generator_name: str = "",
    ) -> Intent:
        """Parse a dict into a typed :class:`Intent`.

        Polymorphic on the shape of ``data``:

        * LLM / JSON shape (CLI, generator): data has ``"effect"`` and
          nested ``"principal"`` / ``"action"`` / ``"resource"`` /
          ``"when"`` / ``"unless"`` / ``"notes"`` keys. ``need``,
          ``principal``, ``action``, ``resource`` and
          ``generator_name`` are used as defaults for missing fields.
        * SQL shape (storage hydration): data has ``"intent"`` /
          ``"principal"`` / ``"action"`` / ``"resource"`` /
          ``"when_clauses"`` / ``"unless_clauses"`` / ``"notes"``
          keys (the assembled JOIN result). The kwargs are ignored.

        Args:
            data: ``intent`` sub-dict from the model response (LLM
                shape) or assembled dict of SQL rows (SQL shape).
            need: Default :class:`~cedrus.need.Need` used by the LLM
                path to derive the intent identifier and
                ``requirement_id``.
            principal: Default :class:`Principal` for the LLM path.
            action: Default :class:`Action` for the LLM path.
            resource: Default :class:`Resource` for the LLM path.
            generator_name: Generator name recorded in
                ``notes["generator"]`` (LLM path only).

        Returns:
            A fully typed :class:`Intent`.

        Raises:
            Compile: When ``data`` is not a dict, ``effect`` is not
                ``"permit"`` / ``"forbid"``, or the data shape is
                neither LLM nor SQL.
        """
        if not isinstance(data, dict):
            raise Compile("intent must be a JSON object")
        if "effect" in data:
            return cls._parse_llm_shape(
                data,
                need=need,
                principal=principal,
                action=action,
                resource=resource,
                generator_name=generator_name,
            )
        if "intent" in data:
            return cls._parse_sql_shape(data)
        raise Compile(
            "intent data has neither 'effect' (LLM shape) nor 'intent' "
            "(SQL shape); cannot determine which parser to use"
        )

    @classmethod
    def _parse_llm_shape(
        cls,
        data: dict[str, Any],
        *,
        need: Any,
        principal: Principal | None,
        action: Action | None,
        resource: Resource | None,
        generator_name: str,
    ) -> Intent:
        """Parse the LLM / JSON shape produced by generators."""
        effect = data.get("effect")
        if effect not in {"permit", "forbid"}:
            raise Compile(f"intent has invalid effect {effect!r}")
        parsed_principal = Scope.parse(data.get("principal") or {}) or principal or Principal()
        parsed_action = Scope.parse(data.get("action") or {}) or action or Action()
        parsed_resource = Scope.parse(data.get("resource") or {}) or resource or Resource()
        when_clauses = Clause.normalize(data.get("when") or [])
        unless_clauses = Clause.normalize(data.get("unless") or [])
        if need is not None:
            intent_id = f"{need.domain}-{slugify(need.id)}"
            requirement_id = need.id
        else:
            intent_id = str(data.get("id", ""))
            requirement_id = str(data.get("requirement_id", ""))
        return cls(
            id=intent_id,
            requirement_id=requirement_id,
            effect=effect,
            principal=parsed_principal,
            action=parsed_action,
            resource=parsed_resource,
            when_clauses=when_clauses,
            unless_clauses=unless_clauses,
            notes={"generator": generator_name},
        )

    @classmethod
    def _parse_sql_shape(cls, data: dict[str, Any]) -> Intent:
        """Parse the SQL-shape dict assembled by the storage layer."""
        intent_row = data["intent"]
        principal = Principal.parse(data["principal"])
        action = Action.parse(data["action"])
        resource = Resource.parse(data["resource"])
        when_clauses = tuple(Clause.parse(c) for c in data.get("when_clauses", ()))
        unless_clauses = tuple(Clause.parse(c) for c in data.get("unless_clauses", ()))
        notes: dict[str, str] = {
            n["key"]: n["value"] for n in data.get("notes", ())
        }
        return cls(
            id=intent_row["id"],
            requirement_id=intent_row["requirement_id"],
            effect=intent_row["effect"],
            principal=principal,
            action=action,
            resource=resource,
            when_clauses=when_clauses,
            unless_clauses=unless_clauses,
            notes=notes,
        )

    def to_data(self) -> dict[str, Any]:
        """Return the multi-row dict for this :class:`Intent`.

        Includes the row for the ``intents`` table, the row for
        ``principals`` / ``actions`` / ``resources`` (from the typed
        sub-objects), and the ordered ``intent_when_clauses`` /
        ``intent_unless_clauses`` / ``intent_notes`` rows.

        Returns:
            A dict with ``"intents"`` and lists of typed-object /
            composition rows ready for the multi-table write.
        """
        intent_row = {
            "id": self.id,
            "effect": self.effect,
            "requirement_id": self.requirement_id,
            "principal_id": self.principal.id,
            "action_id": self.action.id,
            "resource_id": self.resource.id,
        }
        return {
            "intents": intent_row,
            "principals": [self.principal.to_data()],
            "actions": [self.action.to_data()],
            "resources": [self.resource.to_data()],
            "intent_when_clauses": [
                {"intent_id": self.id, "position": i, "clause_id": c.id}
                for i, c in enumerate(self.when_clauses)
            ],
            "intent_unless_clauses": [
                {"intent_id": self.id, "position": i, "clause_id": c.id}
                for i, c in enumerate(self.unless_clauses)
            ],
            "intent_notes": [
                {"intent_id": self.id, "key": k, "value": v}
                for k, v in self.notes.items()
            ],
            "when_clause_rows": [c.to_data() for c in self.when_clauses],
            "unless_clause_rows": [c.to_data() for c in self.unless_clauses],
        }


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
    "Compiler",
]
