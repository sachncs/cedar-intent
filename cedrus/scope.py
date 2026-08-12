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

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .error import ScopeFault
from .utils import generate

Expression = str | bool | int | float | dict[str, Any] | list[Any]


class Scope(ABC):
    """Abstract base for every scope shape.

    Each Cedar policy slot accepts a scope of a specific kind; this
    ABC defines the contract that the four concrete scope types
    (:class:`Principal`, :class:`Action`, :class:`Resource`,
    :class:`Clause`) implement.
    """

    @abstractmethod
    def clause(self) -> str:
        """Return the Cedar source fragment this scope renders to."""

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation of this scope."""

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> Scope:
        """Reconstruct a scope from its JSON-friendly representation."""

    @classmethod
    def parse(cls, data: Any) -> Scope | None:
        """Parse JSON-like data into the right :class:`Scope` subclass.

        Polymorphic entry point that dispatches on the discriminator
        fields documented in the SYSTEM_PROMPT contract:

        * ``parent_type`` or ``parent_id`` → :class:`Resource`
        * ``group_type`` or ``group_id`` → :class:`Principal`
        * ``name`` → :class:`Action`

        :class:`Clause` is not constructed here — callers normalize
        clauses through :meth:`Clause.normalize`. Returns ``None`` for
        ambiguous or invalid data; :class:`Scope` validation failures
        inside :meth:`from_dict` are also swallowed and reported as
        ``None`` so callers can fall back to their own defaults.

        Args:
            data: Raw JSON-like value.

        Returns:
            A typed :class:`Scope` instance, or ``None``.
        """
        if not isinstance(data, dict):
            return None
        try:
            if "parent_type" in data or "parent_id" in data:
                return Resource.from_dict(data)
            if "group_type" in data or "group_id" in data:
                return Principal.from_dict(data)
            if "name" in data:
                return Action.from_dict(data)
        except ScopeFault:
            return None
        return None


def _validate_kind(value: str, allowed: frozenset[str]) -> None:
    """Raise :class:`ScopeFault` if ``value`` is not in ``allowed``."""
    if value not in allowed:
        raise ScopeFault(
            f"invalid kind {value!r}; expected one of {sorted(allowed)}"
        )


def _validate_id(value: str | None, field: str) -> None:
    """Raise :class:`ScopeFault` if ``value`` is empty when required."""
    if value is not None and not value.strip():
        raise ScopeFault(f"{field} must be non-empty when set")


@dataclass(frozen=True, slots=True)
class Principal(Scope):
    """Scope applied to the ``principal`` slot of a Cedar policy.

    Attributes:
        id: Unique identifier (UUID-style ``object_id``).
        kind: One of the ``Principal.VARIETIES`` constants.
        type_name: Entity type name (for ``type``, ``specific``, ``is_type``).
        entity_id: Entity id (for ``specific``).
        group_type: Group entity type (for ``in_group``).
        group_id: Group entity id (for ``in_group``).
    """

    ANY: str = "any"
    TYPE: str = "type"
    SPECIFIC: str = "specific"
    IN_GROUP: str = "in_group"
    IS_TYPE: str = "is_type"
    VARIETIES: frozenset[str] = frozenset({ANY, TYPE, SPECIFIC, IN_GROUP, IS_TYPE})

    id: str = field(default_factory=generate)
    kind: str = ANY
    type_name: str | None = None
    entity_id: str | None = None
    group_type: str | None = None
    group_id: str | None = None

    def __post_init__(self) -> None:
        _validate_kind(self.kind, self.VARIETIES)
        _validate_id(self.type_name, "type_name")
        _validate_id(self.entity_id, "entity_id")
        _validate_id(self.group_type, "group_type")
        _validate_id(self.group_id, "group_id")

    def clause(self) -> str:
        """Render the Cedar fragment for this principal slot."""
        if self.kind == self.ANY:
            return "principal"
        if self.kind == self.SPECIFIC:
            import json

            return f'principal == {self.type_name}::{json.dumps(self.entity_id)}'
        if self.kind == self.TYPE:
            return f"principal == {self.type_name}"
        if self.kind == self.IS_TYPE:
            return f"principal is {self.type_name}"
        # self.kind == self.IN_GROUP
        return f"principal in {self.group_type}::{json.dumps(self.group_id)}"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation of this principal."""
        return {
            "kind": self.kind,
            "type_name": self.type_name,
            "entity_id": self.entity_id,
            "group_type": self.group_type,
            "group_id": self.group_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Principal:
        """Reconstruct a Principal from its JSON-friendly representation."""
        return cls(
            kind=data.get("kind", cls.ANY),
            type_name=data.get("type_name"),
            entity_id=data.get("entity_id"),
            group_type=data.get("group_type"),
            group_id=data.get("group_id"),
        )

    @classmethod
    def parse(cls, row: dict[str, Any]) -> Principal:
        """Build a :class:`Principal` from a SQLite ``principals`` row dict.

        Args:
            row: Dict produced by ``SELECT * FROM principals``.

        Returns:
            The reconstructed :class:`Principal`.
        """
        return cls(
            id=row["id"],
            kind=row["kind"],
            type_name=row["type_name"],
            entity_id=row["entity_id"],
            group_type=row["group_type"],
            group_id=row["group_id"],
        )

    def to_data(self) -> dict[str, Any]:
        """Return the ``principals`` row dict for this :class:`Principal`.

        Returns:
            A dict keyed by ``principals`` column name.
        """
        return {
            "id": self.id,
            "kind": self.kind,
            "type_name": self.type_name,
            "entity_id": self.entity_id,
            "group_type": self.group_type,
            "group_id": self.group_id,
        }


@dataclass(frozen=True, slots=True)
class Action(Scope):
    """Scope applied to the ``action`` slot of a Cedar policy.

    Attributes:
        id: Unique identifier (UUID-style ``object_id``).
        kind: One of the ``Action.VARIETIES`` constants.
        name: Action name (for ``named``).
        group: Action group name (for ``in_group``).
    """

    ANY: str = "any"
    NAMED: str = "named"
    IN_GROUP: str = "in_group"
    VARIETIES: frozenset[str] = frozenset({ANY, NAMED, IN_GROUP})

    id: str = field(default_factory=generate)
    kind: str = ANY
    name: str | None = None
    group: str | None = None

    def __post_init__(self) -> None:
        _validate_kind(self.kind, self.VARIETIES)
        _validate_id(self.name, "name")
        _validate_id(self.group, "group")

    def clause(self) -> str:
        """Render the Cedar fragment for this action slot."""
        if self.kind == self.ANY:
            return "action"
        if self.kind == self.NAMED:
            import json

            return f'action == Action::{json.dumps(self.name)}'
        # self.kind == self.IN_GROUP
        import json

        return f'action in Action::{json.dumps(self.group)}'

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation of this action."""
        return {
            "kind": self.kind,
            "name": self.name,
            "group": self.group,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Action:
        """Reconstruct an Action from its JSON-friendly representation."""
        return cls(
            kind=data.get("kind", cls.ANY),
            name=data.get("name"),
            group=data.get("group"),
        )

    @classmethod
    def parse(cls, row: dict[str, Any]) -> Action:
        """Build an :class:`Action` from a SQLite ``actions`` row dict.

        Args:
            row: Dict produced by ``SELECT * FROM actions``.

        Returns:
            The reconstructed :class:`Action`.
        """
        return cls(
            id=row["id"],
            kind=row["kind"],
            name=row["name"],
            group=row["group"],
        )

    def to_data(self) -> dict[str, Any]:
        """Return the ``actions`` row dict for this :class:`Action`.

        Returns:
            A dict keyed by ``actions`` column name.
        """
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "group": self.group,
        }


@dataclass(frozen=True, slots=True)
class Resource(Scope):
    """Scope applied to the ``resource`` slot of a Cedar policy.

    Attributes:
        id: Unique identifier (UUID-style ``object_id``).
        kind: One of the ``Resource.VARIETIES`` constants.
        type_name: Entity type name (for ``type``, ``specific``, ``is_type``).
        entity_id: Entity id (for ``specific``).
        parent_type: Parent entity type (for ``in_parent``).
        parent_id: Parent entity id (for ``in_parent``).
    """

    ANY: str = "any"
    TYPE: str = "type"
    SPECIFIC: str = "specific"
    IN_PARENT: str = "in_parent"
    IS_TYPE: str = "is_type"
    VARIETIES: frozenset[str] = frozenset({ANY, TYPE, SPECIFIC, IN_PARENT, IS_TYPE})

    id: str = field(default_factory=generate)
    kind: str = ANY
    type_name: str | None = None
    entity_id: str | None = None
    parent_type: str | None = None
    parent_id: str | None = None

    def __post_init__(self) -> None:
        _validate_kind(self.kind, self.VARIETIES)
        _validate_id(self.type_name, "type_name")
        _validate_id(self.entity_id, "entity_id")
        _validate_id(self.parent_type, "parent_type")
        _validate_id(self.parent_id, "parent_id")

    def clause(self) -> str:
        """Render the Cedar fragment for this resource slot."""
        if self.kind == self.ANY:
            return "resource"
        if self.kind == self.SPECIFIC:
            import json

            return f'resource == {self.type_name}::{json.dumps(self.entity_id)}'
        if self.kind == self.TYPE:
            return f"resource == {self.type_name}"
        if self.kind == self.IS_TYPE:
            return f"resource is {self.type_name}"
        # self.kind == self.IN_PARENT
        import json

        return f'resource in {self.parent_type}::{json.dumps(self.parent_id)}'

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation of this resource."""
        return {
            "kind": self.kind,
            "type_name": self.type_name,
            "entity_id": self.entity_id,
            "parent_type": self.parent_type,
            "parent_id": self.parent_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Resource:
        """Reconstruct a Resource from its JSON-friendly representation."""
        return cls(
            kind=data.get("kind", cls.ANY),
            type_name=data.get("type_name"),
            entity_id=data.get("entity_id"),
            parent_type=data.get("parent_type"),
            parent_id=data.get("parent_id"),
        )

    @classmethod
    def parse(cls, row: dict[str, Any]) -> Resource:
        """Build a :class:`Resource` from a SQLite ``resources`` row dict.

        Args:
            row: Dict produced by ``SELECT * FROM resources``.

        Returns:
            The reconstructed :class:`Resource`.
        """
        return cls(
            id=row["id"],
            kind=row["kind"],
            type_name=row["type_name"],
            entity_id=row["entity_id"],
            parent_type=row["parent_type"],
            parent_id=row["parent_id"],
        )

    def to_data(self) -> dict[str, Any]:
        """Return the ``resources`` row dict for this :class:`Resource`.

        Returns:
            A dict keyed by ``resources`` column name.
        """
        return {
            "id": self.id,
            "kind": self.kind,
            "type_name": self.type_name,
            "entity_id": self.entity_id,
            "parent_type": self.parent_type,
            "parent_id": self.parent_id,
        }


@dataclass(frozen=True, slots=True)
class Clause(Scope):
    """A single ``when`` or ``unless`` clause carried by a draft.

    Attributes:
        id: Unique identifier (UUID-style ``object_id``).
        body: Cedar expression body.
        attributes: Optional attribute bindings referenced by ``body``.
    """

    id: str = field(default_factory=generate)
    body: str
    attributes: dict[str, Expression] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.body or not self.body.strip():
            raise ScopeFault("condition clause body must be non-empty")

    def clause(self) -> str:
        """Return the clause body (which IS the Cedar source fragment)."""
        return self.body

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation of this clause."""
        return {
            "body": self.body,
            "attributes": dict(self.attributes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Clause:
        """Reconstruct a Clause from its JSON-friendly representation."""
        attrs_raw = data.get("attributes") or {}
        attrs: dict[str, Expression] = dict(attrs_raw) if isinstance(attrs_raw, dict) else {}
        return cls(body=str(data.get("body", "")), attributes=attrs)

    @classmethod
    def normalize(cls, values: Any) -> tuple[Clause, ...]:
        """Normalize a JSON-friendly value to a tuple of :class:`Clause`.

        Accepts a single string, a list of strings, or ``None`` / any
        non-list value (which returns an empty tuple). Blank entries
        are dropped.

        Args:
            values: ``when`` / ``unless`` payload from the JSON
                response, or a single body string.

        Returns:
            A tuple of :class:`Clause` instances; empty when no
            non-blank strings were supplied.
        """
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            return ()
        return tuple(
            cls(body=v.strip())
            for v in values
            if isinstance(v, str) and v.strip()
        )

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Clause:
        """Build a :class:`Clause` from its SQLite row dict(s).

        ``data`` carries:
        - ``"clauses"``: a single row dict from the ``clauses`` table
        - ``"clause_attributes"``: a list of row dicts from
          ``clause_attributes`` keyed by ``clause_id`` (defaults to
          empty list when there are no attributes)

        Args:
            data: Assembled dict from the SQLite read path.

        Returns:
            The reconstructed :class:`Clause`.
        """
        clause_row = data["clauses"]
        attrs = {
            a["key"]: a["value"]
            for a in data.get("clause_attributes", [])
            if a.get("clause_id") == clause_row["id"]
        }
        return cls(
            id=clause_row["id"],
            body=clause_row["body"],
            attributes=attrs,
        )

    def to_data(self) -> dict[str, Any]:
        """Return the multi-row dict for this :class:`Clause`.

        Returns:
            A dict with ``"clauses"`` (the main row) and
            ``"clause_attributes"`` (one row per attribute key/value).
        """
        return {
            "clauses": {
                "id": self.id,
                "body": self.body,
            },
            "clause_attributes": [
                {"clause_id": self.id, "key": k, "value": v}
                for k, v in self.attributes.items()
            ],
        }


__all__ = [
    "Action",
    "Clause",
    "Expression",
    "Principal",
    "Resource",
    "Scope",
]
