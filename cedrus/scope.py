"""Scope definitions for policy principal, action, and resource triples.

Scopes are explicit objects so the LLM proposal and the deterministic
compiler agree on the exact shape of an authorization request. Each
slot of a Cedar policy (``principal``, ``action``, ``resource``) is
backed by a corresponding scope class, and ``when``/``unless`` clauses
are carried as :class:`Clause` instances.

Why a class hierarchy and not a string union
--------------------------------------------

Cedar's syntax for principal, action, and resource is rich: each
slot accepts ``any``, a fully qualified entity reference, an ``is``
membership test, an ``in`` group/parent reference, and a small set
of named kinds. Encoding these as strings makes validation, linting,
and namespace resolution difficult; encoding them as objects makes
each kind a discrete, type-checked branch in the compiler and the
generator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .error import ScopeFault

Expression = str | bool | int | float | dict[str, Any] | list[Any]


@dataclass(frozen=True, slots=True)
class Principal:
    """Scope applied to the ``principal`` slot of a Cedar policy.

    Attributes:
        kind: One of ``"any"``, ``"type"``, ``"specific"``, ``"in_group"``,
            or ``"is_type"``.
        type_name: Entity type name (for ``type``, ``specific``, ``is_type``).
        entity_id: Entity id (for ``specific``).
        group_type: Group entity type (for ``in_group``).
        group_id: Group entity id (for ``in_group``).
    """

    kind: Literal["any", "type", "specific", "in_group", "is_type"] = "any"
    type_name: str | None = None
    entity_id: str | None = None
    group_type: str | None = None
    group_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind == "any":
            return
        if self.kind in {"type", "is_type"} and not self.type_name:
            raise ScopeFault(f"{self.kind!r} principal requires type_name")
        if self.kind == "specific":
            if not self.type_name or not self.entity_id:
                raise ScopeFault("'specific' principal requires type_name and entity_id")
        if self.kind == "in_group":
            if not self.group_type or not self.group_id:
                raise ScopeFault("'in_group' principal requires group_type and group_id")


@dataclass(frozen=True, slots=True)
class Action:
    """Scope applied to the ``action`` slot of a Cedar policy.

    Attributes:
        kind: One of ``"any"``, ``"named"``, or ``"in_group"``.
        name: Action name (for ``named``).
        group: Action group (for ``in_group``).
        namespace: Namespace prefix applied at compile time.
    """

    kind: Literal["any", "named", "in_group"] = "any"
    name: str | None = None
    group: str | None = None
    namespace: str | None = None

    def __post_init__(self) -> None:
        if self.kind == "any":
            return
        if self.kind == "named" and not self.name:
            raise ScopeFault("'named' action requires name")
        if self.kind == "in_group" and not self.group:
            raise ScopeFault("'in_group' action requires group")


@dataclass(frozen=True, slots=True)
class Resource:
    """Scope applied to the ``resource`` slot of a Cedar policy.

    Attributes:
        kind: One of ``"any"``, ``"type"``, ``"specific"``, ``"in_parent"``, or ``"is_type"``.
        type_name: Entity type name (for ``type``, ``specific``, ``is_type``, ``in_parent``).
        entity_id: Entity id (for ``specific``).
        parent_type: Parent entity type (for ``in_parent``).
        parent_id: Parent entity id (for ``in_parent``).
    """

    kind: Literal["any", "type", "specific", "in_parent", "is_type"] = "any"
    type_name: str | None = None
    entity_id: str | None = None
    parent_type: str | None = None
    parent_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind == "any":
            return
        if self.kind in {"type", "is_type"} and not self.type_name:
            raise ScopeFault(f"{self.kind!r} resource requires type_name")
        if self.kind == "specific":
            if not self.type_name or not self.entity_id:
                raise ScopeFault("'specific' resource requires type_name and entity_id")
        if self.kind == "in_parent":
            if not self.type_name or not self.parent_type or not self.parent_id:
                raise ScopeFault(
                    "'in_parent' resource requires type_name, parent_type, and parent_id"
                )


@dataclass(frozen=True, slots=True)
class Clause:
    """A single ``when`` or ``unless`` clause carried by a draft.

    Attributes:
        body: Cedar expression body.
        attributes: Optional attribute bindings referenced by ``body``.
    """

    body: str
    attributes: dict[str, Expression] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.body or not self.body.strip():
            raise ScopeFault("condition clause body must be non-empty")


__all__ = [
    "Action",
    "Clause",
    "Expression",
    "Principal",
    "Resource",
]


# Codec helpers (merged from scope_json.py)

def principal_scope_to_dict(scope: Principal | None) -> dict[str, Any] | None:
    """Serialize a :class:`Principal` to a JSON-friendly dict.

    Args:
        scope: Principal scope, or ``None``.

    Returns:
        A plain ``dict`` mirroring the scope's fields, or ``None`` when
        the input is ``None``.
    """
    if scope is None:
        return None
    return {
        "kind": scope.kind,
        "type_name": scope.type_name,
        "entity_id": scope.entity_id,
        "group_type": scope.group_type,
        "group_id": scope.group_id,
    }


def principal_scope_from_dict(data: dict[str, Any] | None) -> Principal | None:
    """Deserialize a :class:`Principal` from a JSON-friendly dict.

    Args:
        data: Mapping previously produced by
            :func:`principal_scope_to_dict`, or ``None``.

    Returns:
        The reconstructed :class:`Principal`, or ``None`` when
        ``data`` is ``None``.
    """
    if data is None:
        return None
    return Principal(
        kind=data.get("kind", "any"),
        type_name=data.get("type_name") or None,
        entity_id=data.get("entity_id") or None,
        group_type=data.get("group_type") or None,
        group_id=data.get("group_id") or None,
    )


def action_scope_to_dict(scope: Action | None) -> dict[str, Any] | None:
    """Serialize an :class:`Action` to a JSON-friendly dict.

    Args:
        scope: Action scope, or ``None``.

    Returns:
        A plain ``dict`` mirroring the scope's fields, or ``None``.
    """
    if scope is None:
        return None
    return {
        "kind": scope.kind,
        "name": scope.name,
        "group": scope.group,
        "namespace": scope.namespace,
    }


def action_scope_from_dict(data: dict[str, Any] | None) -> Action | None:
    """Deserialize an :class:`Action` from a JSON-friendly dict.

    Args:
        data: Mapping previously produced by
            :func:`action_scope_to_dict`, or ``None``.

    Returns:
        The reconstructed :class:`Action`, or ``None``.
    """
    if data is None:
        return None
    return Action(
        kind=data.get("kind", "any"),
        name=data.get("name") or None,
        group=data.get("group") or None,
        namespace=data.get("namespace") or None,
    )


def resource_scope_to_dict(scope: Resource | None) -> dict[str, Any] | None:
    """Serialize a :class:`Resource` to a JSON-friendly dict.

    Args:
        scope: Resource scope, or ``None``.

    Returns:
        A plain ``dict`` mirroring the scope's fields, or ``None``.
    """
    if scope is None:
        return None
    return {
        "kind": scope.kind,
        "type_name": scope.type_name,
        "entity_id": scope.entity_id,
        "parent_type": scope.parent_type,
        "parent_id": scope.parent_id,
    }


def resource_scope_from_dict(data: dict[str, Any] | None) -> Resource | None:
    """Deserialize a :class:`Resource` from a JSON-friendly dict.

    Args:
        data: Mapping previously produced by
            :func:`resource_scope_to_dict`, or ``None``.

    Returns:
        The reconstructed :class:`Resource`, or ``None``.
    """
    if data is None:
        return None
    return Resource(
        kind=data.get("kind", "any"),
        type_name=data.get("type_name") or None,
        entity_id=data.get("entity_id") or None,
        parent_type=data.get("parent_type") or None,
        parent_id=data.get("parent_id") or None,
    )


def condition_clauses_to_list(
    clauses: tuple[Clause, ...],
) -> list[dict[str, Any]]:
    """Serialize a tuple of condition clauses to a JSON list."""
    return [{"body": clause.body, "attributes": dict(clause.attributes)} for clause in clauses]


def condition_clauses_from_list(
    data: list[dict[str, Any]] | None,
) -> tuple[Clause, ...]:
    """Deserialize a JSON list back into a tuple of condition clauses.

    Accepts both the canonical shape
    (``[{"body": "...", "attributes": {...}}, ...]``) and the legacy
    short form (``["body string", ...]``) for backward compatibility.
    """
    if not data:
        return ()
    clauses: list[Clause] = []
    for item in data:
        if isinstance(item, str):
            clauses.append(Clause(body=item))
        elif isinstance(item, dict) and "body" in item:
            attrs = item.get("attributes") or {}
            clauses.append(
                Clause(
                    body=item["body"],
                    attributes=dict(attrs) if isinstance(attrs, dict) else {},
                )
            )
    return tuple(clauses)


__all__ = [
    "Action",
    "Clause",
    "Expression",
    "Principal",
    "Resource",
    "action_scope_from_dict",
    "action_scope_to_dict",
    "condition_clauses_from_list",
    "condition_clauses_to_list",
    "principal_scope_from_dict",
    "principal_scope_to_dict",
    "resource_scope_from_dict",
    "resource_scope_to_dict",
]

