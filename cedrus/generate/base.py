"""Generator Protocol.

A :class:`Generator` turns a :class:`Context` into a :class:`Result`.
The Protocol is intentionally minimal: any object that implements
``generate`` qualifies, which keeps the rest of cedrus independent
of LiteLLM.

Contract:
    Every generator must:

    1. Receive a :class:`Context` that bundles the requirement,
       the user-supplied principal/action/resource scopes, and the
       existing policy intents the generator should be aware of.
    2. Return a :class:`Result` carrying:
       - a :class:`Proposal` whose ``intent`` is a typed
         :class:`~cedrus.compile.Intent`,
       - the model identifier that produced the proposal (so the
         workspace can record provenance),
       - the request-id and token-usage metadata.

    Items the generator cannot resolve safely must be reported in
    ``Proposal.unresolved`` rather than guessed. The deterministic
    compiler downstream has no LLM and cannot fill gaps; the prompt is
    designed to surface unknowns as ``unresolved`` instead of
    fabricating entity types or actions.

Attributes:
    Context: Input bundle for a generator call.
    Proposal: One generator proposal for a single requirement.
    Result: Final output of a generator call with provenance.
    Generator: Minimum surface every generator must implement.
    merge_unresolved: Combine unresolved requirement strings, dropping
        empties and duplicates.
    Notes: Free-form notes attached to a :class:`~cedrus.compile.Intent`.
    Usage: LLM token-usage metadata extracted from a generation response.

See Also:
    :mod:`cedrus.generate.offline`: Deterministic offline generator.
    :mod:`cedrus.generate.litellm`: LiteLLM-backed generator.
    :mod:`cedrus.data.transit`: Source of the data-layer types
        re-exported here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from cedrus.data import Context as DataContext
from cedrus.data import Notes, Usage
from cedrus.data import Proposal as DataProposal
from cedrus.data import Result as DataResult

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

    Each item is stripped of surrounding whitespace before
    de-duplication; empty strings are ignored.

    Args:
        *sources: One or more sequences of unresolved item strings.
            Order is preserved by first occurrence.

    Returns:
        A tuple of unique, non-empty strings.
    """
    seen: dict[str, None] = dict.fromkeys(
        stripped
        for source in sources
        for item in source
        if (stripped := item.strip())
    )
    return tuple(seen)


@runtime_checkable
class Generator(Protocol):
    """Minimum surface every generator must implement.

    The Protocol is runtime-checkable so workspaces and tests can
    verify conformance with ``isinstance``.

    Attributes:
        name: Human-friendly name of the generator (e.g.
            ``"offline"``, ``"litellm"``).
        model: Model identifier that produced the proposal, or the
            generator's static name when no model is involved.
    """

    name: str
    model: str

    def generate(self, context: Context) -> Result:
        """Run the generator on ``context`` and return the resulting :class:`Result`.

        Args:
            context: Input bundle for this generation call.

        Returns:
            The generator's :class:`Result` including the typed
            :class:`Proposal`.
        """
        ...
