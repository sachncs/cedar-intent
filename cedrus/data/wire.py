"""Wire-shape classes used at the boundary with external systems.

Each class wraps a JSON-friendly representation that round-trips
through the SQLite columns, the deployment manifest, the HTTP
request body, and the LLM prompt format. Internal APIs consume and
produce typed objects; ``to_dict()`` and the ``from_*`` classmethods
are the only places where strings and dicts cross the wire.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class TargetKind(StrEnum):
    """Deployment target kind. ``LOCAL`` writes to a directory; ``REMOTE`` POSTs via HTTP.

    The ``Kind`` suffix avoids collision with the :class:`Target` class.
    """

    LOCAL = "local"
    REMOTE = "remote"


@dataclass(frozen=True, slots=True)
class Headers:
    """HTTP header collection with reserved-name and CR/LF validation.

    Reserves Host, Authorization, Cookie, Content-Length, Transfer-Encoding.
    Rejects CR/LF in either name or value.

    Attributes:
        items: Tuple of ``(name, value)`` pairs preserving order.
    """

    items: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, str]:
        """Return a dict for the HTTP library."""
        return dict(self.items)

    @classmethod
    def from_strings(cls, raw: Sequence[str]) -> Headers:
        """Parse a list of ``"Name: Value"`` strings.

        Raises:
            Config: When a header is missing a colon, has an empty
                name, contains CR/LF in either name or value, has a
                reserved name, or exceeds the length cap.
        """
        from ..error import Config

        reserved = {"host", "authorization", "cookie", "content-length", "transfer-encoding"}
        items: list[tuple[str, str]] = []
        for entry in raw:
            if ":" not in entry:
                raise Config(f"invalid header (expected 'Name: Value'): {entry!r}")
            name, _, value = entry.partition(":")
            name = name.strip()
            value = value.strip()
            if not name:
                raise Config("header name must be non-empty")
            if "\r" in name or "\n" in name or "\r" in value or "\n" in value:
                raise Config(f"header contains CR/LF: {entry!r}")
            if name.lower() in reserved:
                raise Config(f"header name {name!r} is reserved and cannot be set")
            if len(name) > 256:
                raise Config(f"header name {name!r} exceeds 256 characters")
            if len(value) > 8192:
                raise Config(f"header value for {name!r} exceeds 8192 characters")
            items.append((name, value))
        return cls(items=tuple(items))

    @classmethod
    def from_dict(cls, data: Mapping[str, str]) -> Headers:
        """Build from an existing dict (no validation)."""
        return cls(items=tuple(data.items()))


@dataclass(frozen=True, slots=True)
class Body:
    """HTTP request body with computed SHA-256."""

    payload: bytes
    content_type: str = "application/json"
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        # Use object.__setattr__ because frozen dataclasses forbid
        # attribute assignment in __post_init__.
        object.__setattr__(self, "sha256", hashlib.sha256(self.payload).hexdigest())

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-friendly dict for the wire."""
        import base64

        return {
            "content_type": self.content_type,
            "payload_b64": base64.b64encode(self.payload).decode("ascii"),
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class Receipt:
    """HTTP response metadata persisted in a :class:`~cedrus.deploy.Record`.

    The body itself is never persisted; only its SHA-256 hash is.

    Attributes:
        status_code: HTTP status code returned by the endpoint.
        body_sha256: SHA-256 hex digest of the response body.
        idempotency_key: The ``Idempotency-Key`` sent with the request.
        retry_count: Number of retries the client performed.
    """

    status_code: int
    body_sha256: str
    idempotency_key: str
    retry_count: int

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-friendly dict for SQLite."""
        return {
            "status_code": str(self.status_code),
            "body_sha256": self.body_sha256,
            "idempotency_key": self.idempotency_key,
            "retry_count": str(self.retry_count),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, str]) -> Receipt:
        """Parse a receipt from a stored dict."""
        return cls(
            status_code=int(data["status_code"]),
            body_sha256=data["body_sha256"],
            idempotency_key=data["idempotency_key"],
            retry_count=int(data.get("retry_count", "0")),
        )


@dataclass(frozen=True, slots=True)
class Target:
    """Deployment target (local path or remote URL).

    Use :meth:`local` or :meth:`remote` to construct.

    Attributes:
        kind: Whether the target is local or remote.
        value: The path or URL string.
    """

    kind: TargetKind
    value: str

    @classmethod
    def local(cls, path: Path) -> Target:
        """Construct a local target from a filesystem path."""
        return cls(kind=TargetKind.LOCAL, value=str(path))

    @classmethod
    def remote(cls, url: str) -> Target:
        """Construct a remote target from a URL string."""
        return cls(kind=TargetKind.REMOTE, value=url)

    def is_local(self) -> bool:
        return self.kind == TargetKind.LOCAL

    def is_remote(self) -> bool:
        return self.kind == TargetKind.REMOTE


@dataclass(frozen=True, slots=True)
class Usage:
    """LLM token-usage metadata extracted from a generation response."""

    prompt: int
    completion: int
    total: int

    def to_dict(self) -> dict[str, int]:
        return {"prompt": self.prompt, "completion": self.completion, "total": self.total}


@dataclass(frozen=True, slots=True)
class Notes:
    """Free-form notes attached to an :class:`~cedrus.compile.Intent`."""

    items: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, str]:
        return dict(self.items)

    @classmethod
    def from_dict(cls, data: Mapping[str, str]) -> Notes:
        return cls(items=tuple(data.items()))


@dataclass(frozen=True, slots=True)
class Metadata:
    """Free-form deployment metadata attached to a manifest."""

    items: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, str]:
        return dict(self.items)

    @classmethod
    def from_dict(cls, data: Mapping[str, str]) -> Metadata:
        return cls(items=tuple(data.items()))


@dataclass(frozen=True, slots=True)
class Payload:
    """Typed wrapper for a JSON payload (e.g., a validation report body)."""

    data: tuple[tuple[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.data)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Payload:
        return cls(data=tuple(data.items()))


__all__ = [
    "Body",
    "Headers",
    "Metadata",
    "Notes",
    "Payload",
    "Receipt",
    "Target",
    "TargetKind",
    "Usage",
]
