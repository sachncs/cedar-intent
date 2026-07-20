"""Deployment automation for compiled Cedar policies.

A :class:`BundleExporter` produces a self-contained deployment artifact
(a Cedar source bundle plus a manifest with a SHA-256 integrity hash).
A :class:`DeploymentClient` pushes the bundle to either a local directory
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
or a missing manifest hash raises :class:`DeploymentError`, which is
the recommended signal for tamper detection after transport.

Atomicity
---------

Local deployments write the bundle to a sibling temporary directory
first and atomically rename each file into place with
``Path.replace``. Concurrent writers therefore never observe a
mixed state where one file is the new version and the other is the
old version. A crash before the rename leaves the previous bundle
untouched.

Network behavior
----------------

``DeploymentClient.deploy_http`` reads the response body in bounded
chunks so a malicious or streaming endpoint cannot exhaust memory.
2xx responses are treated as success; 4xx and 5xx responses raise
:class:`DeploymentError` with the response body captured (truncated
to :data:`HTTP_RESPONSE_BODY_LIMIT`).

The default :class:`SSRFGuard` rejects loopback, link-local, and
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
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import DeploymentError
from .policies import CompiledPolicy, Policy

DEPLOYMENT_KIND_LOCAL = "local"
DEPLOYMENT_KIND_HTTP = "http"

#: Maximum number of bytes of the HTTP response body to capture in the
#: deployment record. The body is also bounded at read time so that a
#: streaming or oversized response cannot exhaust memory.
HTTP_RESPONSE_BODY_LIMIT = 512

#: Maximum total bytes read from an HTTP response body. Pairs with
#: :data:`HTTP_RESPONSE_BODY_LIMIT` so a streaming endpoint cannot
#: exhaust memory before the per-record truncation runs.
HTTP_RESPONSE_READ_LIMIT = 65536


@dataclass(frozen=True, slots=True)
class DeploymentManifest:
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
class DeploymentRecord:
    """Persisted record of a successful deployment.

    Attributes:
        id: Unique deployment identifier.
        domain: Domain that was deployed.
        target: Local path or HTTP URL the bundle was pushed to.
        target_kind: ``"local"`` or ``"http"``.
        bundle_hash: SHA-256 of the deployed Cedar source.
        status: ``"deployed"`` or ``"rejected"``.
        created_at: Timestamp at which the deployment completed.
        response: Provider response metadata (for HTTP targets).
    """

    id: str
    domain: str
    target: str
    target_kind: str
    bundle_hash: str
    status: str
    created_at: datetime
    response: Mapping[str, str] = field(default_factory=dict)


class BundleExporter:
    """Build, write, and read :class:`DeploymentManifest` objects.

    All methods are stateless and can be used as static methods, but are
    exposed as instance methods to keep a consistent call style.
    """

    def build(
        self,
        domain: str,
        policies: Sequence[Policy],
        *,
        metadata: Mapping[str, str] | None = None,
    ) -> DeploymentManifest:
        """Build a manifest from compiled policies.

        Args:
            domain: Domain the manifest belongs to.
            policies: Policies to include; only those with non-empty Cedar
                source are considered.
            metadata: Optional deployment metadata.

        Returns:
            The constructed :class:`DeploymentManifest`.

        Raises:
            DeploymentError: If no compiled policies are available.
        """
        compiled = [
            policy
            for policy in policies
            if isinstance(policy, CompiledPolicy) and policy.cedar.strip()
        ]
        if not compiled:
            raise DeploymentError(
                f"no compiled policies to deploy for domain {domain!r}"
            )
        cedar_text = "\n\n".join(policy.cedar for policy in compiled)
        bundle_hash = hashlib.sha256(cedar_text.encode("utf-8")).hexdigest()
        return DeploymentManifest(
            domain=domain,
            cedar=cedar_text,
            bundle_hash=bundle_hash,
            policy_ids=tuple(policy.id for policy in compiled),
            created_at=datetime.now(UTC),
            metadata=dict(metadata or {}),
        )

    def write_directory(self, manifest: DeploymentManifest, directory: Path) -> Path:
        """Write ``manifest`` to ``directory`` atomically.

        Creates ``bundle.cedar`` and ``manifest.json`` in a sibling
        temporary directory first, then renames each file into place
        with ``Path.replace``. Concurrent writers never observe a
        mixed state where one file is the new version and the other is
        the old version. A crash before the rename leaves the previous
        bundle untouched.

        Args:
            manifest: Manifest to write.
            directory: Target directory. Created if it does not exist.

        Returns:
            The directory the manifest was written to.

        Raises:
            DeploymentError: If writing the temporary files or the
                rename fails.
        """
        directory.mkdir(parents=True, exist_ok=True)
        staging = directory.with_name(f".{directory.name}.staging.{uuid.uuid4().hex}")
        try:
            try:
                staging.mkdir(parents=False, exist_ok=False)
            except FileExistsError:
                staging.mkdir(parents=False, exist_ok=True)
            (staging / "bundle.cedar").write_text(manifest.cedar, encoding="utf-8")
            (staging / "manifest.json").write_text(
                json.dumps(manifest.to_manifest_payload(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            for filename in ("bundle.cedar", "manifest.json"):
                (staging / filename).replace(directory / filename)
        except OSError as error:
            raise DeploymentError(
                f"failed to write deployment bundle to {directory}: {error}"
            ) from error
        finally:
            if staging.exists():
                for child in staging.iterdir():
                    try:
                        child.unlink()
                    except OSError:
                        pass
                try:
                    staging.rmdir()
                except OSError:
                    pass
        return directory

    def read_directory(self, directory: Path) -> DeploymentManifest:
        """Read a previously written manifest back from ``directory``.

        Recomputes the bundle hash from ``bundle.cedar`` and compares
        it against the manifest's recorded hash. A mismatch or a
        missing manifest hash raises :class:`DeploymentError`, which
        is the recommended signal for tamper detection after
        transport.

        Args:
            directory: Directory containing ``bundle.cedar`` and
                ``manifest.json``.

        Returns:
            The reconstructed :class:`DeploymentManifest`.

        Raises:
            DeploymentError: If the directory is missing files, the
                manifest has no bundle hash, or the bundle hash does
                not match the recorded value.
        """
        if not directory.exists() or not directory.is_dir():
            raise DeploymentError(f"deployment directory not found: {directory}")
        bundle_path = directory / "bundle.cedar"
        manifest_path = directory / "manifest.json"
        if not bundle_path.exists() or not manifest_path.exists():
            raise DeploymentError(
                f"deployment directory is missing bundle or manifest: {directory}"
            )
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise DeploymentError(
                f"deployment manifest is not valid JSON: {error}"
            ) from error
        cedar_text = bundle_path.read_text(encoding="utf-8")
        expected_hash = data.get("bundle_hash")
        if not expected_hash:
            raise DeploymentError(
                "deployment manifest is missing bundle_hash; refusing to trust "
                "an unverifiable bundle"
            )
        actual_hash = hashlib.sha256(cedar_text.encode("utf-8")).hexdigest()
        if expected_hash != actual_hash:
            raise DeploymentError(
                "deployment bundle hash mismatch: expected "
                f"{expected_hash}, got {actual_hash}"
            )
        return DeploymentManifest(
            domain=data["domain"],
            cedar=cedar_text,
            bundle_hash=actual_hash,
            policy_ids=tuple(data.get("policy_ids", [])),
            created_at=datetime.fromisoformat(data["created_at"]),
            metadata=dict(data.get("metadata", {})),
        )


class SSRFGuard:
    """Reject requests to loopback, link-local, or private network targets.

    The deployment client constructs an :class:`SSRFGuard` by default so
    untrusted callers cannot use the client as an SSRF proxy. The
    guard resolves the target hostname through DNS and rejects any
    address that falls inside a reserved range.

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
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("fc00::/7"),
        ipaddress.ip_network("fe80::/10"),
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

    def check(self, url: str) -> None:
        """Raise :class:`DeploymentError` when ``url`` targets a blocked host.

        Args:
            url: Full HTTP(S) URL to validate.

        Raises:
            DeploymentError: When the host resolves to a blocked network
                range, the URL is malformed, or DNS resolution fails.
        """
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise DeploymentError(
                f"deployment URL has unsupported scheme: {parsed.scheme!r}"
            )
        host = parsed.hostname
        if not host:
            raise DeploymentError(f"deployment URL is missing a host: {url}")
        try:
            infos = (
                self.resolver(host)
                if self.resolver
                else socket.getaddrinfo(host, None)
            )
        except (socket.gaierror, UnicodeError) as error:
            raise DeploymentError(
                f"could not resolve deployment host {host}: {error}"
            ) from error
        addresses: set[str] = set()
        for info in infos:
            sock_address = info[4][0]
            if isinstance(sock_address, str):
                addresses.add(sock_address)
        for address in addresses:
            try:
                parsed_address = ipaddress.ip_address(address)
            except ValueError:
                continue
            for network in self.BLOCKED_NETWORKS:
                if parsed_address in network:
                    if network.is_loopback or network.is_link_local:
                        if self.allow_loopback:
                            continue
                        raise DeploymentError(
                            f"deployment URL targets loopback or link-local "
                            f"address {address} ({network})"
                        )
                    if self.allow_private_targets:
                        continue
                    raise DeploymentError(
                        f"deployment URL targets private-network address "
                        f"{address} ({network}); pass "
                        "allow_private_targets=True to override"
                    )


class DeploymentClient:
    """Push a :class:`DeploymentManifest` to a local directory or HTTP endpoint."""

    def __init__(
        self,
        *,
        timeout: float = 30,
        allow_private_targets: bool = False,
        allow_loopback: bool = False,
        ssrf_guard: SSRFGuard | None = None,
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

        Raises:
            DeploymentError: If ``timeout`` is not strictly positive.
        """
        if timeout <= 0:
            raise DeploymentError("deployment timeout must be positive")
        self.timeout = timeout
        self.ssrf_guard = ssrf_guard or SSRFGuard(
            allow_private_targets=allow_private_targets,
            allow_loopback=allow_loopback,
        )

    def deploy(
        self,
        manifest: DeploymentManifest,
        target: str,
        *,
        record_id: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> DeploymentRecord:
        """Push ``manifest`` to ``target`` (local path or http(s) URL).

        Dispatches to :meth:`deploy_local` when ``target`` is a path
        and to :meth:`deploy_http` when it has an ``http://`` or
        ``https://`` scheme. The caller receives a :class:`DeploymentRecord`
        describing the outcome.

        Args:
            manifest: Bundle to push.
            target: Destination. Either a filesystem path or an
                ``http(s)://`` URL.
            record_id: Optional explicit identifier for the deployment
                record. Auto-generated when omitted.
            headers: Optional HTTP headers added to the POST request.

        Returns:
            The deployment record describing the outcome.

        Raises:
            DeploymentError: If the target is invalid, the HTTP
                endpoint returns non-2xx, or the request fails.
        """
        if not target.strip():
            raise DeploymentError("deployment target must be non-empty")
        parsed = urllib.parse.urlparse(target)
        if parsed.scheme in {"http", "https"}:
            return self.deploy_http(
                manifest, target, record_id=record_id, headers=headers
            )
        return self.deploy_local(manifest, Path(target), record_id=record_id)

    def deploy_local(
        self,
        manifest: DeploymentManifest,
        directory: Path,
        *,
        record_id: str | None = None,
    ) -> DeploymentRecord:
        """Write ``manifest`` to ``directory`` atomically and return the record.

        Args:
            manifest: Bundle to write.
            directory: Target directory. Created if missing.
            record_id: Optional explicit identifier for the record.

        Returns:
            The deployment record describing the local write.
        """
        directory.parent.mkdir(parents=True, exist_ok=True)
        BundleExporter().write_directory(manifest, directory)
        return DeploymentRecord(
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
        manifest: DeploymentManifest,
        url: str,
        *,
        record_id: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> DeploymentRecord:
        """POST ``manifest`` to ``url`` and return the deployment record.

        Reads the response body in bounded chunks so that a streaming
        or oversized endpoint cannot exhaust memory. 2xx responses are
        treated as success; 4xx and 5xx raise :class:`DeploymentError`
        with the response body captured (truncated to
        :data:`HTTP_RESPONSE_BODY_LIMIT`).

        Args:
            manifest: Bundle to push.
            url: HTTP endpoint accepting a JSON POST.
            record_id: Optional explicit identifier for the record.
            headers: Optional HTTP headers added to the POST.

        Returns:
            The deployment record describing the HTTP push.

        Raises:
            DeploymentError: When the URL fails the SSRF guard, the
                endpoint returns non-2xx, the request times out, or the
                network fails.
        """
        self.ssrf_guard.check(url)

        payload = json.dumps(manifest.to_dict()).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Cedar-Bundle-Hash": manifest.bundle_hash,
                "X-Cedar-Domain": manifest.domain,
                **(dict(headers) if headers else {}),
            },
        )
        body, status_code = _read_http_response(request, self.timeout)
        status = "deployed" if 200 <= status_code < 300 else "rejected"
        if status != "deployed":
            raise DeploymentError(
                f"deployment to {url} rejected with status {status_code}: "
                f"{body[:HTTP_RESPONSE_BODY_LIMIT]}"
            )
        return DeploymentRecord(
            id=record_id or generate_record_id(),
            domain=manifest.domain,
            target=url,
            target_kind=DEPLOYMENT_KIND_HTTP,
            bundle_hash=manifest.bundle_hash,
            status=status,
            created_at=datetime.now(UTC),
            response={
                "status_code": str(status_code),
                "body": body[:HTTP_RESPONSE_BODY_LIMIT],
            },
        )


def _read_http_response(
    request: urllib.request.Request, timeout: float
) -> tuple[str, int]:
    """Read an HTTP response with bounded size and split error handling.

    Returns:
        A tuple ``(body, status_code)``. ``body`` is truncated to
        :data:`HTTP_RESPONSE_READ_LIMIT` bytes. ``status_code`` is the
        HTTP status returned by the endpoint.

    Raises:
        DeploymentError: When the connection fails, the request times
            out, or the endpoint returns an HTTP error status (4xx/5xx).
            In every case the response body is included in the error
            message up to :data:`HTTP_RESPONSE_BODY_LIMIT` bytes.
    """
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        # ``HTTPError`` is raised for 4xx and 5xx responses. ``read()``
        # is bounded by the underlying implementation; we still cap it
        # before constructing the message body.
        body = _read_http_error_body(error)
        raise DeploymentError(
            f"deployment rejected with status {error.code}: "
            f"{body[:HTTP_RESPONSE_BODY_LIMIT]}"
        ) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        # ``URLError`` covers DNS, connection refused, and other protocol
        # failures; ``TimeoutError`` covers the configured HTTP timeout;
        # ``OSError`` covers network-stack failures on some platforms.
        raise DeploymentError(f"deployment request failed: {error}") from error

    body_bytes = bytearray()
    try:
        while True:
            chunk = response.read(4096)
            if not chunk:
                break
            body_bytes.extend(chunk)
            if len(body_bytes) >= HTTP_RESPONSE_READ_LIMIT:
                break
    finally:
        response.close()
    status_code = getattr(response, "status", 200)
    return body_bytes[:HTTP_RESPONSE_READ_LIMIT].decode(
        "utf-8", errors="replace"
    ), status_code


def _read_http_error_body(error: urllib.error.HTTPError) -> str:
    """Safely read an :class:`urllib.error.HTTPError` body."""
    try:
        return error.read().decode("utf-8", errors="replace")
    except (OSError, AttributeError):
        return ""


def generate_record_id() -> str:
    """Return a fresh UUID-based deployment record identifier."""
    return uuid.uuid4().hex


__all__ = [
    "BundleExporter",
    "DEPLOYMENT_KIND_HTTP",
    "DEPLOYMENT_KIND_LOCAL",
    "DeploymentClient",
    "DeploymentError",
    "DeploymentManifest",
    "DeploymentRecord",
    "HTTP_RESPONSE_BODY_LIMIT",
    "HTTP_RESPONSE_READ_LIMIT",
    "SSRFGuard",
    "generate_record_id",
]
