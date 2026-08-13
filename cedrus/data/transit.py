"""In-process typed data classes.

These types flow through the system in memory. They wrap complex
multi-field structures that would otherwise be passed as dicts.
They are not persisted directly; the persistence layer stores them
as JSON via :meth:`to_dict` and reconstructs them via :meth:`from_dict`.

All classes are ``@dataclass(frozen=True, slots=True)``.

Attributes:
    Context: Input bundle for a generator call.
    Proposal: One generator proposal for a single requirement.
    Result: Final output of a generator call with provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from cedrus.compile import Intent
from cedrus.data.unresolved import Unresolved
from cedrus.data.wire import Notes, Usage
from cedrus.schema import Schema
from cedrus.scope import Action, Principal, Resource


@dataclass(frozen=True, slots=True)
class Context:
    """Input bundle for a generator call.

    Attributes:
        need: The requirement driving the draft.
        schema: The Cedar schema the draft must conform to.
        principal: User-supplied principal scope hint.
        action: User-supplied action scope hint.
        resource: User-supplied resource scope hint.
        existing: Existing intents the generator should be aware of.
    """

    need: Any  # Need type (forward ref to avoid circular import)
    schema: Schema | None = None
    principal: Principal
    action: Action
    resource: Resource
    existing: tuple[Intent, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Proposal:
    """One generator proposal for a single requirement.

    Attributes:
        intent: The proposed typed intent.
        unresolved: Items the generator could not safely resolve.
        notes: Free-form generator-supplied metadata.
    """

    intent: Intent
    unresolved: Unresolved = field(default_factory=Unresolved)
    notes: Notes = field(default_factory=Notes)


@dataclass(frozen=True, slots=True)
class Result:
    """Final output of a generator call with provenance.

    Attributes:
        proposal: The generator's proposal.
        model: Model identifier (or generator's static name).
        request_id: Provider-supplied request identifier.
        usage: Token-usage metadata.
        created_at: When the generator returned;
            defaults to ``datetime.now(UTC)`` if not provided.
    """

    proposal: Proposal
    model: str
    request_id: str
    usage: Usage
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


__all__ = [
    "Context",
    "Proposal",
    "Result",
]
