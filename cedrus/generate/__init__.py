"""Generator implementations and Protocol.

This package wires generators into the cedrus pipeline. The
:class:`Generator` Protocol is the duck-typed surface every
implementation satisfies; :class:`Context` and :class:`Result` are
the in-memory data shapes that flow through it.

Attributes:
    Context: Input bundle for a generator call.
    Proposal: One generator proposal for a single requirement.
    Result: Final output of a generator call with provenance.
    Generator: Minimum surface every generator must implement.
    Offline: Deterministic generator that requires no network calls.
    Llm: LiteLLM-backed generator for production drafting.

See Also:
    :mod:`cedrus.generate.base`: :class:`Generator` Protocol and
        the data-layer re-exports.
    :mod:`cedrus.generate.offline`: :class:`Offline` generator.
    :mod:`cedrus.generate.litellm`: :class:`Llm` generator.
"""

from cedrus.generate.base import Context, Generator, Proposal, Result
from cedrus.generate.litellm import Llm
from cedrus.generate.offline import Offline

__all__ = [
    "Context",
    "Generator",
    "Llm",
    "Offline",
    "Proposal",
    "Result",
]