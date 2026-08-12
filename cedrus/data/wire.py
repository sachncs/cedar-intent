"""Wire-shape classes used at the boundary with external systems.

Each class wraps a JSON-friendly representation that round-trips
through the SQLite columns, the deployment manifest, the HTTP
request body, and the LLM prompt format. Internal APIs consume and
produce typed objects; ``to_dict()`` and the ``from_*`` classmethods
are the only places where strings and dicts cross the wire.

All classes are ``@dataclass(frozen=True, slots=True)`` unless noted.

Attributes:
    TargetKind: Deployment target kind (``LOCAL`` / ``REMOTE``).
    Headers: HTTP header collection with reserved-name and CR/LF validation.
    Body: HTTP request body with computed SHA-256.
    Receipt: HTTP response metadata persisted in a :class:`~cedrus.deploy.Record`.
    Target: Deployment target (local path or remote URL).
    Usage: LLM token-usage metadata extracted from a generation response.
    Notes: Free-form notes attached to an :class:`~cedrus.compile.Intent`.
    Metadata: Free-form deployment metadata attached to a manifest.
    Payload: Typed wrapper for a JSON payload (e.g., a validation report body).

See Also:
    :mod:`cedrus.store.base`: The persistence rows that store these
        wire shapes in SQLite.
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
        """Return a dict for the HTTP library.

        Returns:
            A ``{name: value}`` dict preserving insertion order.
        """
        return dict(self.items)

    @classmethod
    def from_strings(cls, raw: Sequence[str]) -> Headers:
        """Parse a list of ``"Name: Value"`` strings.

        Args:
            raw: Sequence of ``"Name: Value"`` strings.

        Returns:
            A new :class:`Headers` instance.

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
        """Build from an existing dict (no validation).

        Args:
            data: Mapping of header name to value.

        Returns:
            A new :class:`Headers` instance.
        """
        return cls(items=tuple(data.items()))


@dataclass(frozen=True, slots=True)
class Body:
    """HTTP request body with computed SHA-256.

    The SHA-256 of the payload is computed in ``__post_init__`` and
    exposed as the ``sha256`` field.

    Attributes:
        payload: Raw request body bytes.
        content_type: MIME type of the payload; defaults to
            ``"application/json"``.
        sha256: Lowercase hex digest of ``payload``; not part of the
            constructor (``init=False``).
    """

    payload: bytes
    content_type: str = "application/json"
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        """Compute and cache the SHA-256 of the payload bytes."""
        # Use object.__setattr__ because frozen dataclasses forbid
        # attribute assignment in __post_init__.
        object.__setattr__(self, "sha256", hashlib.sha256(self.payload).hexdigest())

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-friendly dict for the wire.

        The payload is base64-encoded so it survives JSON transport.

        Returns:
            A dict with ``content_type``, ``payload_b64`` and
            ``sha256`` keys.
        """
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
        """Return a JSON-friendly dict for SQLite.

        Numeric fields are stringified so the dict round-trips through
        a JSON column without loss.

        Returns:
            A dict with string values for ``status_code`` and
            ``retry_count``, plus the original strings.
        """
        return {
            "status_code": str(self.status_code),
            "body_sha256": self.body_sha256,
            "idempotency_key": self.idempotency_key,
            "retry_count": str(self.retry_count),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, str]) -> Receipt:
        """Parse a receipt from a stored dict.

        Args:
            data: Dict previously produced by :meth:`to_dict`.

        Returns:
            A new :class:`Receipt` instance.
        """
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
        """Construct a local target from a filesystem path.

        Args:
            path: Filesystem path the bundle will be written to.

        Returns:
            A new :class:`Target` with kind ``LOCAL``.
        """
        return cls(kind=TargetKind.LOCAL, value=str(path))

    @classmethod
    def remote(cls, url: str) -> Target:
        """Construct a remote target from a URL string.

        Args:
            url: Endpoint the bundle will be POSTed to.

        Returns:
            A new :class:`Target` with kind ``REMOTE``.
        """
        return cls(kind=TargetKind.REMOTE, value=url)

    def is_local(self) -> bool:
        """Return ``True`` when the target is local."""
        return self.kind == TargetKind.LOCAL

    def is_remote(self) -> bool:
        """Return ``True`` when the target is remote."""
        return self.kind == TargetKind.REMOTE


@dataclass(frozen=True, slots=True)
class Usage:
    """LLM token-usage metadata extracted from a generation response.

    Attributes:
        prompt: Tokens consumed by the prompt.
        completion: Tokens generated by the model.
        total: Sum of ``prompt`` and ``completion``.
    """

    prompt: int
    completion: int
    total: int

    def to_dict(self) -> dict[str, int]:
        """Return a JSON-friendly dict for the wire.

        Returns:
            A dict with ``prompt``, ``completion`` and ``total`` keys.
        """
        return {"prompt": self.prompt, "completion": self.completion, "total": self.total}


@dataclass(frozen=True, slots=True)
class Notes:
    """Free-form notes attached to an :class:`~cedrus.compile.Intent`.

    Attributes:
        items: Tuple of ``(key, value)`` pairs preserving order.
    """

    items: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-friendly dict for the wire.

        Returns:
            A dict of notes keyed by ``key``.
        """
        return dict(self.items)

    @classmethod
    def from_dict(cls, data: Mapping[str, str]) -> Notes:
        """Build from a dict of notes.

        Args:
            data: Mapping of note key to value.

        Returns:
            A new :class:`Notes` instance.
        """
        return cls(items=tuple(data.items()))


@dataclass(frozen=True, slots=True)
class Metadata:
    """Free-form deployment metadata attached to a manifest.

    Attributes:
        items: Tuple of ``(key, value)`` pairs preserving order.
    """

    items: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-friendly dict for the manifest.

        Returns:
            A dict of metadata keyed by ``key``.
        """
        return dict(self.items)

    @classmethod
    def from_dict(cls, data: Mapping[str, str]) -> Metadata:
        """Build from a dict of metadata.

        Args:
            data: Mapping of metadata key to value.

        Returns:
            A new :class:`Metadata` instance.
        """
        return cls(items=tuple(data.items()))


@dataclass(frozen=True, slots=True)
class Payload:
    """Typed wrapper for a JSON payload (e.g., a validation report body).

    Attributes:
        data: Tuple of ``(key, value)`` pairs preserving order.
    """

    data: tuple[tuple[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly dict for the wire.

        Returns:
            A dict of payload entries keyed by ``key``.
        """
        return dict(self.data)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Payload:
        """Build from a dict payload.

        Args:
            data: Mapping of payload key to value.

        Returns:
            A new :class:`Payload` instance.
        """
        return cls(data=tuple(data.items()))

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Payload:
        """Build a :class:`Payload` from its SQLite ``report_payload`` rows.

        Args:
            data: Dict with a ``"report_payload"`` key holding the
                ordered list of ``{"position", "key", "value"}`` row
                dicts from the ``report_payload`` table.

        Returns:
            The reconstructed :class:`Payload`.
        """
        rows = sorted(data["report_payload"], key=lambda r: r["position"])
        return cls(data=tuple((r["key"], r["value"]) for r in rows))

    def to_data(self) -> dict[str, Any]:
        """Return the ``report_payload`` rows for this :class:`Payload`.

        Returns:
            A dict with a ``"report_payload"`` list of
            ``{"position", "key", "value"}`` row dicts.
        """
        return {
            "report_payload": [
                {"position": i, "key": k, "value": v}
                for i, (k, v) in enumerate(self.data)
            ],
        }


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
