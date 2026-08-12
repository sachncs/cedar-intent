"""Generator Protocol.

A :class:`Generator` turns a :class:`Context` into a :class:`Result`.
The Protocol is intentionally minimal: any object that implements
``generate`` qualifies, which keeps the rest of cedrus independent
of LiteLLM.

Contract
--------

Every generator must:

1. Receive a :class:`Context` that bundles the requirement,
   the user-supplied principal/action/resource scopes, and the
   existing policy intents the generator should be aware of.
2. Return a :class:`Result` carrying:
   - a :class:`Proposal` whose ``intent`` is a typed
     :class:`~cedrus.compile.Intent`,
   - the model identifier that produced the proposal (so the workspace
     can record provenance),
   - optional request-id and token-usage metadata.

Items the generator cannot resolve safely must be reported in
``Proposal.unresolved`` rather than guessed. The deterministic
compiler downstream has no LLM and cannot fill gaps; the prompt is
designed to surface unknowns as ``unresolved`` instead of fabricating
entity types or actions.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from ..data import Context as DataContext
from ..data import Notes, Usage
from ..data import Proposal as DataProposal
from ..data import Result as DataResult

# Re-export the data-layer types under the canonical names.
Context = DataContext
Proposal = DataProposal
Result = DataResult


__all__ = [
    "Context",
    "Generator",
    "Notes",
    "Proposal",
    "Result",
    "Usage",
    "merge_unresolved",
]


def merge_unresolved(*sources: Sequence[str]) -> tuple[str, ...]:
    """Combine unresolved requirement strings, dropping empties and duplicates.

    Args:
        sources: One or more sequences of unresolved item strings. Order
            is preserved by first occurrence.

    Returns:
        A tuple of unique, non-empty strings.
    """
    seen: dict[str, None] = {}
    for source in sources:
        for item in source:
            stripped = item.strip()
            if stripped and stripped not in seen:
                seen[stripped] = None
    return tuple(seen.keys())


@runtime_checkable
class Generator(Protocol):
    """Minimum surface every generator must implement.

    The Protocol is runtime-checkable so workspaces and tests can
    verify conformance with ``isinstance``.
    """

    name: str
    model: str

    def generate(self, context: Context) -> Result: ...
