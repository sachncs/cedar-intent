"""Domain dataclass — the rich mutable object the Space operates on.

A :class:`Domain` carries the mutable state the user passes around.
Space methods read and mutate a Domain in place; the Domain is what
the user passes to ``space.export``, ``space.existing_policies``,
etc.

Mutations funnel through :meth:`Domain.mutate` so callers cannot
accidentally bypass the orchestrator's invariants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .need import Need
from .policy import Compiled, Existing


@dataclass
class Domain:
    """One authorization domain inside a Space.

    Attributes:
        name: Domain identifier (e.g., ``"hr"``).
        root: Filesystem root of the domain (workspace/<name>/).
        schema_path: Path to the schema file.
        scenarios_path: Path to the scenarios file.
        requirements_dir: Path to the requirements directory.
        policies_dir: Path to the policies directory.
        needs: Requirements registered in this domain.
        cases: Authorization scenarios loaded for this domain.
        policies: Compiled policies in this domain.
        drafts: Draft history for this domain.
        manifests: Deployment manifests produced for this domain.
        bundles: Filesystem paths of written bundles.
        reports: Verification/validation/test reports keyed by id.
        schema_loaded: The loaded Schema, if any.
        verified_at: When verification last ran.
    """

    name: str
    root: Path
    schema_path: Path
    scenarios_path: Path
    requirements_dir: Path
    policies_dir: Path
    needs: list[Need] = field(default_factory=list)
    cases: list[Any] = field(default_factory=list)  # Case, forward-refed
    policies: list[Compiled] = field(default_factory=list)
    drafts: list[Any] = field(default_factory=list)  # DraftStored, forward-refed
    manifests: list[Any] = field(default_factory=list)  # Manifest, forward-refed
    bundles: list[Path] = field(default_factory=list)
    reports: dict[str, Any] = field(default_factory=dict)
    schema_loaded: Any | None = None  # Schema, forward-refed
    verified_at: datetime | None = None

    def mutate(self, **changes: object) -> None:
        """Update fields in place. Single verb for all field updates.

        Raises:
            Space: When ``changes`` contains a key that is not a
                declared field.
        """
        from .error import Space

        for key, value in changes.items():
            if not hasattr(self, key):
                raise Space(f"Domain has no field {key!r}")
            setattr(self, key, value)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly representation of the domain state."""
        return {
            "name": self.name,
            "root": str(self.root),
            "schema_path": str(self.schema_path),
            "scenarios_path": str(self.scenarios_path),
            "requirements_dir": str(self.requirements_dir),
            "policies_dir": str(self.policies_dir),
            "needs": [need.id for need in self.needs],
            "cases": [case.name for case in self.cases],
            "policies": [policy.id for policy in self.policies],
            "drafts": [draft.id for draft in self.drafts],
            "manifests": [manifest.domain for manifest in self.manifests],
            "bundles": [str(path) for path in self.bundles],
            "reports": list(self.reports.keys()),
        }

    @classmethod
    def create(cls, name: str, root: Path) -> Domain:
        """Create a new domain directory and return an empty Domain."""
        requirements_dir = root / "requirements"
        policies_dir = root / "policies"
        requirements_dir.mkdir(parents=True, exist_ok=True)
        policies_dir.mkdir(parents=True, exist_ok=True)
        schema_path = root / "schema.json"
        scenarios_path = root / "scenarios.json"
        return cls(
            name=name,
            root=root,
            schema_path=schema_path,
            scenarios_path=scenarios_path,
            requirements_dir=requirements_dir,
            policies_dir=policies_dir,
        )

    @classmethod
    def load(
        cls,
        name: str,
        root: Path,
        schema: Any | None = None,
    ) -> Domain:
        """Load an existing domain.

        Returns a Domain with paths populated. The caller may supply
        a Schema to set ``schema_loaded``.
        """
        domain = cls.create(name=name, root=root)
        if schema is not None:
            domain.mutate(schema_loaded=schema)
        return domain

    def refresh(self) -> None:
        """Reload the domain's needs and policies from disk.

        Reads the requirements directory and policies directory and
        re-parses any Cedar files.
        """
        # Re-scan the requirements directory.
        from .need import Need, load_requirement

        self.needs = []
        if self.requirements_dir.exists():
            for path in sorted(self.requirements_dir.glob("*.md")):
                try:
                    self.needs.append(load_requirement(path))
                except Exception:  # noqa: BLE001
                    continue

        # Re-scan the policies directory.

        self.policies = []
        if self.policies_dir.exists():
            for path in sorted(self.policies_dir.glob("*.cedar")):
                cedar = path.read_text(encoding="utf-8").strip()
                try:
                    self.policies.append(
                        Existing.from_requirement(
                            Need(
                                id=path.stem,
                                text=f"Imported from {path.name}",
                                domain=self.name,
                                source_path=path,
                            ),
                            cedar=cedar,
                        )
                    )
                except Exception:  # noqa: BLE001
                    continue


__all__ = ["Domain"]
