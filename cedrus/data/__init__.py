"""Wire-shape data classes for cross-process serialization.

Every class in this package is a frozen dataclass that represents a
specific wire format: HTTP request headers, HTTP request body, HTTP
response receipt, deployment target, LLM token usage, and so on.

Wire shapes are the boundary between the typed in-memory object model
and the untyped strings/bytes on the wire (HTTP, SQLite columns,
manifest JSON). The internal object model never crosses a wire; it
goes through ``to_dict()`` to produce the wire format and
``from_dict()`` / ``from_strings()`` / ``from_row()`` to consume
it.

All classes are ``@dataclass(frozen=True, slots=True)``.
"""

from .persist import DraftStored, ReportStored, Stored
from .transit import Context, Proposal, Result
from .unresolved import Unresolved
from .wire import (
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
    "DraftStored",
    "Headers",
    "Metadata",
    "Notes",
    "Payload",
    "Proposal",
    "Receipt",
    "ReportStored",
    "Result",
    "Stored",
    "Target",
    "TargetKind",
    "Unresolved",
    "Usage",
]
