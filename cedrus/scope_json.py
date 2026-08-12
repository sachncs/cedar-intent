"""JSON serialization for :mod:`cedrus.scopes` objects.

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
* ``when_clauses``/``unless_clauses`` arrays carry
  ``{"body": str, "attributes": dict}`` objects so the verification
  layer can recover both the body and any operator-supplied
  attributes.
* The legacy short-form ``when``/``unless`` keys (carrying a list of
  body strings) are still accepted on read for backward compatibility
  with rows stored by earlier cedrus versions, but every
  writer now uses the canonical ``when_clauses``/``unless_clauses``
  shape.

The helpers are stateless and safe to call from any thread.
"""

from __future__ import annotations

from typing import Any

from .compiler import PolicyIntent
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
    """Deserialize a JSON list back into a tuple of condition clauses.

    Accepts both the canonical shape
    (``[{"body": "...", "attributes": {...}}, ...]``) and the legacy
    short form (``["body string", ...]``) for backward compatibility.
    """
    if not data:
        return ()
    clauses: list[ConditionClause] = []
    for item in data:
        if isinstance(item, str):
            clauses.append(ConditionClause(body=item))
        elif isinstance(item, dict) and "body" in item:
            attrs = item.get("attributes") or {}
            clauses.append(
                ConditionClause(
                    body=item["body"],
                    attributes=dict(attrs) if isinstance(attrs, dict) else {},
                )
            )
    return tuple(clauses)


def intent_to_dict(intent: PolicyIntent | None) -> dict[str, Any] | None:
    """Serialize a :class:`PolicyIntent` to a JSON-friendly dict.

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
        "notes": dict(intent.notes),
    }


def intent_from_dict(data: dict[str, Any] | None) -> PolicyIntent | None:
    """Deserialize a :class:`PolicyIntent` from a JSON-friendly dict.

    Accepts both the canonical ``when_clauses``/``unless_clauses``
    shape and the legacy short form (``when``/``unless`` carrying a
    list of body strings) so rows stored by earlier cedrus
    versions still load.

    Args:
        data: Mapping previously produced by :func:`intent_to_dict`,
            or ``None``.

    Returns:
        The reconstructed :class:`PolicyIntent`, or ``None`` when
        ``data`` is ``None``.
    """
    if data is None:
        return None
    when_raw = data.get("when_clauses", data.get("when"))
    unless_raw = data.get("unless_clauses", data.get("unless"))
    principal = principal_scope_from_dict(data.get("principal")) or PrincipalScope()
    action = action_scope_from_dict(data.get("action")) or ActionScope()
    resource = resource_scope_from_dict(data.get("resource")) or ResourceScope()
    when_clauses = condition_clauses_from_list(when_raw)
    unless_clauses = condition_clauses_from_list(unless_raw)
    return PolicyIntent(
        id=str(data.get("id", "")),
        requirement_id=str(data.get("requirement_id", "")),
        effect=data.get("effect", "permit"),
        principal=principal,
        action=action,
        resource=resource,
        when_clauses=when_clauses,
        unless_clauses=unless_clauses,
        notes=dict(data.get("notes", {}) or {}),
    )


__all__ = [
    "action_scope_from_dict",
    "action_scope_to_dict",
    "condition_clauses_from_list",
    "condition_clauses_to_list",
    "intent_from_dict",
    "intent_to_dict",
    "principal_scope_from_dict",
    "principal_scope_to_dict",
    "resource_scope_from_dict",
    "resource_scope_to_dict",
]
