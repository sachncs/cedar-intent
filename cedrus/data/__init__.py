"""Wire-shape data classes for cross-process serialization.

Every class in this package is a frozen dataclass that represents a
specific wire format: HTTP request headers, HTTP request body, HTTP
response receipt, deployment target, LLM token usage, and so on.

Wire shapes are the boundary between the typed in-memory object model
and the untyped strings/bytes on the wire (HTTP, SQLite columns,
manifest JSON). The internal object model never crosses a wire; it
goes through ``to_dict()`` to produce the wire format and
``from_dict()`` / ``from_strings()`` to consume it.

All classes are ``@dataclass(frozen=True, slots=True)``.

Attributes:
    Body: HTTP request body with computed SHA-256.
    Headers: HTTP header collection with reserved-name and CR/LF validation.
    Metadata: Free-form deployment metadata attached to a manifest.
    Notes: Free-form notes attached to an :class:`~cedrus.compile.Intent`.
    Payload: Typed wrapper for a JSON payload (e.g., a validation report body).
    Receipt: HTTP response metadata persisted in a :class:`~cedrus.deploy.Record`.
    Target: Deployment target (local path or remote URL).
    TargetKind: Deployment target kind (``LOCAL`` / ``REMOTE``).
    Usage: LLM token-usage metadata extracted from a generation response.
    Context: Input bundle for a generator call.
    Proposal: One generator proposal for a single requirement.
    Result: Final output of a generator call with provenance.
    Unresolved: Items the generator could not safely resolve.

See Also:
    :mod:`cedrus.data.wire`: Wire-shape classes (JSON-friendly boundary types).
    :mod:`cedrus.data.transit`: In-process typed data classes.
    :mod:`cedrus.data.unresolved`: Typed wrapper for unresolved items.
"""

from cedrus.data.transit import Context, Proposal, Result
from cedrus.data.unresolved import Unresolved
from cedrus.data.wire import (
    Body,
    Headers,
    Metadata,
    Notes,
    Payload,
    Receipt,
    Target,
    TargetKind,
    Usage,
)

__all__ = [
    "Body",
    "Context",
    "Headers",
    "Metadata",
    "Notes",
    "Payload",
    "Proposal",
    "Receipt",
    "Result",
    "Target",
    "TargetKind",
    "Unresolved",
    "Usage",
]
