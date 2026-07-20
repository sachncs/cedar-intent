"""Cedar schema wrapper.

The schema is the authority over entity types, actions, attributes,
and context. It is required both at compile time (to validate a
proposal) and at runtime (for authorization decisions). cedar-intent
wraps ``cedarpy`` to provide a single, typed entrypoint.

Why an eager handle
------------------

The cedarpy :class:`Schema` handle is constructed eagerly in
``__post_init__`` so any malformed schema raises :class:`ValidationError`
the moment the :class:`CedarSchema` is built, rather than at the
first downstream call. This makes schema errors surface at the CLI or
API boundary and prevents a half-constructed :class:`CedarSchema`
from leaking into the rest of the pipeline.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cedarpy import Schema

from .errors import ValidationError


@dataclass(frozen=True, slots=True)
class CedarSchema:
    """Parsed Cedar JSON schema.

    Attributes:
        source: The original JSON schema as a mapping.
        handle: The parsed ``cedarpy.Schema`` ready for validation calls.
    """

    source: Mapping[str, Any]
    handle: Schema = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.source, Mapping) or not self.source:
            raise ValidationError(("schema must be a non-empty Cedar JSON object",), "")
        try:
            object.__setattr__(
                self,
                "handle",
                Schema.from_json_str(json.dumps(dict(self.source), sort_keys=True)),
            )
        except (TypeError, ValueError) as error:
            raise ValidationError((f"invalid Cedar JSON schema: {error}",), "") from error

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> CedarSchema:
        """Build a :class:`CedarSchema` from a JSON-like mapping.

        Args:
            mapping: Cedar JSON schema expressed as nested mappings and lists.

        Returns:
            A fully parsed :class:`CedarSchema`.

        Raises:
            ValidationError: If the mapping cannot be parsed by Cedar.
        """
        normalized = json.loads(json.dumps(mapping, sort_keys=True))
        return cls(source=normalized)

    @classmethod
    def from_json_file(cls, path: Path) -> CedarSchema:
        """Build a :class:`CedarSchema` from a Cedar JSON schema file.

        Args:
            path: Path to a Cedar JSON schema file.

        Returns:
            A fully parsed :class:`CedarSchema`.

        Raises:
            ValidationError: If the file is missing, unreadable, or invalid.
        """
        if not path.exists() or not path.is_file():
            raise ValidationError((f"schema file not found: {path}",), "")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValidationError((f"schema file is not valid JSON: {error}",), "") from error
        if not isinstance(data, Mapping):
            raise ValidationError((f"schema file must contain a JSON object: {path}",), "")
        return cls.from_mapping(data)

    def entity_type_names(self) -> set[str]:
        """Return the set of fully qualified entity type names declared in the schema."""
        names: set[str] = set()
        for namespace, declaration in self.source.items():
            if not isinstance(namespace, str) or not isinstance(declaration, Mapping):
                continue
            entity_types = declaration.get("entityTypes", {})
            if not isinstance(entity_types, Mapping):
                continue
            for type_name in entity_types:
                if isinstance(type_name, str):
                    names.add(_qualify(namespace, type_name))
        return names

    def action_names(self) -> set[tuple[str, str]]:
        """Return the set of ``(namespace, action_id)`` pairs declared in the schema.

        Namespace and action identifier are returned as a tuple so the
        verifier can distinguish ``hr::view`` from ``finance::view``.
        """
        names: set[tuple[str, str]] = set()
        for namespace, declaration in self.source.items():
            if not isinstance(namespace, str) or not isinstance(declaration, Mapping):
                continue
            actions = declaration.get("actions", {})
            if not isinstance(actions, Mapping):
                continue
            for action_name in actions:
                if isinstance(action_name, str):
                    names.add((namespace, action_name))
        return names

    def action_members(
        self, namespace: str, action_id: str
    ) -> tuple[str, ...]:
        """Return the member action identifiers of the named action group.

        Action groups are themselves Cedar actions of kind ``Action``
        that contain a ``members`` array of action identifiers. This
        helper extracts that array when present; an empty tuple is
        returned when the action is not a group or has no members.

        Args:
            namespace: Namespace owning the action.
            action_id: Action identifier (group name).

        Returns:
            Tuple of member action identifiers (unqualified).
        """
        declaration = self.source.get(namespace, {})
        if not isinstance(declaration, Mapping):
            return ()
        actions = declaration.get("actions", {})
        if not isinstance(actions, Mapping):
            return ()
        group = actions.get(action_id)
        if not isinstance(group, Mapping):
            return ()
        members = group.get("members")
        if not isinstance(members, list):
            return ()
        return tuple(str(member) for member in members)

    def actions_by_namespace(
        self,
    ) -> Mapping[str, Mapping[str, tuple[str, ...]]]:
        """Return a mapping ``{namespace: {action_id: (member_ids)}}``.

        Built once per call. The verifier uses this to expand
        ``action in Action::"group"`` into the group's member actions
        during coverage analysis.
        """
        result: dict[str, dict[str, tuple[str, ...]]] = {}
        for namespace, declaration in self.source.items():
            if not isinstance(namespace, str) or not isinstance(declaration, Mapping):
                continue
            actions = declaration.get("actions", {})
            if not isinstance(actions, Mapping):
                continue
            inner: dict[str, tuple[str, ...]] = {}
            for action_name, action_def in actions.items():
                if isinstance(action_name, str) and isinstance(action_def, Mapping):
                    members = action_def.get("members")
                    if isinstance(members, list):
                        inner[action_name] = tuple(str(m) for m in members)
            if inner:
                result[namespace] = inner
        return result

    def namespace_of(self, type_name: str) -> str | None:
        """Return the namespace prefix for a fully qualified type name."""
        if "::" not in type_name:
            return None
        namespace, _, _ = type_name.partition("::")
        return namespace or None

    def qualify_type_name(self, type_name: str | None) -> str | None:
        """Return the fully qualified Cedar type name.

        Args:
            type_name: Unqualified or qualified type name.

        Returns:
            The qualified name when ``type_name`` matches exactly one
            namespace in the schema, or the original value if it is already
            qualified or does not match any namespace.
        """
        if type_name is None:
            return None
        if "::" in type_name:
            return type_name
        matches: list[str] = []
        for namespace, declaration in self.source.items():
            if not isinstance(namespace, str) or not isinstance(declaration, Mapping):
                continue
            entity_types = declaration.get("entityTypes", {})
            if isinstance(entity_types, Mapping) and type_name in entity_types:
                matches.append(_qualify(namespace, type_name))
        if len(matches) == 1:
            return matches[0]
        return type_name


def _qualify(namespace: str, name: str) -> str:
    """Join ``namespace`` and ``name`` with the Cedar namespace separator."""
    return f"{namespace}::{name}" if namespace else name


__all__ = ["CedarSchema"]
