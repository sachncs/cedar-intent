"""Scope definitions for policy principal, action, and resource triples.

Scopes are explicit objects so the LLM proposal and the deterministic
compiler agree on the exact shape of an authorization request. Each
slot of a Cedar policy (``principal``, ``action``, ``resource``) is
backed by a corresponding scope class, and ``when``/``unless`` clauses
are carried as :class:`ConditionClause` instances.

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

from .errors import ScopeError

Expression = str | bool | int | float | dict[str, Any] | list[Any]


@dataclass(frozen=True, slots=True)
class PrincipalScope:
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
            raise ScopeError(f"{self.kind!r} principal requires type_name")
        if self.kind == "specific":
            if not self.type_name or not self.entity_id:
                raise ScopeError("'specific' principal requires type_name and entity_id")
        if self.kind == "in_group":
            if not self.group_type or not self.group_id:
                raise ScopeError("'in_group' principal requires group_type and group_id")


@dataclass(frozen=True, slots=True)
class ActionScope:
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
            raise ScopeError("'named' action requires name")
        if self.kind == "in_group" and not self.group:
            raise ScopeError("'in_group' action requires group")


@dataclass(frozen=True, slots=True)
class ResourceScope:
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
            raise ScopeError(f"{self.kind!r} resource requires type_name")
        if self.kind == "specific":
            if not self.type_name or not self.entity_id:
                raise ScopeError("'specific' resource requires type_name and entity_id")
        if self.kind == "in_parent":
            if not self.type_name or not self.parent_type or not self.parent_id:
                raise ScopeError(
                    "'in_parent' resource requires type_name, parent_type, and parent_id"
                )


@dataclass(frozen=True, slots=True)
class ConditionClause:
    """A single ``when`` or ``unless`` clause carried by a draft.

    Attributes:
        body: Cedar expression body.
        attributes: Optional attribute bindings referenced by ``body``.
    """

    body: str
    attributes: dict[str, Expression] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.body or not self.body.strip():
            raise ScopeError("condition clause body must be non-empty")


__all__ = [
    "ActionScope",
    "ConditionClause",
    "Expression",
    "PrincipalScope",
    "ResourceScope",
]
