"""Cedar schema wrapper.

The schema is the authority over entity types, actions, attributes, and
context. It is required both at compile time (to validate a proposal) and
at runtime (for authorization decisions). cedar-intent wraps ``cedarpy`` to
provide a single, typed entrypoint.
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
        # Two failure modes are possible when handing the mapping to Cedar:
        # json.dumps raises TypeError when ``source`` contains non-JSON values
        # such as bytes, sets, or custom objects; Schema.from_json_str raises
        # ValueError when the resulting JSON does not match the Cedar schema
        # grammar. Each mode is reported with a distinct message.
        try:
            serialized = json.dumps(dict(self.source), sort_keys=True)
        except TypeError as error:
            raise ValidationError(
                (f"schema contains values that are not JSON-serializable: {error}",),
                "",
            ) from error
        try:
            handle = Schema.from_json_str(serialized)
        except ValueError as error:
            raise ValidationError((f"invalid Cedar JSON schema: {error}",), "") from error
        object.__setattr__(self, "handle", handle)

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

    def action_names(self) -> set[str]:
        """Return the set of action identifiers declared in the schema."""
        names: set[str] = set()
        for namespace, declaration in self.source.items():
            if not isinstance(namespace, str) or not isinstance(declaration, Mapping):
                continue
            actions = declaration.get("actions", {})
            if not isinstance(actions, Mapping):
                continue
            for action_name in actions:
                if isinstance(action_name, str):
                    names.add(action_name)
        return names

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
