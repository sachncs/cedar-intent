"""Schema migration helpers for cedar-intent 0.6.0.

Starting with cedar-intent 0.6.0, every stored :class:`StoredDraft`
carries a JSON-serialized typed intent and the per-slot scope JSON,
and every :class:`StoredPolicy` carries the action scope JSON.
Databases created before this version are upgraded in place by
:func:`migrate_legacy_rows`.

Detection
---------

:func:`detect_legacy_rows` returns the number of legacy rows. A row is
legacy when its policy has no action_scope_json OR any of its
drafts has missing intent or scope JSON.

Migration
---------

:func:`migrate_legacy_rows` walks every policy in the repository,
rebuilds the action scope from Cedar (when missing), then walks
every draft belonging to the policy and rebuilds the intent plus the
three scope columns from the persisted Cedar text.

Both functions take any object that quacks like the Repository
Protocol: :meth:`get_policy`, :meth:`upsert_policy`,
:meth:`list_policies`, and :meth:`list_drafts`. This lets the same
code operate against the in-memory and SQLite repositories, plus
custom backends.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Protocol

from .compiler import PolicyIntent
from .scope_json import (
    action_scope_to_dict,
    principal_scope_to_dict,
    resource_scope_to_dict,
)
from .scopes import ActionScope, ConditionClause, PrincipalScope, ResourceScope

if TYPE_CHECKING:
    # Imported only for type checking; the runtime path uses structural
    # duck typing through the ``_RepoLike`` Protocol below.
    from .storage.base import StoredDraft, StoredPolicy

# ``StoredDraft`` and ``StoredPolicy`` are imported lazily below to break
# a circular import: ``storage.sqlite`` imports ``detect_legacy_rows``,
# which would otherwise re-enter ``storage.base`` while it is still
# being initialized. The Protocol below is structural, so duck typing
# works against any repository that exposes the four methods.

_LOGGER = logging.getLogger(__name__)


class _RepoLike(Protocol):
    """Subset of :class:`~cedar_intent.storage.Repository` used by the migration."""

    def get_policy(self, policy_id: str) -> StoredPolicy: ...
    def upsert_policy(self, policy: StoredPolicy) -> None: ...
    def list_policies(self, domain: str | None = None) -> Sequence[StoredPolicy]: ...
    def list_drafts(self, policy_id: str | None = None) -> Sequence[StoredDraft]: ...
    def record_draft(self, draft: StoredDraft) -> None: ...


def detect_legacy_rows(repository: _RepoLike) -> int:
    """Return the number of legacy rows in ``repository``.

    A row is legacy when its policy has no ``action_scope_json`` or any
    of its drafts has missing intent or scope JSON.

    Args:
        repository: Repository to scan. Quacks like the
            :class:`~cedar_intent.storage.Repository` Protocol.

    Returns:
        Number of legacy rows that still need migration.
    """
    if not hasattr(repository, "list_policies"):
        return 0
    count = 0
    for policy in repository.list_policies(None):
        if policy.action_scope_json is None:
            count += 1
        for draft in repository.list_drafts(policy.id):
            if (
                draft.intent_json is None
                or draft.principal_scope_json is None
                or draft.action_scope_json is None
                or draft.resource_scope_json is None
            ):
                count += 1
    return count


def migrate_legacy_rows(repository: _RepoLike) -> int:
    """Migrate every legacy row in ``repository``.

    Args:
        repository: Repository to migrate.

    Returns:
        Number of rows that were upgraded in place.
    """
    if not hasattr(repository, "list_policies"):
        return 0
    upgraded = 0
    for policy in list(repository.list_policies(None)):
        upgraded += _migrate_policy(repository, policy)
        for draft in list(repository.list_drafts(policy.id)):
            upgraded += _migrate_draft(repository, draft)
    if upgraded:
        _LOGGER.info("migrated %d legacy rows to the 0.6.0 schema", upgraded)
    return upgraded


def _migrate_policy(repository: _RepoLike, policy: StoredPolicy) -> int:
    """Re-derive ``action_scope_json`` for ``policy`` when missing."""
    if policy.action_scope_json is not None:
        return 0
    action_scope = _parse_action_scope(policy.cedar)
    if action_scope is None:
        return 0
    updated = replace(policy, action_scope_json=_dumps(action_scope))
    repository.upsert_policy(updated)
    return 1


def _migrate_draft(repository: _RepoLike, draft: StoredDraft) -> int:
    """Rebuild the intent and scope JSON columns for ``draft``."""
    if (
        draft.intent_json is not None
        and draft.principal_scope_json is not None
        and draft.action_scope_json is not None
        and draft.resource_scope_json is not None
    ):
        return 0
    intent = _parse_intent_from_cedar(draft.cedar, draft.id, draft.policy_id)
    if intent is None:
        return 0
    updated = StoredDraft(
        id=draft.id,
        policy_id=draft.policy_id,
        model=draft.model,
        request_id=draft.request_id,
        unresolved=draft.unresolved,
        cedar=draft.cedar,
        created_at=draft.created_at,
        intent_json=_dumps(intent),
        principal_scope_json=_dumps(intent.principal),
        action_scope_json=_dumps(intent.action),
        resource_scope_json=_dumps(intent.resource),
    )
    repository.record_draft(updated)
    return 1


def _parse_intent_from_cedar(
    cedar: str, intent_id: str, requirement_id: str
) -> PolicyIntent | None:
    """Rebuild a typed :class:`PolicyIntent` from persisted Cedar text.

    The migration uses the same heuristic parser as the compile-time
    fallback: an ``any``/``any``/``any`` skeleton with a default
    ``permit`` effect. Callers that need precise intent metadata
    should regenerate the draft rather than rely on migration.
    """
    text = cedar.strip()
    if not text:
        return None
    lowered = text.lower()
    effect = "forbid" if lowered.startswith("forbid") else "permit"
    return PolicyIntent(
        id=intent_id,
        requirement_id=requirement_id,
        effect=effect,  # type: ignore[arg-type]
        principal=PrincipalScope(),
        action=ActionScope(),
        resource=ResourceScope(),
        when_clauses=(),
        unless_clauses=(),
    )


def _parse_action_scope(cedar: str) -> ActionScope | None:
    """Best-effort parse of an action scope from Cedar text.

    Returns ``None`` when the Cedar does not name a single action
    (for example, ``action`` is ``any`` or is bound to a group).
    """
    needle = 'Action::"'
    start = cedar.find(needle)
    if start < 0:
        return None
    end = cedar.find('"', start + len(needle))
    if end < 0:
        return None
    action_name = cedar[start + len(needle) : end]
    namespace = None
    before = cedar[:start]
    if before.endswith("::"):
        namespace = before[: -len("::")]
    return ActionScope(kind="named", name=action_name, namespace=namespace or None)


def _dumps(scope: Any) -> str:
    """Serialize a scope object to JSON."""
    if isinstance(scope, PrincipalScope):
        return json.dumps(principal_scope_to_dict(scope), sort_keys=True)
    if isinstance(scope, ActionScope):
        return json.dumps(action_scope_to_dict(scope), sort_keys=True)
    if isinstance(scope, ResourceScope):
        return json.dumps(resource_scope_to_dict(scope), sort_keys=True)
    if isinstance(scope, PolicyIntent):
        return json.dumps(
            {
                "id": scope.id,
                "requirement_id": scope.requirement_id,
                "effect": scope.effect,
                "principal": principal_scope_to_dict(scope.principal),
                "action": action_scope_to_dict(scope.action),
                "resource": resource_scope_to_dict(scope.resource),
                "when": [clause.body for clause in scope.when_clauses],
                "unless": [clause.body for clause in scope.unless_clauses],
                "notes": dict(scope.notes),
            },
            sort_keys=True,
        )
    if isinstance(scope, ConditionClause):
        return json.dumps({"body": scope.body}, sort_keys=True)
    return json.dumps(scope, sort_keys=True, default=str)


def _migrate_draft_data(
    draft: StoredDraft,
) -> tuple[str, str, str, str] | None:
    """Return the four JSON strings needed to populate the new columns.

    Used by tests to verify migration without touching the repository.
    Returns ``None`` when the draft is already migrated.
    """
    if (
        draft.intent_json is not None
        and draft.principal_scope_json is not None
        and draft.action_scope_json is not None
        and draft.resource_scope_json is not None
    ):
        return None
    intent = _parse_intent_from_cedar(draft.cedar, draft.id, draft.policy_id)
    if intent is None:
        return None
    return (
        _dumps(intent),
        _dumps(intent.principal),
        _dumps(intent.action),
        _dumps(intent.resource),
    )


__all__ = [
    "_migrate_draft_data",
    "detect_legacy_rows",
    "migrate_legacy_rows",
]
