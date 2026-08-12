"""Deployment automation for compiled Cedar policies.

A :class:`Bundler` produces a self-contained deployment artifact
(a Cedar source bundle plus a manifest with a SHA-256 integrity hash).
A :class:`Client` pushes the bundle to either a local directory
or a remote HTTP endpoint and records the deployment in the workspace.

Bundle format
-------------

Every deployment produces a two-file artifact:

* ``bundle.cedar`` - concatenated Cedar source for every compiled
  policy in the domain.
* ``manifest.json`` - metadata describing the bundle: domain, the
  SHA-256 of ``bundle.cedar``, policy identifiers, creation timestamp,
  and any user-supplied metadata.

The bundle hash in the manifest is recomputed on read; a mismatch
or a missing manifest hash raises :class:`Deploy`. The hash
provides **corruption detection** after transport; it is not an
authenticated signature. To obtain tamper evidence, add a keyed
signature (HMAC-SHA-256 with a shared key, or Ed25519 with a known
public key) in the deploy metadata on the receiving side.

Atomicity
---------

Local deployments write the bundle to a sibling temporary directory
first, fsync both data and directory, and atomically rename each file
into place with ``Path.replace``. Concurrent writers therefore never
observe a mixed state where one file is the new version and the other
is the old version. A crash before the rename leaves the previous
bundle untouched. Symlink targets are refused to avoid cross-trust
boundary replacement.

Network behavior
----------------

``Client.deploy_http`` uses :mod:`httpx` with a custom
transport that pins the connection to the IP address resolved at
SSRF-check time. This closes the DNS-rebinding window in which an
attacker controlling authoritative DNS returns a public address at
guard time and a private address at request time. Redirects are
disabled by default; an explicit ``follow_redirects=True`` flag is
required to follow 3xx responses (which re-enter the SSRF guard on
each hop).

Response bodies are read in bounded chunks so that a streaming or
oversized endpoint cannot exhaust memory. The body is **never**
embedded in error messages or persisted verbatim in deployment
records; only a SHA-256 of the body is retained. This prevents the
deployment client from leaking whatever the target server returns
(stack traces, echoed credentials, internal hostnames) into stderr
or the SQLite store.

The default :class:`Guard` rejects loopback, link-local, and
private-network targets so untrusted callers cannot use the
deployment client as an SSRF proxy. Operators who genuinely need to
deploy into a private network can pass
``allow_private_targets=True`` to the client constructor.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import ssl
import tempfile
import urllib.parse
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .error import Deploy
from .policies import Compiled, Kind

DEPLOYMENT_KIND_LOCAL = "local"
DEPLOYMENT_KIND_HTTP = "http"

#: Maximum number of bytes of the HTTP response body to hash. The body
#: is also bounded at read time so that a streaming or oversized
#: response cannot exhaust memory.
HTTP_RESPONSE_BODY_LIMIT = 512

#: Maximum total bytes read from an HTTP response body. Pairs with
#: :data:`HTTP_RESPONSE_BODY_LIMIT` so a streaming endpoint cannot
#: exhaust memory before the per-record truncation runs.
HTTP_RESPONSE_READ_LIMIT = 65536

#: Reserved HTTP header names that callers may not inject via ``--header``.
#: ``Host`` would override the SSRF guard's pinned host; ``Authorization``
#: and ``Cookie`` could leak credentials; ``Content-Length`` and
#: ``Transfer-Encoding`` are framing headers httpx manages itself.
_RESERVED_HEADERS = frozenset(
    {"host", "authorization", "cookie", "content-length", "transfer-encoding"}
)


@dataclass(frozen=True, slots=True)
class Manifest:
    """Self-contained deployment artifact.

    Attributes:
        domain: Domain the manifest applies to.
        cedar: Concatenated Cedar source for every compiled policy.
        bundle_hash: SHA-256 integrity hash of ``cedar``.
        policy_ids: Identifiers of the policies included in the bundle.
        created_at: Timestamp at which the manifest was created.
        metadata: Free-form deployment metadata.
    """

    domain: str
    cedar: str
    bundle_hash: str
    policy_ids: tuple[str, ...]
    created_at: datetime
    metadata: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> Mapping[str, Any]:
        """Return a JSON-friendly representation including the Cedar source.

        The returned mapping is suitable for direct JSON serialization.
        The full Cedar source is included so consumers do not need to
        also read ``bundle.cedar`` when reconstructing the bundle.
        """
        return {
            "domain": self.domain,
            "bundle_hash": self.bundle_hash,
            "policy_ids": list(self.policy_ids),
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
            "cedar": self.cedar,
        }

    def to_manifest_payload(self) -> Mapping[str, Any]:
        """Return the manifest payload without the bundled Cedar source.

        Used when writing the manifest to disk so the Cedar source is
        not duplicated in ``manifest.json`` (it lives in ``bundle.cedar``
        alongside).
        """
        return {
            "domain": self.domain,
            "bundle_hash": self.bundle_hash,
            "policy_ids": list(self.policy_ids),
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class Record:
    """Persisted record of a successful deployment.

    Attributes:
        id: Unique deployment identifier.
        domain: Domain that was deployed.
        target: Local path or HTTP URL the bundle was pushed to.
        target_kind: ``"local"`` or ``"http"``.
        bundle_hash: SHA-256 of the deployed Cedar source.
        status: ``"deployed"`` or ``"rejected"``.
        created_at: Timestamp at which the deployment completed.
        response: Provider response metadata (for HTTP targets). The
            response body is recorded only as a SHA-256 hash; the raw
            body is never persisted.
    """

    id: str
    domain: str
    target: str
    target_kind: str
    bundle_hash: str
    status: str
    created_at: datetime
    response: Mapping[str, str] = field(default_factory=dict)


class Bundler:
    """Build, write, and read :class:`Manifest` objects.

    All methods are stateless and can be used as static methods, but are
    exposed as instance methods to keep a consistent call style.
    """

    def build(
        self,
        domain: str,
        policies: Sequence[Kind],
        *,
        metadata: Mapping[str, str] | None = None,
    ) -> Manifest:
        """Build a manifest from compiled policies.

        Args:
            domain: Domain the manifest belongs to.
            policies: Policies to include; only those with non-empty Cedar
                source are considered.
            metadata: Optional deployment metadata.

        Returns:
            The constructed :class:`Manifest`.

        Raises:
            Deploy: If no compiled policies are available.
        """
        compiled = [
            policy
            for policy in policies
            if isinstance(policy, Compiled) and policy.cedar.strip()
        ]
        if not compiled:
            raise Deploy(
                f"no compiled policies to deploy for domain {domain!r}"
            )
        cedar_text = "\n\n".join(policy.cedar for policy in compiled)
        bundle_hash = hashlib.sha256(cedar_text.encode("utf-8")).hexdigest()
        return Manifest(
            domain=domain,
            cedar=cedar_text,
            bundle_hash=bundle_hash,
            policy_ids=tuple(policy.id for policy in compiled),
            created_at=datetime.now(UTC),
            metadata=dict(metadata or {}),
        )

    def write_directory(self, manifest: Manifest, directory: Path) -> Path:
        """Write ``manifest`` to ``directory`` atomically.

        Creates ``bundle.cedar`` and ``manifest.json`` in a sibling
        temporary directory first, fsyncs both data files and the
        directory, and renames each file into place with
        ``Path.replace``. Concurrent writers never observe a mixed
        state where one file is the new version and the other is the
        old version. A crash before the rename leaves the previous
        bundle untouched.

        Symlink targets are refused to avoid replacing a file the
        operator did not intend. A non-empty staging directory is
        also refused.

        Args:
            manifest: Manifest to write.
            directory: Target directory. Created if it does not exist.

        Returns:
            The directory the manifest was written to.

        Raises:
            Deploy: If writing the temporary files or the
                rename fails, or the directory is a symlink or a
                symlink exists inside the staging directory.
        """
        directory = directory.resolve(strict=False)
        if directory.is_symlink():
            raise Deploy(
                f"refusing to write deployment bundle through symlink: {directory}"
            )
        directory.parent.mkdir(parents=True, exist_ok=True)
        directory.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=f".{directory.name}.staging.", dir=directory.parent)
        )
        try:
            bundle_path = staging / "bundle.cedar"
            manifest_path = staging / "manifest.json"
            bundle_path.write_text(manifest.cedar, encoding="utf-8")
            manifest_path.write_text(
                json.dumps(manifest.to_manifest_payload(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            for filename in ("bundle.cedar", "manifest.json"):
                src = staging / filename
                dst = directory / filename
                with src.open("rb") as handle:
                    handle.flush()
                    os_fsync(handle.fileno())
                os_fsync_directory(staging)
                os_replace(src, dst)
            os_fsync_directory(directory)
        except OSError as error:
            raise Deploy(
                f"failed to write deployment bundle to {directory}: {error}"
            ) from error
        finally:
            _rm_tmp(staging)
        return directory

    def read_directory(self, directory: Path) -> Manifest:
        """Read a previously written manifest back from ``directory``.

        Recomputes the bundle hash from ``bundle.cedar`` and compares
        it against the manifest's recorded hash. A mismatch or a
        missing manifest hash raises :class:`Deploy`.

        Args:
            directory: Directory containing ``bundle.cedar`` and
                ``manifest.json``.

        Returns:
            The reconstructed :class:`Manifest`.

        Raises:
            Deploy: If the directory is missing files, the
                manifest has no bundle hash, or the bundle hash does
                not match the recorded value.
        """
        if not directory.exists() or not directory.is_dir():
            raise Deploy(f"deployment directory not found: {directory}")
        bundle_path = directory / "bundle.cedar"
        manifest_path = directory / "manifest.json"
        if not bundle_path.exists() or not manifest_path.exists():
            raise Deploy(
                f"deployment directory is missing bundle or manifest: {directory}"
            )
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise Deploy(
                f"deployment manifest is not valid JSON: {error}"
            ) from error
        cedar_text = bundle_path.read_text(encoding="utf-8")
        expected_hash = data.get("bundle_hash")
        if not expected_hash:
            raise Deploy(
                "deployment manifest is missing bundle_hash; refusing to trust "
                "an unverifiable bundle"
            )
        actual_hash = hashlib.sha256(cedar_text.encode("utf-8")).hexdigest()
        if expected_hash != actual_hash:
            raise Deploy(
                "deployment bundle hash mismatch: expected "
                f"{expected_hash}, got {actual_hash}"
            )
        return Manifest(
            domain=data["domain"],
            cedar=cedar_text,
            bundle_hash=actual_hash,
            policy_ids=tuple(data.get("policy_ids", [])),
            created_at=datetime.fromisoformat(data["created_at"]),
            metadata=dict(data.get("metadata", {})),
        )


class Guard:
    """Reject requests to loopback, link-local, or private network targets.

    The deployment client constructs an :class:`Guard` by default so
    untrusted callers cannot use the client as an SSRF proxy. The
    guard resolves the target hostname through DNS and rejects any
    address that falls inside a reserved range.

    The guard is also responsible for **pinning** the resolved address.
    Callers should connect to the returned :class:`Pin`
    rather than re-resolving the hostname, which closes the
    DNS-rebinding window in which an attacker returns a public
    address at guard time and a private address at request time.

    Attributes:
        allow_private_targets: When ``True``, the guard permits
            addresses inside RFC1918 private ranges. Loopback and
            link-local are still rejected.
        allow_loopback: When ``True``, the guard permits loopback and
            link-local addresses. Intended for tests that bind to
            ``127.0.0.1``; never enable in production.
        resolver: Optional DNS resolver. Defaults to
            :func:`socket.getaddrinfo`. Tests inject a stub to avoid
            network calls.
    """

    BLOCKED_NETWORKS: tuple[
        ipaddress.IPv4Network | ipaddress.IPv6Network, ...
    ] = (
        ipaddress.ip_network("0.0.0.0/8"),
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("198.18.0.0/15"),
        ipaddress.ip_network("255.255.255.255/32"),
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("fc00::/7"),
        ipaddress.ip_network("fe80::/10"),
        ipaddress.ip_network("2001:db8::/32"),
    )

    def __init__(
        self,
        *,
        allow_private_targets: bool = False,
        allow_loopback: bool = False,
        resolver: Any = None,
    ) -> None:
        self.allow_private_targets = allow_private_targets
        self.allow_loopback = allow_loopback
        self.resolver = resolver

    def check(self, url: str) -> Pin:
        """Validate ``url`` and return the pinned connection target.

        Args:
            url: Full HTTP(S) URL to validate.

        Returns:
            A :class:`Pin` describing the host, port, scheme,
            and the IP that the connection must use. Callers must
            connect to ``pinned.ip`` with the explicit ``Host:``
            header set from ``pinned.host`` so that TLS SNI and
            virtual-host routing still use the original hostname.

        Raises:
            Deploy: When the host resolves to a blocked network
                range, the URL is malformed, or DNS resolution fails.
        """
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise Deploy(
                f"deployment URL has unsupported scheme: {parsed.scheme!r}"
            )
        host = parsed.hostname
        if not host:
            raise Deploy(f"deployment URL is missing a host: {url}")
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "https" else 80
        try:
            infos = (
                self.resolver(host)
                if self.resolver
                else socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            )
        except (socket.gaierror, UnicodeError) as error:
            raise Deploy(
                f"could not resolve deployment host {host}: {error}"
            ) from error
        if not infos:
            raise Deploy(
                f"deployment host {host} did not resolve to any address"
            )
        seen_families: set[int] = set()
        last_rejection: Deploy | None = None
        for info in infos:
            family = info[0]
            sock_address = info[4]
            ip_str = sock_address[0]
            if isinstance(ip_str, bytes):
                ip_str = ip_str.decode("ascii", errors="replace")
            elif not isinstance(ip_str, str):
                continue
            seen_families.add(family)
            try:
                parsed_address = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            rejection = self._check_address(parsed_address, host)
            if rejection is None:
                return Pin(
                    host=host,
                    port=port,
                    scheme=parsed.scheme,
                    ip=ip_str,
                    family=family,
                )
            last_rejection = rejection
        if last_rejection is not None:
            raise last_rejection
        raise Deploy(
            f"deployment host {host} did not resolve to any usable address"
        )

    def _check_address(
        self, parsed_address: ipaddress.IPv4Address | ipaddress.IPv6Address, host: str
    ) -> Deploy | None:
        """Return a rejection error for blocked addresses or ``None``."""
        for network in self.BLOCKED_NETWORKS:
            if parsed_address in network:
                if network.is_loopback or network.is_link_local:
                    if self.allow_loopback:
                        return None
                    return Deploy(
                        f"deployment URL targets loopback or link-local "
                        f"address {parsed_address} ({network})"
                    )
                if self.allow_private_targets:
                    return None
                return Deploy(
                    f"deployment URL targets private-network address "
                    f"{parsed_address} ({network}); pass "
                    "allow_private_targets=True to override"
                )
        return None


@dataclass(frozen=True, slots=True)
class Pin:
    """A DNS-resolved address to which an HTTP connection must be pinned.

    The transport created by :func:`_pinned_transport` will connect to
    ``(ip, port)`` and set the ``Host`` header to ``host``. This closes
    the DNS-rebinding window between the SSRF guard and the actual
    connection.
    """

    host: str
    port: int
    scheme: str
    ip: str
    family: int


class Transport(httpx.BaseTransport):
    """An :mod:`httpx` transport that pins each connection to a resolved IP.

    The transport refuses to reconnect to the original hostname; if the
    caller asks for a URL whose host or port disagrees with the pinned
    address, the request is rejected. This is what closes the
    DNS-rebinding gap.

    The transport opens the socket itself, wraps with TLS when the
    scheme is ``https``, sends a minimal HTTP/1.1 request, reads the
    response with a hard byte cap, and returns a parsed
    :class:`httpx.Response`. The byte cap mirrors
    :data:`HTTP_RESPONSE_READ_LIMIT`.
    """

    def __init__(self, pinned: Pin) -> None:
        self.pinned = pinned
        self._closed = False

    def close(self) -> None:
        self._closed = True

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self._closed:
            raise Deploy("pinned transport has been closed")
        url = request.url
        if url.host != self.pinned.host or url.port != self.pinned.port:
            raise Deploy(
                f"deployment transport mismatch: request url {url!s} disagrees "
                f"with pinned {self.pinned.host}:{self.pinned.port}"
            )
        timeout = _read_timeout(request)
        try:
            sock = socket.create_connection(
                (self.pinned.ip, self.pinned.port), timeout=timeout
            )
        except OSError as error:
            raise Deploy(
                f"deployment connection to pinned "
                f"{self.pinned.ip}:{self.pinned.port} failed: {error}"
            ) from error
        try:
            if self.pinned.scheme == "https":
                context = ssl.create_default_context()
                try:
                    sock = context.wrap_socket(
                        sock, server_hostname=self.pinned.host
                    )
                except OSError as error:
                    raise Deploy(
                        f"deployment TLS handshake to "
                        f"{self.pinned.host} failed: {error}"
                    ) from error
            request.headers["Host"] = self.pinned.host
            return _round_trip_http(request, sock, timeout)
        finally:
            try:
                sock.close()
            except OSError:
                pass


def _read_timeout(request: httpx.Request) -> float:
    """Extract the per-request timeout from the :class:`httpx.Request` extensions."""
    timeout = request.extensions.get("timeout")
    if timeout is None:
        return 30.0
    if isinstance(timeout, httpx.Timeout):
        return float(timeout.connect or 30.0)
    if isinstance(timeout, Mapping):
        connect = timeout.get("connect", 30.0)
        try:
            return float(connect)
        except (TypeError, ValueError) as error:
            raise Deploy(
                f"invalid httpx timeout extension: {timeout!r}"
            ) from error
    try:
        return float(timeout)
    except (TypeError, ValueError) as error:
        raise Deploy(
            f"invalid httpx timeout extension: {timeout!r}"
        ) from error


def _round_trip_http(
    request: httpx.Request, sock: socket.socket, timeout: float
) -> httpx.Response:
    """Send ``request`` over ``sock`` and parse the response.

    The HTTP/1.1 implementation here is intentionally minimal: a
    single request, a single response, with a hard byte cap on the
    body. There is no chunked transfer-encoding support because the
    deployment client does not stream requests and most deployment
    endpoints respond with a small JSON body.
    """
    body = b"" if request.content is None else bytes(request.content)
    host_header = request.headers.get("Host") or request.url.host or ""
    head_lines = [
        f"{request.method} {request.url.path or '/'} HTTP/1.1",
        f"Host: {host_header}",
    ]
    for name, value in request.headers.items():
        if name.lower() == "host":
            continue
        head_lines.append(f"{name}: {value}")
    head_lines.append(f"Content-Length: {len(body)}")
    head_lines.append("")
    head_lines.append("")
    sock.settimeout(timeout)
    sock.sendall("\r\n".join(head_lines).encode("ascii") + body)

    response_bytes = bytearray()
    header_end = -1
    while True:
        try:
            chunk = sock.recv(4096)
        except TimeoutError as error:
            raise Deploy(
                f"deployment response timed out after {timeout}s"
            ) from error
        if not chunk:
            break
        response_bytes.extend(chunk)
        if b"\r\n\r\n" in response_bytes and header_end == -1:
            header_end = response_bytes.index(b"\r\n\r\n") + 4
        if header_end != -1 and len(response_bytes) >= HTTP_RESPONSE_READ_LIMIT:
            response_bytes = response_bytes[:HTTP_RESPONSE_READ_LIMIT]
            break
    return _parse_raw_response(bytes(response_bytes))


def _parse_raw_response(raw: bytes) -> httpx.Response:
    """Parse a raw HTTP/1.1 response into an :class:`httpx.Response`."""
    if b"\r\n\r\n" not in raw:
        raise Deploy(
            "deployment response was truncated before headers completed"
        )
    head_bytes, _, body_bytes = raw.partition(b"\r\n\r\n")
    head_text = head_bytes.decode("iso-8859-1")
    lines = head_text.split("\r\n")
    status_line = lines[0]
    parts = status_line.split(" ", 2)
    if len(parts) < 2 or not parts[1].isdigit():
        raise Deploy(
            f"could not parse HTTP status line: {status_line!r}"
        )
    status_code = int(parts[1])
    header_pairs: list[tuple[str, str]] = []
    for line in lines[1:]:
        if not line:
            continue
        name, _, value = line.partition(":")
        header_pairs.append((name.strip(), value.strip()))
    return httpx.Response(
        status_code=status_code,
        headers=httpx.Headers(header_pairs),
        content=body_bytes,
    )


class Client:
    """Push a :class:`Manifest` to a local directory or HTTP endpoint."""

    def __init__(
        self,
        *,
        timeout: float = 30,
        allow_private_targets: bool = False,
        allow_loopback: bool = False,
        ssrf_guard: Guard | None = None,
        max_retries: int = 0,
        retry_backoff: float = 0.5,
        follow_redirects: bool = False,
    ) -> None:
        """Initialize the deployment client.

        Args:
            timeout: HTTP timeout in seconds for remote deployments.
            allow_private_targets: When ``True``, the SSRF guard permits
                RFC1918 private-network targets. Loopback and link-local
                addresses are still rejected.
            allow_loopback: When ``True``, permits loopback and
                link-local targets. Intended for tests that bind to
                ``127.0.0.1``; never enable in production.
            ssrf_guard: Optional guard override (mostly for tests).
            max_retries: Number of additional attempts on retryable
                failures (429, 503, network errors). Each retry re-sends
                the same ``Idempotency-Key`` so the server can dedupe.
            retry_backoff: Initial backoff in seconds; doubled per
                attempt up to 8 s.
            follow_redirects: When ``True``, 3xx responses are followed.
                **Disabled by default** because a redirect to a private
                address would bypass the SSRF guard unless the redirect
                target is re-validated; the client does not re-validate
                redirect targets, so leaving this ``False`` is the
                safe default.

        Raises:
            Deploy: If ``timeout`` is not strictly positive or
                ``max_retries`` is negative.
        """
        if timeout <= 0 or not _is_finite(timeout):
            raise Deploy("deployment timeout must be positive and finite")
        if max_retries < 0:
            raise Deploy("deployment max_retries must be non-negative")
        if retry_backoff < 0 or not _is_finite(retry_backoff):
            raise Deploy("deployment retry_backoff must be non-negative")
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.follow_redirects = follow_redirects
        self.ssrf_guard = ssrf_guard or Guard(
            allow_private_targets=allow_private_targets,
            allow_loopback=allow_loopback,
        )

    def deploy(
        self,
        manifest: Manifest,
        target: str,
        *,
        record_id: str | None = None,
        headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> Record:
        """Push ``manifest`` to ``target`` (local path or http(s) URL).

        Dispatches to :meth:`deploy_local` when ``target`` is a path
        and to :meth:`deploy_http` when it has an ``http://`` or
        ``https://`` scheme. The caller receives a :class:`Record`
        describing the outcome.

        Args:
            manifest: Bundle to push.
            target: Destination. Either a filesystem path or an
                ``http(s)://`` URL.
            record_id: Optional explicit identifier for the deployment
                record. Auto-generated when omitted.
            headers: Optional HTTP headers added to the POST request.
                Reserved names (``Host``, ``Authorization``, ``Cookie``,
                ``Content-Length``, ``Transfer-Encoding``) are rejected.
            idempotency_key: Optional explicit idempotency key. When
                omitted a UUID is generated. The key is sent as the
                ``Idempotency-Key`` header.

        Returns:
            The deployment record describing the outcome.

        Raises:
            Deploy: If the target is invalid, the HTTP
                endpoint returns non-2xx, or the request fails.
        """
        if not target.strip():
            raise Deploy("deployment target must be non-empty")
        parsed = urllib.parse.urlparse(target)
        if parsed.scheme in {"http", "https"}:
            return self.deploy_http(
                manifest,
                target,
                record_id=record_id,
                headers=headers,
                idempotency_key=idempotency_key,
            )
        return self.deploy_local(manifest, Path(target), record_id=record_id)

    def deploy_local(
        self,
        manifest: Manifest,
        directory: Path,
        *,
        record_id: str | None = None,
    ) -> Record:
        """Write ``manifest`` to ``directory`` atomically and return the record.

        Args:
            manifest: Bundle to write.
            directory: Target directory. Created if missing.
            record_id: Optional explicit identifier for the record.

        Returns:
            The deployment record describing the local write.
        """
        directory.parent.mkdir(parents=True, exist_ok=True)
        Bundler().write_directory(manifest, directory)
        return Record(
            id=record_id or generate_record_id(),
            domain=manifest.domain,
            target=str(directory.resolve()),
            target_kind=DEPLOYMENT_KIND_LOCAL,
            bundle_hash=manifest.bundle_hash,
            status="deployed",
            created_at=datetime.now(UTC),
        )

    def deploy_http(
        self,
        manifest: Manifest,
        url: str,
        *,
        record_id: str | None = None,
        headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> Record:
        """POST ``manifest`` to ``url`` and return the deployment record.

        The connection is **pinned** to the IP address resolved at
        SSRF-check time, so a DNS change between the guard and the
        request cannot redirect the deployment into a private network.
        The response body is read in bounded chunks and never
        embedded in error messages or persisted verbatim; only a
        SHA-256 of the body is retained. 2xx responses are treated as
        success; 4xx and 5xx raise :class:`Deploy`.

        Args:
            manifest: Bundle to push.
            url: HTTP endpoint accepting a JSON POST.
            record_id: Optional explicit identifier for the record.
            headers: Optional HTTP headers added to the POST. Reserved
                names are rejected.
            idempotency_key: Optional explicit idempotency key. A
                UUID is generated when omitted.

        Returns:
            The deployment record describing the HTTP push.

        Raises:
            Deploy: When the URL fails the SSRF guard, the
                endpoint returns non-2xx, the request times out, or the
                network fails.
        """
        validate_headers(headers)
        pinned = self.ssrf_guard.check(url)
        idem = idempotency_key or uuid.uuid4().hex
        payload = json.dumps(manifest.to_dict()).encode("utf-8")
        request_headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-Cedar-Bundle-Hash": manifest.bundle_hash,
            "X-Cedar-Domain": manifest.domain,
            "Idempotency-Key": idem,
        }
        if headers:
            request_headers.update(dict(headers))

        request = httpx.Request(
            "POST",
            httpx.URL(url),
            headers=request_headers,
            content=payload,
        )
        attempt = 0
        backoff = self.retry_backoff
        last_error: Deploy | None = None
        while attempt <= self.max_retries:
            try:
                with httpx.Client(
                    transport=Transport(pinned),
                    timeout=self.timeout,
                    follow_redirects=self.follow_redirects,
                ) as client:
                    response = client.send(request)
                    body = _read_bounded_body(response)
                    response_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
                    if 200 <= response.status_code < 300:
                        return Record(
                            id=record_id or generate_record_id(),
                            domain=manifest.domain,
                            target=url,
                            target_kind=DEPLOYMENT_KIND_HTTP,
                            bundle_hash=manifest.bundle_hash,
                            status="deployed",
                            created_at=datetime.now(UTC),
                            response={
                                "status_code": str(response.status_code),
                                "body_sha256": response_sha,
                                "idempotency_key": idem,
                                "retry_count": str(attempt),
                            },
                        )
                    if response.status_code in {429, 503} and attempt < self.max_retries:
                        attempt += 1
                        _sleep(backoff)
                        backoff = min(backoff * 2, 8.0)
                        continue
                    raise Deploy(
                        f"deployment to {url} rejected with status "
                        f"{response.status_code} (body sha256={response_sha[:16]}…)"
                    )
            except httpx.HTTPError as error:
                last_error = Deploy(
                    f"deployment request failed: {error}"
                )
                if attempt >= self.max_retries:
                    raise last_error from error
                attempt += 1
                _sleep(backoff)
                backoff = min(backoff * 2, 8.0)
                continue
        if last_error is not None:
            raise last_error
        raise Deploy("deployment exhausted retries without a result")


def validate_headers(headers: Mapping[str, str] | None) -> None:
    """Reject empty, reserved, or carriage-return-bearing HTTP headers.

    Raises:
        Deploy: When a header name is empty, reserved, or
            contains CR/LF, or when a header value contains CR/LF.
    """
    if not headers:
        return
    for name, value in headers.items():
        if not name or not name.strip():
            raise Deploy("deployment header name must be non-empty")
        if "\r" in name or "\n" in name:
            raise Deploy(
                f"deployment header name contains CR/LF: {name!r}"
            )
        if "\r" in value or "\n" in value:
            raise Deploy(
                f"deployment header value for {name!r} contains CR/LF"
            )
        if name.lower() in _RESERVED_HEADERS:
            raise Deploy(
                f"deployment header name {name!r} is reserved and cannot be set"
            )
        if len(name) > 256:
            raise Deploy(
                f"deployment header name {name!r} exceeds 256 characters"
            )
        if len(value) > 8192:
            raise Deploy(
                f"deployment header value for {name!r} exceeds 8192 characters"
            )


def _read_bounded_body(response: httpx.Response) -> str:
    """Read the response body with a hard upper bound on bytes consumed."""
    body_bytes = bytearray()
    for chunk in response.iter_bytes(chunk_size=4096):
        body_bytes.extend(chunk)
        if len(body_bytes) >= HTTP_RESPONSE_READ_LIMIT:
            break
    return body_bytes[:HTTP_RESPONSE_READ_LIMIT].decode("utf-8", errors="replace")


def _is_finite(value: float) -> bool:
    """Return True when ``value`` is a finite number (not inf or NaN)."""
    return value == value and value not in (float("inf"), float("-inf"))


def _sleep(seconds: float) -> None:
    """Sleep helper that ignores zero/negative durations."""
    if seconds > 0:
        import time

        time.sleep(seconds)


def os_replace(src: Path, dst: Path) -> None:
    """Replace ``dst`` with ``src`` atomically (POSIX rename)."""
    import os

    os.replace(src, dst)


def os_fsync_directory(directory: Path) -> None:
    """fsync a directory to durably record file replacements.

    Best-effort: some platforms do not allow opening a directory fd
    for fsync. Failures are silently swallowed because the data is
    already on disk.
    """
    import os

    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def os_fsync(fd: int) -> None:
    """Flush an open file descriptor to durable storage."""
    import os

    os.fsync(fd)


def _rm_tmp(path: Path) -> None:
    """Best-effort removal of a temporary directory used for staging."""
    import shutil

    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def generate_record_id() -> str:
    """Return a fresh UUID-based deployment record identifier."""
    return uuid.uuid4().hex


__all__ = [
    "Bundler",
    "DEPLOYMENT_KIND_HTTP",
    "DEPLOYMENT_KIND_LOCAL",
    "Client",
    "Deploy",
    "Manifest",
    "Record",
    "HTTP_RESPONSE_BODY_LIMIT",
    "HTTP_RESPONSE_READ_LIMIT",
    "Pin",
    "Guard",
    "generate_record_id",
    "validate_headers",
]
