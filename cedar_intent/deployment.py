"""Deployment automation for compiled Cedar policies.

A :class:`BundleExporter` produces a self-contained deployment artifact
(a Cedar source bundle plus a manifest with a SHA-256 integrity hash).
A :class:`DeploymentClient` pushes the bundle to either a local directory
or a remote HTTP endpoint and records the deployment in the workspace.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .errors import DeploymentError
from .policies import CompiledPolicy, Policy

DEPLOYMENT_KIND_LOCAL = "local"
DEPLOYMENT_KIND_HTTP = "http"

HTTP_RESPONSE_BODY_LIMIT = 512


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
        """Return a JSON-friendly representation including the Cedar source."""
        return {
            "domain": self.domain,
            "bundle_hash": self.bundle_hash,
            "policy_ids": list(self.policy_ids),
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
            "cedar": self.cedar,
        }

    def to_manifest_payload(self) -> Mapping[str, Any]:
        """Return the manifest payload without the bundled Cedar source."""
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
        """Write ``manifest`` to ``directory`` and return the directory."""
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "bundle.cedar").write_text(manifest.cedar, encoding="utf-8")
        (directory / "manifest.json").write_text(
            json.dumps(manifest.to_manifest_payload(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return directory

    def read_directory(self, directory: Path) -> DeploymentManifest:
        """Read a previously written manifest back from ``directory``.

        Args:
            directory: Directory containing ``bundle.cedar`` and ``manifest.json``.

        Returns:
            The reconstructed :class:`DeploymentManifest`.

        Raises:
            DeploymentError: If the directory is missing files or the
                bundle hash does not match the manifest.
        """
        if not directory.exists() or not directory.is_dir():
            raise DeploymentError(f"deployment directory not found: {directory}")
        bundle_path = directory / "bundle.cedar"
        manifest_path = directory / "manifest.json"
        if not bundle_path.exists() or not manifest_path.exists():
            raise DeploymentError(
                f"deployment directory is missing bundle or manifest: {directory}"
            )
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        cedar_text = bundle_path.read_text(encoding="utf-8")
        expected_hash = data.get("bundle_hash")
        actual_hash = hashlib.sha256(cedar_text.encode("utf-8")).hexdigest()
        if expected_hash and expected_hash != actual_hash:
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


class DeploymentClient:
    """Push a :class:`DeploymentManifest` to a local directory or HTTP endpoint."""

    def __init__(self, *, timeout: float = 30) -> None:
        """Initialize the deployment client.

        Args:
            timeout: HTTP timeout in seconds for remote deployments.

        Raises:
            DeploymentError: If ``timeout`` is not strictly positive.
        """
        if timeout <= 0:
            raise DeploymentError("deployment timeout must be positive")
        self.timeout = timeout

    def deploy(
        self,
        manifest: DeploymentManifest,
        target: str,
        *,
        record_id: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> DeploymentRecord:
        """Push ``manifest`` to ``target`` (local path or http(s) URL)."""
        if not target.strip():
            raise DeploymentError("deployment target must be non-empty")
        parsed = urlparse(target)
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
        """Write ``manifest`` to ``directory`` and return the deployment record."""
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
        """POST ``manifest`` to ``url`` and return the deployment record."""
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
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                status_code = getattr(response, "status", 200)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise DeploymentError(f"deployment to {url} failed: {error}") from error
        status = "deployed" if 200 <= status_code < 300 else "rejected"
        if status != "deployed":
            raise DeploymentError(
                f"deployment to {url} rejected with status {status_code}: {body}"
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
    "generate_record_id",
]
