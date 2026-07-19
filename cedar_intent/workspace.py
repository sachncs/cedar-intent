"""Workspace orchestrator.

A :class:`Workspace` binds every cedar-intent concern together: it owns a
repository, loads schemas and requirements from disk, drives generators,
applies drafts, and exports validated policy bundles for embedded Cedar
applications.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .compiler import PolicyIntent, compile_intent
from .deployment import (
    BundleExporter,
    DeploymentClient,
    DeploymentManifest,
    DeploymentRecord,
)
from .errors import PolicyError, StorageError, WorkspaceError
from .generator import GenerationContext, GenerationResult, Generator
from .policies import CompiledPolicy, DraftPolicy, ExistingPolicy, Policy
from .requirements import Requirement, load_requirement, load_requirements
from .scenarios import Scenario, TestReport, load_scenarios, run_scenarios
from .schema import CedarSchema
from .scopes import ActionScope, PrincipalScope, ResourceScope
from .storage import (
    InMemoryRepository,
    Repository,
    SqliteRepository,
    StoredDraft,
    StoredPolicy,
    StoredReport,
)
from .validation import ValidationReport, validate_cedar
from .verification import VerificationReport, verify_policies

DEFAULT_STORAGE_FILENAME = "store.db"
DEFAULT_REQUIREMENTS_DIRNAME = "requirements"
DEFAULT_SCHEMA_FILENAME = "schema.json"
DEFAULT_SCENARIOS_FILENAME = "scenarios.json"


@dataclass
class Workspace:
    """Top-level cedar-intent orchestrator for a single organization workspace.

    Attributes:
        root: Filesystem root of the workspace.
        repository: Storage backend used by the workspace.
        storage_path: Path to the workspace's persistent SQLite database.
    """

    root: Path
    repository: Repository
    storage_path: Path

    @classmethod
    def open(cls, path: Path) -> Workspace:
        """Open an existing workspace at ``path``.

        Args:
            path: Filesystem path of the workspace root.

        Returns:
            A :class:`Workspace` backed by a SQLite repository.

        Raises:
            WorkspaceError: If the path does not exist.
        """
        root = Path(path).resolve()
        if not root.exists() or not root.is_dir():
            raise WorkspaceError(f"workspace root not found: {root}")
        storage_path = root / ".cedar-intent" / DEFAULT_STORAGE_FILENAME
        repository = SqliteRepository(storage_path)
        return cls(root=root, repository=repository, storage_path=storage_path)

    @classmethod
    def create(cls, path: Path) -> Workspace:
        """Create a new workspace at ``path`` and return it.

        Args:
            path: Filesystem path that will become the workspace root.

        Returns:
            A freshly created :class:`Workspace`.
        """
        root = Path(path).resolve()
        root.mkdir(parents=True, exist_ok=True)
        (root / ".cedar-intent").mkdir(exist_ok=True)
        storage_path = root / ".cedar-intent" / DEFAULT_STORAGE_FILENAME
        repository = SqliteRepository(storage_path)
        return cls(root=root, repository=repository, storage_path=storage_path)

    @classmethod
    def in_memory(cls, path: Path | None = None) -> Workspace:
        """Build an in-memory workspace for tests or ephemeral sessions."""
        root = (path or Path.cwd()).resolve()
        return cls(
            root=root, repository=InMemoryRepository(), storage_path=root / "<memory>"
        )

    def requirements_directory(self, domain: str) -> Path:
        """Return the directory holding requirement files for ``domain``."""
        return self.root / domain / DEFAULT_REQUIREMENTS_DIRNAME

    def schema_path(self, domain: str) -> Path:
        """Return the path of the schema file for ``domain``."""
        return self.root / domain / DEFAULT_SCHEMA_FILENAME

    def scenarios_path(self, domain: str) -> Path:
        """Return the path of the scenarios file for ``domain``."""
        return self.root / domain / DEFAULT_SCENARIOS_FILENAME

    def policies_directory(self, domain: str) -> Path:
        """Return the directory holding imported Cedar policy files for ``domain``."""
        return self.root / domain / "policies"

    def init_domain(self, domain: str) -> Path:
        """Create the directory layout for ``domain`` if it does not exist."""
        self.requirements_directory(domain).mkdir(parents=True, exist_ok=True)
        self.policies_directory(domain).mkdir(parents=True, exist_ok=True)
        if not self.schema_path(domain).exists():
            self.schema_path(domain).write_text(
                json.dumps({domain: {"entityTypes": {}, "actions": {}}}, indent=2),
                encoding="utf-8",
            )
        return self.schema_path(domain)

    def load_schema(self, domain: str) -> CedarSchema:
        """Load the Cedar schema for ``domain``."""
        return CedarSchema.from_json_file(self.schema_path(domain))

    def load_scenarios(self, domain: str) -> list[Scenario]:
        """Load authorization scenarios for ``domain``.

        Returns an empty list when the scenarios file does not exist.
        """
        path = self.scenarios_path(domain)
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise WorkspaceError(f"scenarios file must contain a list: {path}")
        return load_scenarios(data)

    def add_requirement_file(self, path: Path) -> Requirement:
        """Add a requirement from ``path`` and persist it."""
        requirement = load_requirement(path, workspace_root=self.root)
        self.repository.add_requirement(requirement)
        return requirement

    def add_requirement_directory(self, domain: str) -> list[Requirement]:
        """Add every requirement in the domain's requirements directory."""
        added: list[Requirement] = []
        for requirement in load_requirements(
            self.requirements_directory(domain), workspace_root=self.root
        ):
            self.repository.add_requirement(requirement)
            added.append(requirement)
        return added

    def get_requirement(self, requirement_id: str) -> Requirement:
        """Return the requirement with the given identifier."""
        return self.repository.get_requirement(requirement_id)

    def list_requirements(self, domain: str | None = None) -> list[Requirement]:
        """Return requirements, optionally filtered by domain."""
        return list(self.repository.list_requirements(domain))

    def remove_requirement(self, requirement_id: str) -> None:
        """Remove the requirement with the given identifier."""
        self.repository.remove_requirement(requirement_id)

    def import_existing_policies(self, domain: str) -> list[ExistingPolicy]:
        """Import Cedar files from the domain's policies directory."""
        existing: list[ExistingPolicy] = []
        directory = self.policies_directory(domain)
        if not directory.exists():
            return existing
        for path in sorted(directory.glob("*.cedar")):
            cedar = path.read_text(encoding="utf-8").strip()
            requirement = Requirement(
                id=path.stem,
                text=f"Imported from {path.name}",
                domain=domain,
                source_path=path,
                created_at=datetime.now(UTC),
            )
            self.repository.add_requirement(requirement)
            policy = ExistingPolicy.from_requirement(requirement, cedar=cedar)
            existing.append(policy)
            self.upsert_compiled(
                CompiledPolicy(
                    id=policy.id,
                    requirement=requirement,
                    cedar=cedar,
                )
            )
        return existing

    def upsert_compiled(self, policy: Policy) -> None:
        """Persist ``policy`` to the repository."""
        # ExistingPolicy with no parsed intent raises PolicyError from
        # to_intent(); that is the expected case, not a failure. The
        # intent field is stored as None and the workspace falls back
        # to it at verification time through intent_for_verification.
        intent: PolicyIntent | None = None
        try:
            intent = policy.to_intent()
        except PolicyError:
            intent = None
        stored = StoredPolicy(
            id=policy.id,
            domain=policy.requirement.domain,
            requirement_id=policy.requirement.id,
            intent=intent,
            cedar=policy.cedar,
            status=policy.kind(),
            created_at=policy.created_at,
            updated_at=datetime.now(UTC),
        )
        self.repository.upsert_policy(stored)

    def create_draft(
        self,
        requirement_id: str,
        *,
        principal: PrincipalScope | None = None,
        action: ActionScope | None = None,
        resource: ResourceScope | None = None,
        policy_id: str | None = None,
    ) -> DraftPolicy:
        """Create a :class:`DraftPolicy` for the given requirement and scopes."""
        requirement = self.repository.get_requirement(requirement_id)
        return DraftPolicy.from_requirement(
            requirement,
            principal=principal,
            action=action,
            resource=resource,
            policy_id=policy_id,
        )

    def list_existing_policies(self, domain: str) -> list[ExistingPolicy]:
        """Return existing policies for ``domain`` as :class:`ExistingPolicy` objects."""
        result: list[ExistingPolicy] = []
        for stored in self.repository.list_policies(domain=domain):
            requirement = self.repository.get_requirement(stored.requirement_id or stored.id)
            result.append(
                ExistingPolicy(
                    id=stored.id,
                    requirement=requirement,
                    cedar=stored.cedar,
                    parsed_intent=stored.intent,
                )
            )
        return result

    def list_compiled_policies(self, domain: str) -> list[CompiledPolicy]:
        """Return the compiled policies for ``domain`` as :class:`CompiledPolicy` objects."""
        result: list[CompiledPolicy] = []
        for stored in self.repository.list_policies(domain=domain):
            if stored.status != "compiled":
                continue
            requirement_id = stored.requirement_id or stored.id
            # Skip orphan policies whose backing requirement has been
            # deleted from the store; the foreign key on policies.requirement_id
            # is ON DELETE SET NULL, so this can happen in practice.
            try:
                requirement = self.repository.get_requirement(requirement_id)
            except StorageError:
                continue
            result.append(
                CompiledPolicy(
                    id=stored.id,
                    requirement=requirement,
                    cedar=stored.cedar,
                    intent=stored.intent,
                )
            )
        return result

    def generate_draft(
        self,
        draft: DraftPolicy,
        schema: CedarSchema,
        generator: Generator,
        *,
        existing: Sequence[Policy] = (),
    ) -> tuple[DraftPolicy, GenerationResult]:
        """Run ``generator`` against ``draft`` and persist the resulting proposal."""
        result = generator.generate(build_generation_context(draft, schema, existing))
        proposal = result.proposal
        qualified_intent = qualify_intent(proposal.intent, schema)
        compiled_source = compile_intent(qualified_intent)
        new_draft = DraftPolicy(
            id=draft.id,
            requirement=draft.requirement,
            cedar=compiled_source.cedar,
            created_at=datetime.now(UTC),
            principal=qualified_intent.principal,
            action=qualified_intent.action,
            resource=qualified_intent.resource,
            intent=qualified_intent,
            unresolved=proposal.unresolved,
            status="proposed",
            notes=proposal.notes,
            model=result.model,
            request_id=result.request_id,
        )
        self.repository.record_draft(
            build_stored_draft(new_draft, result, compiled_source.cedar)
        )
        return new_draft, result

    def verify_domain(self, domain: str, schema: CedarSchema) -> VerificationReport:
        """Run static verification on a domain's compiled policies."""
        policies = self.list_compiled_policies(domain)
        requirement_ids = [
            requirement.id for requirement in self.repository.list_requirements(domain=domain)
        ]
        return verify_policies(
            domain=domain,
            policies=policies,
            requirement_ids=requirement_ids,
            action_names=sorted(schema.action_names()),
            entity_type_names=sorted(schema.entity_type_names()),
        )

    def build_bundle(
        self,
        domain: str,
        *,
        metadata: Mapping[str, str] | None = None,
    ) -> DeploymentManifest:
        """Build a deployment manifest for ``domain`` from compiled policies."""
        policies = self.list_compiled_policies(domain)
        return BundleExporter().build(domain, policies, metadata=metadata)

    def write_bundle(self, manifest: DeploymentManifest, directory: Path) -> Path:
        """Write a manifest to ``directory`` without recording a deployment."""
        return BundleExporter().write_directory(manifest, directory)

    def deploy(
        self,
        domain: str,
        target: str,
        *,
        timeout: float = 30,
        headers: Mapping[str, str] | None = None,
    ) -> DeploymentRecord:
        """Build a manifest and push it to ``target``.

        Args:
            domain: Domain to deploy.
            target: Local directory path or ``http(s)://`` URL.
            timeout: HTTP timeout in seconds.
            headers: Optional HTTP headers.

        Returns:
            The persisted :class:`DeploymentRecord`.
        """
        manifest = self.build_bundle(domain)
        client = DeploymentClient(timeout=timeout)
        record = client.deploy(manifest, target, headers=headers)
        self.repository.record_deployment(record)
        return record

    def list_deployments(self, domain: str | None = None) -> list[DeploymentRecord]:
        """Return deployment records, optionally filtered by domain."""
        return list(self.repository.list_deployments(domain=domain))

    def apply(
        self,
        draft: DraftPolicy,
        schema: CedarSchema,
        *,
        scenarios: Sequence[Scenario] = (),
        entities: Sequence[Mapping[str, Any]] = (),
    ) -> CompiledPolicy:
        """Compile, validate, and persist ``draft`` as a :class:`CompiledPolicy`."""
        if draft.cedar is None or not draft.cedar.strip():
            raise WorkspaceError(
                f"draft {draft.id} has no Cedar source; call generate before apply"
            )
        if draft.unresolved:
            raise WorkspaceError(
                f"draft {draft.id} has unresolved items: {', '.join(draft.unresolved)}"
            )
        report = validate_cedar([draft.cedar], schema)
        self.repository.record_report(
            build_stored_report(draft.id, "validation", report)
        )
        if scenarios:
            scenario_list: list[Scenario] = list(scenarios)
            test_report = draft.test(
                schema, scenario_list, entities=resolve_test_entities(entities)
            )
            self.repository.record_report(
                build_stored_report(draft.id, "test", test_report)
            )
            if not test_report.passed:
                failures = [
                    result for result in test_report.results if not result.passed
                ]
                raise WorkspaceError(
                    f"draft {draft.id} failed scenarios: "
                    + ", ".join(failure.scenario.name for failure in failures)
                )
        compiled = CompiledPolicy(
            id=draft.id,
            requirement=draft.requirement,
            cedar=report.formatted[0] if report.formatted else draft.cedar,
            intent=draft.intent,
            created_at=datetime.now(UTC),
        )
        self.upsert_compiled(compiled)
        return compiled

    def apply_for_requirement(
        self,
        requirement_id: str,
        schema: CedarSchema,
        *,
        scopes: tuple[PrincipalScope | None, ActionScope | None, ResourceScope | None] = (
            None,
            None,
            None,
        ),
        scenarios: Sequence[Scenario] = (),
    ) -> CompiledPolicy:
        """Apply the most recent draft that addresses ``requirement_id``.

        Looks up the requirement, finds the latest stored draft for it,
        and applies that draft.

        Args:
            requirement_id: Identifier of the requirement to apply.
            schema: Cedar schema the draft must validate against.
            scopes: Optional ``(principal, action, resource)`` scopes to
                seed the empty draft placeholder.
            scenarios: Optional scenarios to run during validation.

        Returns:
            The persisted :class:`CompiledPolicy`.

        Raises:
            WorkspaceError: If no draft exists for the requirement.
        """
        requirement = self.repository.get_requirement(requirement_id)
        placeholder = DraftPolicy.from_requirement(
            requirement,
            principal=scopes[0],
            action=scopes[1],
            resource=scopes[2],
        )
        stored_draft = self.repository.latest_draft(placeholder.id)
        draft = DraftPolicy(
            id=stored_draft.policy_id,
            requirement=requirement,
            cedar=stored_draft.cedar,
            unresolved=stored_draft.unresolved,
        )
        return self.apply(draft, schema, scenarios=scenarios)

    def validate_policies(self, domain: str, schema: CedarSchema) -> ValidationReport:
        """Validate every persisted compiled policy in ``domain``."""
        policies = [
            policy.cedar
            for policy in self.list_compiled_policies(domain)
            if policy.cedar
        ]
        if not policies:
            raise WorkspaceError(f"no compiled policies for domain {domain!r}")
        return validate_cedar(policies, schema)

    def test_domain(
        self,
        domain: str,
        schema: CedarSchema,
        *,
        entities: Sequence[Mapping[str, Any]] = (),
    ) -> TestReport:
        """Run every scenario for ``domain`` against its compiled policies."""
        scenarios = self.load_scenarios(domain)
        if not scenarios:
            raise WorkspaceError(f"no scenarios for domain {domain!r}")
        policies = [
            policy.cedar
            for policy in self.list_compiled_policies(domain)
            if policy.cedar
        ]
        if not policies:
            raise WorkspaceError(f"no compiled policies for domain {domain!r}")
        return run_scenarios(policies, list(entities), scenarios, schema=schema)

    def export_domain(self, domain: str, output: Path) -> Path:
        """Write a Cedar bundle for ``domain`` to ``output``."""
        policies = self.list_compiled_policies(domain)
        if not policies:
            raise WorkspaceError(f"no policies to export for domain {domain!r}")
        output.parent.mkdir(parents=True, exist_ok=True)
        bundle = "\n\n".join(policy.cedar for policy in policies if policy.cedar)
        output.write_text(bundle + "\n", encoding="utf-8")
        return output

    def close(self) -> None:
        """Close any underlying resources owned by the repository."""
        if hasattr(self.repository, "close") and callable(self.repository.close):
            self.repository.close()


def build_generation_context(
    draft: DraftPolicy,
    schema: CedarSchema,
    existing: Sequence[Policy],
) -> GenerationContext:
    """Build a :class:`GenerationContext` for a draft and existing policies."""
    existing_intents: list[PolicyIntent] = []
    for policy in existing:
        # Existing policies with no parsed intent are excluded from the
        # generation context; the LLM only sees policies it can reason
        # about. Failing to parse an existing policy must not block the
        # entire draft.
        try:
            existing_intents.append(policy.to_intent())
        except PolicyError:
            continue
    return GenerationContext(
        requirement=draft.requirement,
        schema=schema,
        principal=draft.principal,
        action=draft.action,
        resource=draft.resource,
        existing=tuple(existing_intents),
    )


def build_stored_draft(
    draft: DraftPolicy,
    result: GenerationResult,
    cedar: str,
) -> StoredDraft:
    """Build a :class:`StoredDraft` from a draft and a generation result."""
    return StoredDraft(
        id=str(uuid.uuid4()),
        policy_id=draft.id,
        model=result.model,
        request_id=result.request_id,
        unresolved=draft.unresolved,
        cedar=cedar,
        created_at=datetime.now(UTC),
    )


def build_stored_report(
    policy_id: str,
    kind: str,
    report: ValidationReport | TestReport,
) -> StoredReport:
    """Build a :class:`StoredReport` from a validation or test report."""
    return StoredReport(
        policy_id=policy_id,
        kind=kind,
        passed=report.passed,
        payload=dict(report.to_dict()),
        created_at=datetime.now(UTC),
    )


def qualify_intent(intent: PolicyIntent, schema: CedarSchema) -> PolicyIntent:
    """Return a copy of ``intent`` with namespace-qualified type names."""
    qualified_principal = PrincipalScope(
        kind=intent.principal.kind,
        type_name=schema.qualify_type_name(intent.principal.type_name),
        entity_id=intent.principal.entity_id,
        group_type=schema.qualify_type_name(intent.principal.group_type),
        group_id=intent.principal.group_id,
    )
    qualified_resource = ResourceScope(
        kind=intent.resource.kind,
        type_name=schema.qualify_type_name(intent.resource.type_name),
        entity_id=intent.resource.entity_id,
        parent_type=schema.qualify_type_name(intent.resource.parent_type),
        parent_id=intent.resource.parent_id,
    )
    qualified_action = ActionScope(
        kind=intent.action.kind,
        name=intent.action.name,
        group=intent.action.group,
        namespace=find_action_namespace(intent.action, schema),
    )
    return PolicyIntent(
        id=intent.id,
        requirement_id=intent.requirement_id,
        effect=intent.effect,
        principal=qualified_principal,
        action=qualified_action,
        resource=qualified_resource,
        when_clauses=intent.when_clauses,
        unless_clauses=intent.unless_clauses,
        notes=intent.notes,
    )


def find_action_namespace(action: ActionScope, schema: CedarSchema) -> str | None:
    """Return the namespace that owns the given action, or ``None``."""
    for namespace, declaration in schema.source.items():
        if not isinstance(namespace, str) or not isinstance(declaration, Mapping):
            continue
        actions = declaration.get("actions", {})
        if not isinstance(actions, Mapping):
            continue
        identifier = action.name or action.group
        if identifier and identifier in actions:
            return namespace
    return action.namespace


def resolve_test_entities(
    entities: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Normalize test entities for passing into the Cedar engine."""
    return [dict(entity) for entity in entities]


__all__ = [
    "DEFAULT_REQUIREMENTS_DIRNAME",
    "DEFAULT_SCHEMA_FILENAME",
    "DEFAULT_SCENARIOS_FILENAME",
    "DEFAULT_STORAGE_FILENAME",
    "Workspace",
    "load_requirement",
    "load_requirements",
]
