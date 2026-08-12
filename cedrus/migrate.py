"""Schema migration helpers for cedrus 0.6.0.

Starting with cedrus 0.6.0, every stored :class:`DraftStored`
carries a JSON-serialized typed intent and the per-slot scope JSON,
and every :class:`Stored` carries the action scope JSON.
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
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Protocol

from .compile import Intent
from .scope import Action, Clause, Principal, Resource

if TYPE_CHECKING:
    from .store.base import DraftStored, Stored

LOGGER = logging.getLogger(__name__)


class RepoLike(Protocol):
    """Subset of :class:`~cedrus.store.Repository` used by the migration."""

    def get_policy(self, policy_id: str) -> Stored: ...
    def upsert_policy(self, policy: Stored) -> None: ...
    def list_policies(self, domain: str | None = None) -> Sequence[Stored]: ...
    def list_drafts(self, policy_id: str | None = None) -> Sequence[DraftStored]: ...
    def update_draft_json(
        self, draft_id: str, json_columns: Mapping[str, str | None]
    ) -> None: ...


def detect_legacy_rows(repository: RepoLike) -> int:
    """Return the number of legacy rows in ``repository``.

    A row is legacy when its policy has no ``action_scope_json`` or any
    of its drafts has missing intent or scope JSON.

    Args:
        repository: Repository to scan. Quacks like the
            :class:`~cedrus.store.Repository` Protocol.

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


class Migrator:
    """Legacy migration helper. Single entry point: :meth:`migrate`."""

    def __init__(self, repo: RepoLike) -> None:
        self.repo = repo

    def detect(self) -> int:
        """Return the number of legacy rows that still need migration."""
        return detect_legacy_rows(self.repo)

    def migrate(self) -> int:
        """Migrate every legacy row in place. Returns rows upgraded."""
        return migrate_legacy_rows(self.repo)


def migrate_legacy_rows(repository: RepoLike) -> int:
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
        upgraded += policy_migrate(repository, policy)
        for draft in list(repository.list_drafts(policy.id)):
            upgraded += draft_migrate(repository, draft)
    if upgraded:
        LOGGER.info("migrated %d legacy rows to the 0.6.0 schema", upgraded)
    return upgraded


def policy_migrate(repository: RepoLike, policy: Any) -> int:
    """Re-derive ``action_scope_json`` for ``policy`` when missing."""
    from .store.base import Stored

    if not isinstance(policy, Stored):
        return 0
    if policy.action_scope_json is not None:
        return 0
    action_scope = action_parse_cedar(policy.cedar)
    if action_scope is None:
        return 0
    updated = replace(policy, action_scope_json=dumps(action_scope))
    repository.upsert_policy(updated)
    return 1


def draft_migrate(repository: RepoLike, draft: Any) -> int:
    """Rebuild the intent and scope JSON columns for ``draft`` in place."""
    from .store.base import DraftStored

    if not isinstance(draft, DraftStored):
        return 0
    if (
        draft.intent_json is not None
        and draft.principal_scope_json is not None
        and draft.action_scope_json is not None
        and draft.resource_scope_json is not None
    ):
        return 0
    intent = intent_parse_cedar(draft.cedar, draft.id, draft.policy_id)
    if intent is None:
        return 0
    repository.update_draft_json(
        draft.id,
        {
            "intent_json": dumps(intent),
            "principal_scope_json": dumps(intent.principal),
            "action_scope_json": dumps(intent.action),
            "resource_scope_json": dumps(intent.resource),
        },
    )
    return 1


def intent_parse_cedar(
    cedar: str, intent_id: str, requirement_id: str
) -> Intent | None:
    """Rebuild a typed :class:`Intent` from persisted Cedar text.

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
    return Intent(
        id=intent_id,
        requirement_id=requirement_id,
        effect=effect,  # type: ignore[arg-type]
        principal=Principal(),
        action=Action(),
        resource=Resource(),
        when_clauses=(),
        unless_clauses=(),
    )


def action_parse_cedar(cedar: str) -> Action | None:
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
    return Action(kind="named", name=action_name, namespace=namespace or None)


def dumps(scope: Any) -> str:
    """Serialize a scope object to JSON."""
    from .compile import intent_to_dict

    if isinstance(scope, Principal):
        return json.dumps(scope.to_dict(), sort_keys=True)
    if isinstance(scope, Action):
        return json.dumps(scope.to_dict(), sort_keys=True)
    if isinstance(scope, Resource):
        return json.dumps(scope.to_dict(), sort_keys=True)
    if isinstance(scope, Intent):
        return json.dumps(intent_to_dict(scope), sort_keys=True)
    if isinstance(scope, Clause):
        return json.dumps({"body": scope.body}, sort_keys=True)
    return json.dumps(scope, sort_keys=True, default=str)


def draft_migrate_data(
    draft: Any,
) -> tuple[str, str, str, str] | None:
    """Return the four JSON strings needed to populate the new columns.

    Used by tests to verify migration without touching the repository.
    Returns ``None`` when the draft is already migrated.
    """
    from .store.base import DraftStored

    if not isinstance(draft, DraftStored):
        return None
    if (
        draft.intent_json is not None
        and draft.principal_scope_json is not None
        and draft.action_scope_json is not None
        and draft.resource_scope_json is not None
    ):
        return None
    intent = intent_parse_cedar(draft.cedar, draft.id, draft.policy_id)
    if intent is None:
        return None
    return (
        dumps(intent),
        dumps(intent.principal),
        dumps(intent.action),
        dumps(intent.resource),
    )


__all__ = [
    "draft_migrate_data",
    "detect_legacy_rows",
    "migrate_legacy_rows",
]
