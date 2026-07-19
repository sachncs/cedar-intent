"""JSON serialization for :mod:`cedar_intent.scopes` objects.

Both the storage layer and the verification layer need to round-trip
typed scope objects to and from JSON. This module centralizes the
encoding and decoding so the two layers agree on the wire format
and so future additions to the scope classes only require a single
update.

Round-trip rules
----------------

* ``null`` decodes back to ``None``.
* Missing optional fields decode to ``None``.
* Empty optional strings decode to ``None`` (so the SQL ``IS NULL``
  check works as expected).
* ``when``/``unless`` clauses lose their ``attributes`` map on
  deserialization; the body alone is sufficient for verification.

The helpers are stateless and safe to call from any thread.
"""

from __future__ import annotations

from typing import Any

from .scopes import ActionScope, ConditionClause, PrincipalScope, ResourceScope


def principal_scope_to_dict(scope: PrincipalScope | None) -> dict[str, Any] | None:
    """Serialize a :class:`PrincipalScope` to a JSON-friendly dict.

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


def principal_scope_from_dict(data: dict[str, Any] | None) -> PrincipalScope | None:
    """Deserialize a :class:`PrincipalScope` from a JSON-friendly dict.

    Args:
        data: Mapping previously produced by
            :func:`principal_scope_to_dict`, or ``None``.

    Returns:
        The reconstructed :class:`PrincipalScope`, or ``None`` when
        ``data`` is ``None``.
    """
    if data is None:
        return None
    return PrincipalScope(
        kind=data.get("kind", "any"),
        type_name=data.get("type_name") or None,
        entity_id=data.get("entity_id") or None,
        group_type=data.get("group_type") or None,
        group_id=data.get("group_id") or None,
    )


def action_scope_to_dict(scope: ActionScope | None) -> dict[str, Any] | None:
    """Serialize an :class:`ActionScope` to a JSON-friendly dict.

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


def action_scope_from_dict(data: dict[str, Any] | None) -> ActionScope | None:
    """Deserialize an :class:`ActionScope` from a JSON-friendly dict.

    Args:
        data: Mapping previously produced by
            :func:`action_scope_to_dict`, or ``None``.

    Returns:
        The reconstructed :class:`ActionScope`, or ``None``.
    """
    if data is None:
        return None
    return ActionScope(
        kind=data.get("kind", "any"),
        name=data.get("name") or None,
        group=data.get("group") or None,
        namespace=data.get("namespace") or None,
    )


def resource_scope_to_dict(scope: ResourceScope | None) -> dict[str, Any] | None:
    """Serialize a :class:`ResourceScope` to a JSON-friendly dict.

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


def resource_scope_from_dict(data: dict[str, Any] | None) -> ResourceScope | None:
    """Deserialize a :class:`ResourceScope` from a JSON-friendly dict.

    Args:
        data: Mapping previously produced by
            :func:`resource_scope_to_dict`, or ``None``.

    Returns:
        The reconstructed :class:`ResourceScope`, or ``None``.
    """
    if data is None:
        return None
    return ResourceScope(
        kind=data.get("kind", "any"),
        type_name=data.get("type_name") or None,
        entity_id=data.get("entity_id") or None,
        parent_type=data.get("parent_type") or None,
        parent_id=data.get("parent_id") or None,
    )


def condition_clauses_to_list(
    clauses: tuple[ConditionClause, ...],
) -> list[dict[str, Any]]:
    """Serialize a tuple of condition clauses to a JSON list."""
    return [{"body": clause.body, "attributes": dict(clause.attributes)} for clause in clauses]


def condition_clauses_from_list(
    data: list[dict[str, Any]] | None,
) -> tuple[ConditionClause, ...]:
    """Deserialize a JSON list back into a tuple of condition clauses."""
    if not data:
        return ()
    return tuple(ConditionClause(body=item["body"]) for item in data if "body" in item)


__all__ = [
    "action_scope_from_dict",
    "action_scope_to_dict",
    "condition_clauses_from_list",
    "condition_clauses_to_list",
    "principal_scope_from_dict",
    "principal_scope_to_dict",
    "resource_scope_from_dict",
    "resource_scope_to_dict",
]
