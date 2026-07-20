"""Workspace orchestrator.

A :class:`Workspace` binds every cedar-intent concern together: it owns a
repository, loads schemas and requirements from disk, drives generators,
applies drafts, and exports validated policy bundles for embedded Cedar
applications.

Lifecycle
---------

A typical session runs through these stages:

1. **Initialize** - :meth:`Workspace.create` or :meth:`Workspace.open`
   creates or loads the workspace layout and storage.
2. **Declare domain** - :meth:`Workspace.init_domain` creates the
   directory layout and an empty schema for a domain.
3. **Load requirements** - :meth:`Workspace.add_requirement_file` or
   :meth:`Workspace.add_requirement_directory` registers Markdown
   requirements.
4. **Generate draft** - :meth:`Workspace.generate_draft` runs a
   :class:`~cedar_intent.generator.Generator` against a draft and
   persists the proposal.
5. **Apply** - :meth:`Workspace.apply` or
   :meth:`Workspace.apply_for_requirement` validates, optionally runs
   scenarios, and persists a :class:`CompiledPolicy`.
6. **Verify** - :meth:`Workspace.verify_domain` flags shadowing,
   redundancy, and coverage gaps.
7. **Deploy** - :meth:`Workspace.build_bundle`,
   :meth:`Workspace.write_bundle`, and :meth:`Workspace.deploy` produce
   and push the deployment artifact.

Thread safety
-------------

A single :class:`Workspace` instance is safe for concurrent use from
multiple threads only when the underlying :class:`Repository` supports
it. The default :class:`SqliteRepository` serializes access through
its connection; for heavy parallel use, prefer one workspace per
thread.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

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
from .scopes import ActionScope, ConditionClause, PrincipalScope, ResourceScope
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
        """Build an in-memory workspace for tests or ephemeral sessions.

        Args:
            path: Optional filesystem path used as the workspace root.
                Defaults to the current directory.

        Returns:
            A :class:`Workspace` backed by an :class:`InMemoryRepository`.
        """
        root = (path or Path.cwd()).resolve()
        return cls(
            root=root, repository=InMemoryRepository(), storage_path=root / "<memory>"
        )

    def requirements_directory(self, domain: str) -> Path:
        """Return the directory holding requirement files for ``domain``.

        Args:
            domain: Domain identifier.

        Returns:
            Path under ``<workspace>/<domain>/requirements/``.
        """
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
        """Create the directory layout for ``domain`` if it does not exist.

        Creates ``<domain>/requirements/`` and ``<domain>/policies/``.
        If ``<domain>/schema.json`` is missing, seeds an empty schema
        with the domain name as the only namespace.

        Args:
            domain: Domain identifier to initialize.

        Returns:
            The path of the schema file after initialization.
        """
        self.requirements_directory(domain).mkdir(parents=True, exist_ok=True)
        self.policies_directory(domain).mkdir(parents=True, exist_ok=True)
        if not self.schema_path(domain).exists():
            self.schema_path(domain).write_text(
                json.dumps({domain: {"entityTypes": {}, "actions": {}}}, indent=2),
                encoding="utf-8",
            )
        return self.schema_path(domain)

    def load_schema(self, domain: str) -> CedarSchema:
        """Load and validate the Cedar schema for ``domain``.

        Args:
            domain: Domain identifier.

        Returns:
            A fully parsed :class:`CedarSchema`.

        Raises:
            cedar_intent.errors.ValidationError: If the schema file is
                missing or invalid.
        """
        return CedarSchema.from_json_file(self.schema_path(domain))

    def load_scenarios(self, domain: str) -> list[Scenario]:
        """Load authorization scenarios for ``domain``.

        Returns an empty list when the scenarios file does not exist.

        Args:
            domain: Domain identifier.

        Returns:
            A list of :class:`Scenario` objects.

        Raises:
            WorkspaceError: If the scenarios file exists but is not a
                JSON list.
        """
        path = self.scenarios_path(domain)
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise WorkspaceError(f"scenarios file must contain a list: {path}")
        return load_scenarios(data)

    def add_requirement_file(self, path: Path) -> Requirement:
        """Load a single requirement from ``path`` and persist it.

        Args:
            path: Markdown file to load.

        Returns:
            The loaded :class:`Requirement`.

        Raises:
            RequirementError: If the file is missing or malformed.
        """
        requirement = load_requirement(path, workspace_root=self.root)
        self.repository.add_requirement(requirement)
        return requirement

    def add_requirement_directory(self, domain: str) -> list[Requirement]:
        """Add every requirement in the domain's requirements directory.

        Args:
            domain: Domain identifier.

        Returns:
            The list of requirements loaded and persisted.
        """
        added: list[Requirement] = []
        for requirement in load_requirements(
            self.requirements_directory(domain), workspace_root=self.root
        ):
            self.repository.add_requirement(requirement)
            added.append(requirement)
        return added

    def get_requirement(self, requirement_id: str) -> Requirement:
        """Return the requirement with ``requirement_id``.

        Raises:
            StorageError: If no requirement exists with that id.
        """
        return self.repository.get_requirement(requirement_id)

    def list_requirements(self, domain: str | None = None) -> list[Requirement]:
        """Return requirements, optionally filtered by ``domain``."""
        return list(self.repository.list_requirements(domain))

    def remove_requirement(self, requirement_id: str) -> None:
        """Remove the requirement with ``requirement_id``.

        Raises:
            StorageError: If no requirement exists with that id.
        """
        self.repository.remove_requirement(requirement_id)

    def import_existing_policies(self, domain: str) -> list[ExistingPolicy]:
        """Import Cedar files from the domain's policies directory.

        Each ``*.cedar`` file in ``<domain>/policies/`` becomes a
        synthetic :class:`Requirement` (named after the file stem) plus
        an :class:`ExistingPolicy` carrying the Cedar source. The policy
        is also upserted as a :class:`CompiledPolicy` so it shows up in
        subsequent verification, test, and deployment runs.

        Args:
            domain: Domain identifier.

        Returns:
            The list of imported :class:`ExistingPolicy` objects, in
            alphabetical order by file name. Empty when the policies
            directory does not exist.
        """
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
        from .scope_json import action_scope_to_dict

        action_json: str | None = None
        if intent is not None:
            action_json = json.dumps(
                action_scope_to_dict(intent.action), sort_keys=True
            )
        stored = StoredPolicy(
            id=policy.id,
            domain=policy.requirement.domain,
            requirement_id=policy.requirement.id,
            intent=intent,
            cedar=policy.cedar,
            status=policy.kind(),
            created_at=policy.created_at,
            updated_at=datetime.now(UTC),
            action_scope_json=action_json,
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
        """Create a :class:`DraftPolicy` for the given requirement and scopes.

        Args:
            requirement_id: Identifier of the requirement to draft.
            principal: Optional principal scope. Defaults to ``any``.
            action: Optional action scope. Defaults to ``any``.
            resource: Optional resource scope. Defaults to ``any``.
            policy_id: Optional explicit identifier. Defaults to
                ``"draft-<requirement_id>"``.

        Returns:
            The constructed :class:`DraftPolicy`.

        Raises:
            StorageError: If the requirement does not exist.
        """
        requirement = self.repository.get_requirement(requirement_id)
        return DraftPolicy.from_requirement(
            requirement,
            principal=principal,
            action=action,
            resource=resource,
            policy_id=policy_id,
        )

    def list_existing_policies(self, domain: str) -> list[ExistingPolicy]:
        """Return existing policies for ``domain`` as :class:`ExistingPolicy` objects.

        Includes both true existing policies and any policy persisted
        with status ``"existing"``. The synthetic requirements
        produced by :meth:`import_existing_policies` are looked up by
        id when present.

        Args:
            domain: Domain identifier.

        Returns:
            A list of :class:`ExistingPolicy` in storage order.
        """
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
        """Return the compiled policies for ``domain`` as :class:`CompiledPolicy` objects.

        Args:
            domain: Domain identifier.

        Returns:
            A list of compiled policies whose storage status is
            ``"compiled"``. Orphan policies (those whose requirement has
            been deleted) are silently skipped.
        """
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
        """Run ``generator`` against ``draft`` and persist the resulting proposal.

        Args:
            draft: Draft whose scopes and requirement seed the generator.
            schema: Cedar schema the draft must conform to.
            generator: Generator that produces the typed intent.
            existing: Existing policies the generator should be aware of.

        Returns:
            A tuple of ``(updated_draft, generation_result)``. The
            returned draft carries the generator's Cedar and provenance.
        """
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
        """Run static verification on a domain's compiled policies.

        The verifier analyzes the deployed Cedar source of every
        compiled policy, so coverage and shadowing reflect what will
        actually run. Action groups are expanded through the schema so
        ``action in Action::"group"`` covers every member action.

        Args:
            domain: Domain identifier.
            schema: Cedar schema used to compute coverage.

        Returns:
            A :class:`VerificationReport` aggregating findings and
            coverage metrics.
        """
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
            actions_by_namespace=schema.actions_by_namespace(),
        )

    def build_bundle(
        self,
        domain: str,
        *,
        metadata: Mapping[str, str] | None = None,
    ) -> DeploymentManifest:
        """Build a deployment manifest for ``domain`` from compiled policies.

        Args:
            domain: Domain identifier.
            metadata: Optional deployment metadata included in the
                manifest.

        Returns:
            The constructed :class:`DeploymentManifest`.

        Raises:
            DeploymentError: If no compiled policies are available.
        """
        policies = self.list_compiled_policies(domain)
        return BundleExporter().build(domain, policies, metadata=metadata)

    def write_bundle(self, manifest: DeploymentManifest, directory: Path) -> Path:
        """Write a manifest to ``directory`` without recording a deployment.

        Args:
            manifest: Manifest to write.
            directory: Target directory. Created if it does not exist.

        Returns:
            The directory the manifest was written to.
        """
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
            headers: Optional HTTP headers added to the POST request.

        Returns:
            The persisted :class:`DeploymentRecord`.

        Raises:
            DeploymentError: If no compiled policies are available or
                the HTTP target returns non-2xx.
        """
        manifest = self.build_bundle(domain)
        client = DeploymentClient(timeout=timeout)
        record = client.deploy(manifest, target, headers=headers)
        self.repository.record_deployment(record)
        return record

    def list_deployments(self, domain: str | None = None) -> list[DeploymentRecord]:
        """Return deployment records, optionally filtered by ``domain``."""
        return list(self.repository.list_deployments(domain=domain))

    def apply(
        self,
        draft: DraftPolicy,
        schema: CedarSchema,
        *,
        scenarios: Sequence[Scenario] = (),
        entities: Sequence[Mapping[str, Any]] = (),
    ) -> CompiledPolicy:
        """Compile, validate, and persist ``draft`` as a :class:`CompiledPolicy`.

        Args:
            draft: Draft to apply.
            schema: Cedar schema to validate against.
            scenarios: Optional authorization scenarios to run.
            entities: Optional entities exposed to the Cedar engine.

        Returns:
            The persisted :class:`CompiledPolicy`.

        Raises:
            WorkspaceError: If the draft has no Cedar source, has
                unresolved items, or any scenario fails.
        """
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
        and applies that draft. The reconstructed :class:`DraftPolicy`
        carries the typed intent and original scopes read from the
        stored JSON columns, so verification and deployment see exactly
        what the generator produced.

        Args:
            requirement_id: Identifier of the requirement to apply.
            schema: Cedar schema the draft must validate against.
            scopes: Optional ``(principal, action, resource)`` scopes
                used to compute the draft's stable identifier.
            scenarios: Optional scenarios to run during validation.

        Returns:
            The persisted :class:`CompiledPolicy`.

        Raises:
            WorkspaceError: If no draft exists for the requirement.
        """
        from .scope_json import (
            action_scope_from_dict,
            principal_scope_from_dict,
            resource_scope_from_dict,
        )

        requirement = self.repository.get_requirement(requirement_id)
        placeholder = DraftPolicy.from_requirement(
            requirement,
            principal=scopes[0],
            action=scopes[1],
            resource=scopes[2],
        )
        try:
            stored_draft = self.repository.latest_draft(placeholder.id)
        except StorageError as error:
            raise WorkspaceError(
                f"no draft exists for requirement {requirement_id!r}; "
                "run 'cedar-intent policy generate' first"
            ) from error
        intent = intent_from_draft(stored_draft, placeholder.id, requirement_id)
        principal_payload = loads_optional_json(stored_draft.principal_scope_json)
        action_payload = loads_optional_json(stored_draft.action_scope_json)
        resource_payload = loads_optional_json(stored_draft.resource_scope_json)
        draft = DraftPolicy(
            id=stored_draft.policy_id,
            requirement=requirement,
            cedar=stored_draft.cedar,
            unresolved=stored_draft.unresolved,
            principal=principal_scope_from_dict(principal_payload)
            or placeholder.principal,
            action=action_scope_from_dict(action_payload) or placeholder.action,
            resource=resource_scope_from_dict(resource_payload) or placeholder.resource,
            intent=intent,
            status="proposed",
        )
        return self.apply(draft, schema, scenarios=scenarios)

    def validate_policies(self, domain: str, schema: CedarSchema) -> ValidationReport:
        """Validate every persisted compiled policy in ``domain``.

        Args:
            domain: Domain identifier.
            schema: Cedar schema to validate against.

        Returns:
            A :class:`ValidationReport` describing the outcome.

        Raises:
            WorkspaceError: If no compiled policies exist for ``domain``.
        """
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
        """Run every scenario for ``domain`` against its compiled policies.

        Args:
            domain: Domain identifier.
            schema: Cedar schema for scenario evaluation.
            entities: Optional entities exposed to the Cedar engine.

        Returns:
            A :class:`TestReport` summarizing the outcomes.

        Raises:
            WorkspaceError: If no scenarios or no compiled policies exist.
        """
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
        """Write a Cedar bundle for ``domain`` to ``output``.

        Concatenates every compiled policy for ``domain`` into a single
        file separated by blank lines. Use this when the embedded Cedar
        engine reads policies from a single file.

        Args:
            domain: Domain identifier.
            output: Destination path. Parent directories are created.

        Returns:
            The path the bundle was written to.

        Raises:
            WorkspaceError: If no compiled policies exist for ``domain``.
        """
        policies = self.list_compiled_policies(domain)
        if not policies:
            raise WorkspaceError(f"no policies to export for domain {domain!r}")
        output.parent.mkdir(parents=True, exist_ok=True)
        bundle = "\n\n".join(policy.cedar for policy in policies if policy.cedar)
        output.write_text(bundle + "\n", encoding="utf-8")
        return output

    def close(self) -> None:
        """Close any underlying resources owned by the repository.

        Idempotent: subsequent calls are no-ops. Backends without a
        ``close`` attribute are silently ignored (the in-memory
        repository has nothing to release).
        """
        if hasattr(self.repository, "close") and callable(self.repository.close):
            self.repository.close()


def build_generation_context(
    draft: DraftPolicy,
    schema: CedarSchema,
    existing: Sequence[Policy],
) -> GenerationContext:
    """Build a :class:`GenerationContext` for a draft and existing policies.

    Args:
        draft: Draft whose requirement, schema, and scopes seed the context.
        schema: Cedar schema for the generation pass.
        existing: Existing policies to surface to the generator.

    Returns:
        A :class:`GenerationContext` ready to hand to a :class:`Generator`.
    """
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
    """Build a :class:`StoredDraft` from a draft and a generation result.

    The returned :class:`StoredDraft` carries the typed intent and the
    three scope JSON blobs alongside the existing Cedar text. Those
    fields are required for verification and deployment: when
    :meth:`Workspace.apply_for_requirement` reads the draft back, the
    reconstructed :class:`DraftPolicy` carries the original scopes and
    intent, not a fabricated placeholder.

    Args:
        draft: Draft whose id, unresolved items, and provenance are
            preserved in the stored row.
        result: Generation result carrying the model identifier and
            request id.
        cedar: Compiled Cedar source text.

    Returns:
        A :class:`StoredDraft` ready for insertion.
    """
    from .scope_json import (
        action_scope_to_dict,
        principal_scope_to_dict,
        resource_scope_to_dict,
    )

    intent_json: str | None = None
    if draft.intent is not None:
        intent_json = json.dumps(
            {
                "id": draft.intent.id,
                "requirement_id": draft.intent.requirement_id,
                "effect": draft.intent.effect,
                "principal": principal_scope_to_dict(draft.intent.principal),
                "action": action_scope_to_dict(draft.intent.action),
                "resource": resource_scope_to_dict(draft.intent.resource),
                "when": [clause.body for clause in draft.intent.when_clauses],
                "unless": [clause.body for clause in draft.intent.unless_clauses],
                "notes": dict(draft.intent.notes),
            },
            sort_keys=True,
        )
    principal_json = (
        json.dumps(principal_scope_to_dict(draft.principal), sort_keys=True)
        if draft.principal is not None
        else None
    )
    action_json = (
        json.dumps(action_scope_to_dict(draft.action), sort_keys=True)
        if draft.action is not None
        else None
    )
    resource_json = (
        json.dumps(resource_scope_to_dict(draft.resource), sort_keys=True)
        if draft.resource is not None
        else None
    )

    return StoredDraft(
        id=str(uuid.uuid4()),
        policy_id=draft.id,
        model=result.model,
        request_id=result.request_id,
        unresolved=draft.unresolved,
        cedar=cedar,
        created_at=datetime.now(UTC),
        intent_json=intent_json,
        principal_scope_json=principal_json,
        action_scope_json=action_json,
        resource_scope_json=resource_json,
    )


def build_stored_report(
    policy_id: str,
    kind: str,
    report: ValidationReport | TestReport,
) -> StoredReport:
    """Build a :class:`StoredReport` from a validation or test report.

    Args:
        policy_id: Identifier of the policy the report belongs to.
        kind: Report kind (``"validation"`` or ``"test"``).
        report: Source report whose payload is serialized to JSON.

    Returns:
        A :class:`StoredReport` with ``created_at`` set to the current time.
    """
    return StoredReport(
        policy_id=policy_id,
        kind=kind,
        passed=report.passed,
        payload=dict(report.to_dict()),
        created_at=datetime.now(UTC),
    )


def qualify_intent(intent: PolicyIntent, schema: CedarSchema) -> PolicyIntent:
    """Return a copy of ``intent`` with namespace-qualified type names.

    The generator emits ``User``, ``Photo``, ``viewPhoto`` and similar
    names without their namespace prefix. ``qualify_intent`` looks each
    one up in the schema and rewrites it with its namespace when there
    is a unique match. Unresolved names pass through unchanged.

    Args:
        intent: Original intent from the generator.
        schema: Cedar schema used for namespace lookup.

    Returns:
        A new :class:`PolicyIntent` with qualified principal, action,
        and resource scopes.
    """
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
    """Return the namespace that owns the given action, or ``None``.

    Searches every namespace in ``schema.source`` for an action whose
    identifier matches either ``action.name`` or ``action.group``. When
    multiple namespaces claim the same action, the first one wins
    (schemas with that pattern should be normalized before reaching
    here).

    Args:
        action: Action scope whose namespace to resolve.
        schema: Cedar schema used for the lookup.

    Returns:
        The matching namespace identifier, or ``None`` if the action is
        not found in any namespace. Falls back to ``action.namespace``
        when set, allowing the caller to preserve an existing namespace.
    """
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


def loads_optional_json(payload: str | None) -> dict[str, Any] | None:
    """Deserialize a JSON string into a dict, returning ``None`` for empty input.

    Args:
        payload: JSON string to deserialize, or ``None``.

    Returns:
        The deserialized dict, or ``None`` when ``payload`` is empty or
        not a JSON object.
    """
    if not payload:
        return None
    data = json.loads(payload)
    if not isinstance(data, dict):
        return None
    return cast(dict[str, Any], data)


def intent_from_draft(
    draft: StoredDraft, intent_id: str, requirement_id: str
) -> PolicyIntent | None:
    """Rebuild the typed intent for a stored draft.

    When the stored draft carries ``intent_json``, that JSON is parsed
    into a typed :class:`PolicyIntent`. When the JSON is missing (legacy
    drafts migrated by :func:`migrate_legacy_rows`), a permissive
    fallback intent is constructed so that downstream callers see a
    typed object instead of ``None``.
    """
    from .scope_json import (
        action_scope_from_dict,
        principal_scope_from_dict,
        resource_scope_from_dict,
    )

    if draft.intent_json:
        data = loads_optional_json(draft.intent_json)
        if data is not None:
            return PolicyIntent(
                id=str(data.get("id", intent_id)),
                requirement_id=str(data.get("requirement_id", requirement_id)),
                effect=data.get("effect", "permit"),
                principal=principal_scope_from_dict(data.get("principal"))
                or PrincipalScope(),
                action=action_scope_from_dict(data.get("action")) or ActionScope(),
                resource=resource_scope_from_dict(data.get("resource"))
                or ResourceScope(),
                when_clauses=tuple(
                    ConditionClause(body=body) for body in data.get("when", []) or []
                ),
                unless_clauses=tuple(
                    ConditionClause(body=body) for body in data.get("unless", []) or []
                ),
                notes=dict(data.get("notes", {}) or {}),
            )
    text = draft.cedar.strip().lower()
    effect = "forbid" if text.startswith("forbid") else "permit"
    return PolicyIntent(
        id=intent_id,
        requirement_id=requirement_id,
        effect=effect,  # type: ignore[arg-type]
        principal=PrincipalScope(),
        action=ActionScope(),
        resource=ResourceScope(),
    )


__all__ = [
    "DEFAULT_REQUIREMENTS_DIRNAME",
    "DEFAULT_SCHEMA_FILENAME",
    "DEFAULT_SCENARIOS_FILENAME",
    "DEFAULT_STORAGE_FILENAME",
    "Workspace",
    "load_requirement",
    "load_requirements",
]
