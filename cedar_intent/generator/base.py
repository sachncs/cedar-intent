"""Generator Protocol and shared data classes.

A :class:`Generator` turns an authorization intent request into a
:class:`DraftProposal`. The Protocol is intentionally minimal: any object
that implements ``generate`` qualifies, which keeps the rest of
cedar-intent independent of LiteLLM.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..compiler import PolicyIntent
from ..requirements import Requirement
from ..schema import CedarSchema
from ..scopes import ActionScope, PrincipalScope, ResourceScope


@dataclass(frozen=True, slots=True)
class GenerationContext:
    """Inputs supplied to a generator.

    Attributes:
        requirement: The requirement that drives the draft.
        schema: The Cedar schema the draft must conform to.
        principal: User-supplied principal scope for the draft.
        action: User-supplied action scope for the draft.
        resource: User-supplied resource scope for the draft.
        existing: Existing policy intents the generator should be aware of.
    """

    requirement: Requirement
    schema: CedarSchema
    principal: PrincipalScope
    action: ActionScope
    resource: ResourceScope
    existing: tuple[PolicyIntent, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class DraftProposal:
    """One generator proposal for a single requirement.

    Attributes:
        intent: The proposed typed policy intent.
        unresolved: Items the generator could not safely resolve.
        notes: Free-form generator-supplied metadata.
    """

    intent: PolicyIntent
    unresolved: tuple[str, ...] = field(default_factory=tuple)
    notes: Mapping[str, str] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        """Return ``True`` when there are no unresolved items."""
        return not self.unresolved

    def to_dict(self) -> Mapping[str, Any]:
        """Return a JSON-friendly representation of the proposal."""
        return {
            "complete": self.complete,
            "intent_id": self.intent.id,
            "requirement_id": self.intent.requirement_id,
            "unresolved": list(self.unresolved),
            "notes": dict(self.notes),
        }


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Final output of a generator call with provenance."""

    proposal: DraftProposal
    model: str
    request_id: str | None
    usage: Mapping[str, int]


@runtime_checkable
class Generator(Protocol):
    """Minimum surface every generator must implement."""

    name: str
    model: str

    def generate(self, context: GenerationContext) -> GenerationResult: ...


def merge_unresolved(*sources: Sequence[str]) -> tuple[str, ...]:
    """Combine unresolved requirement strings, dropping empties and duplicates."""
    seen: dict[str, None] = {}
    for source in sources:
        for item in source:
            stripped = item.strip()
            if stripped and stripped not in seen:
                seen[stripped] = None
    return tuple(seen.keys())


__all__ = [
    "DraftProposal",
    "GenerationContext",
    "GenerationResult",
    "Generator",
    "merge_unresolved",
]
