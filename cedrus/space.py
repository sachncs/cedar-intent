"""Workspace orchestrator.

A :class:`Workspace` binds every cedrus concern together: it owns a
repository, loads schemas and requirements from disk, drives generators,
applies drafts, and exports validated policy bundles for embedded Cedar
applications.

Lifecycle:
    A typical session runs through these stages:

    1. **Initialize** - :meth:`Workspace.create` or
       :meth:`Workspace.open` creates or loads the workspace layout
       and storage.
    2. **Declare domain** - :meth:`Workspace.init_domain` creates the
       directory layout and an empty schema for a domain.
    3. **Load requirements** - :meth:`Workspace.add_requirement_file`
       or :meth:`Workspace.add_requirement_directory` registers
       Markdown requirements.
    4. **Generate draft** - :meth:`Workspace.generate_draft` runs a
       :class:`~cedrus.generate.Generator` against a draft and
       persists the proposal.
    5. **Apply** - :meth:`Workspace.apply` or
       :meth:`Workspace.apply_for_requirement` validates, optionally
       runs scenarios, and persists a :class:`Compiled`.
    6. **Verify** - :meth:`Workspace.verify_domain` flags shadowing,
       redundancy, and coverage gaps.
    7. **Deploy** - :meth:`Workspace.build_bundle`,
       :meth:`Workspace.write_bundle`, and :meth:`Workspace.deploy`
       produce and push the deployment artifact.

Thread safety:
    A single :class:`Workspace` instance is safe for concurrent use
    from multiple threads only when the underlying
    :class:`Repository` supports it. The default :class:`Backend`
    serializes access through its connection; for heavy parallel use,
    prefer one workspace per thread.

Attributes:
    Workspace: Top-level orchestrator.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from cedrus.case import Case, Run, Suite
from cedrus.compile import Intent
from cedrus.deploy import Bundler, Client, Manifest, Record
from cedrus.error import Fault, Space
from cedrus.generate import Context, Generator, Result
from cedrus.need import Need
from cedrus.policies import Compiled, Draft, Existing, Kind
from cedrus.schema import Schema
from cedrus.scope import Action, Principal, Resource
from cedrus.store import Backend, DraftStored, Memory, ReportStored, Repository, Stored
from cedrus.validate import Vreport
from cedrus.verify import Report, Verifier

DEFAULT_STORAGE_FILENAME = "store.db"
DEFAULT_REQUIREMENTS_DIRNAME = "requirements"
DEFAULT_SCHEMA_FILENAME = "schema.json"
DEFAULT_SCENARIOS_FILENAME = "scenarios.json"


@dataclass
class Workspace:
    """Top-level cedrus orchestrator for a single organization workspace.

    Attributes:
        root: Filesystem root of the workspace.
        repository: Storage backend used by the workspace.
        storage_path: Path to the workspace's persistent SQLite
            database.
    """

    root: Path
    repository: Repository
    storage_path: Path

    @classmethod
    def open(cls, path: Path) -> "Workspace":
        """Open an existing workspace at ``path``.

        Args:
            path: Filesystem path of the workspace root.

        Returns:
            A :class:`Workspace` backed by a SQLite repository.

        Raises:
            Space: If the path does not exist.
        """
        root = Path(path).resolve()
        if not root.exists() or not root.is_dir():
            raise Space(f"workspace root not found: {root}")
        storage_path = root / ".cedrus" / DEFAULT_STORAGE_FILENAME
        repository = Backend(storage_path)
        return cls(root=root, repository=repository, storage_path=storage_path)

    @classmethod
    def create(cls, path: Path) -> "Workspace":
        """Create a new workspace at ``path`` and return it.

        Args:
            path: Filesystem path that will become the workspace root.

        Returns:
            A freshly created :class:`Workspace`.
        """
        root = Path(path).resolve()
        root.mkdir(parents=True, exist_ok=True)
        (root / ".cedrus").mkdir(exist_ok=True)
        storage_path = root / ".cedrus" / DEFAULT_STORAGE_FILENAME
        repository = Backend(storage_path)
        return cls(root=root, repository=repository, storage_path=storage_path)

    @classmethod
    def in_memory(cls, path: Path | None = None) -> "Workspace":
        """Build an in-memory workspace for tests or ephemeral sessions.

        Args:
            path: Optional filesystem path used as the workspace root.
                Defaults to the current directory.

        Returns:
            A :class:`Workspace` backed by an :class:`Memory`.
        """
        root = (path or Path.cwd()).resolve()
        return cls(
            root=root, repository=Memory(), storage_path=root / "<memory>"
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
        with the domain name as the only namespace. The seed write
        is atomic: a sibling temp file is created, fsynced, and
        renamed into place, so a crash mid-write can never leave a
        truncated ``schema.json`` on disk.

        Args:
            domain: Domain identifier to initialize.

        Returns:
            The path of the schema file after initialization.
        """
        self.requirements_directory(domain).mkdir(parents=True, exist_ok=True)
        self.policies_directory(domain).mkdir(parents=True, exist_ok=True)
        schema_path = self.schema_path(domain)
        if not schema_path.exists():
            payload = json.dumps(
                {domain: {"entityTypes": {}, "actions": {}}}, indent=2
            )
            parent = schema_path.parent
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{schema_path.name}.", dir=str(parent), suffix=".tmp"
            )
            try:
                os.write(fd, payload.encode("utf-8"))
                os.fsync(fd)
                os.close(fd)
                os.replace(tmp_name, schema_path)
            except OSError:
                os.close(fd)
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        return schema_path

    def load_schema(self, domain: str) -> Schema:
        """Load and validate the Cedar schema for ``domain``.

        Args:
            domain: Domain identifier.

        Returns:
            A fully parsed :class:`Schema`.

        Raises:
            cedrus.error.Validate: If the schema file is missing or invalid.
        """
        return Schema.from_json_file(self.schema_path(domain))

    def load_scenarios(self, domain: str) -> list[Case]:
        """Load authorization scenarios for ``domain``.

        Returns an empty list when the scenarios file does not exist.

        Args:
            domain: Domain identifier.

        Returns:
            A list of :class:`Case` objects.

        Raises:
            Space: If the scenarios file exists but is not a JSON list.
        """
        path = self.scenarios_path(domain)
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise Space(f"scenarios file must contain a list: {path}")
        return Case.load(data)

    def add_requirement_file(self, path: Path) -> Need:
        """Load a single requirement from ``path`` and persist it.

        Args:
            path: Markdown file to load.

        Returns:
            The loaded :class:`Need`.

        Raises:
            Require: If the file is missing or malformed.
        """
        requirement = Need.from_markdown(path, workspace_root=self.root)
        requirement.save(self.repository)
        return requirement

    def add_requirement_directory(self, domain: str) -> list[Need]:
        """Add every requirement in the domain's requirements directory.

        Args:
            domain: Domain identifier.

        Returns:
            The list of requirements loaded and persisted.
        """
        added: list[Need] = []
        for requirement in Need.from_directory(
            self.requirements_directory(domain), workspace_root=self.root
        ):
            requirement.save(self.repository)
            added.append(requirement)
        return added

    def get_requirement(self, requirement_id: str) -> Need:
        """Return the requirement with ``requirement_id``.

        Raises:
            Require: If no requirement exists with that id.
        """
        return Need.get(self.repository, requirement_id)

    def list_requirements(self, domain: str | None = None) -> list[Need]:
        """Return requirements, optionally filtered by ``domain``."""
        return Need.list(self.repository, domain=domain)

    def remove_requirement(self, requirement_id: str) -> None:
        """Remove the requirement with ``requirement_id``.

        Raises:
            Store: If no requirement exists with that id.
        """
        self.repository.remove_requirement(requirement_id)

    def import_existing_policies(self, domain: str) -> list[Existing]:
        """Import Cedar files from the domain's policies directory.

        Each ``*.cedar`` file in ``<domain>/policies/`` becomes a
        synthetic :class:`Need` (named after the file stem) plus
        an :class:`Existing` carrying the Cedar source. The policy is
        also upserted as a :class:`Compiled` so it shows up in
        subsequent verification, test, and deployment runs.

        Duplicate file stems (for example ``Foo.cedar`` and
        ``Foo.cedar.bak`` both producing stem ``Foo``) raise
        :class:`Space` so the operator is forced to disambiguate
        before the import proceeds; the prior behaviour silently
        merged the duplicates via upsert and lost data.

        Args:
            domain: Domain identifier.

        Returns:
            The list of imported :class:`Existing` objects, in
            alphabetical order by file name. Empty when the policies
            directory does not exist.

        Raises:
            Space: When two ``*.cedar`` files share the same stem.
        """
        existing: list[Existing] = []
        directory = self.policies_directory(domain)
        if not directory.exists():
            return existing
        stems_seen: set[str] = set()
        for path in sorted(directory.glob("*.cedar")):
            if path.stem in stems_seen:
                raise Space(
                    f"duplicate policy file stem {path.stem!r} in {directory}: "
                    "rename one of the files before importing"
                )
            stems_seen.add(path.stem)
            cedar = path.read_text(encoding="utf-8").strip()
            requirement = Need(
                id=path.stem,
                text=f"Imported from {path.name}",
                domain=domain,
                source_path=path,
                created_at=datetime.now(UTC),
            )
            requirement.save(self.repository)
            policy = Existing.from_requirement(requirement, cedar=cedar)
            existing.append(policy)
            self.upsert_compiled(
                Compiled(
                    id=policy.id,
                    requirement=requirement,
                    cedar=cedar,
                )
            )
        return existing

    def upsert_compiled(self, policy: Kind) -> None:
        """Persist ``policy`` to the repository.

        Existing policies with no parsed intent raise ``Fault`` from
        :meth:`to_intent`; that is the expected case, not a failure.
        The intent field is stored as ``None`` and the workspace falls
        back to it at verification time through
        :attr:`intent_for_verification`.

        Args:
            policy: Policy to upsert.
        """
        intent: Intent | None = None
        try:
            intent = policy.to_intent()
        except Fault:
            intent = None
        stored = Stored(
            id=policy.id,
            domain=policy.requirement.domain,
            requirement_id=policy.requirement.id,
            intent=intent,
            cedar=policy.cedar,
            status=policy.kind(),
            created_at=policy.created_at,
            updated_at=datetime.now(UTC),
            action=policy.action,
        )
        stored.upsert(self.repository)

    def create_draft(
        self,
        requirement_id: str,
        *,
        principal: Principal | None = None,
        action: Action | None = None,
        resource: Resource | None = None,
        policy_id: str | None = None,
    ) -> Draft:
        """Create a :class:`Draft` for the given requirement and scopes.

        Args:
            requirement_id: Identifier of the requirement to draft.
            principal: Optional principal scope. Defaults to ``any``.
            action: Optional action scope. Defaults to ``any``.
            resource: Optional resource scope. Defaults to ``any``.
            policy_id: Optional explicit identifier. Defaults to
                ``"draft-<requirement_id>"``.

        Returns:
            The constructed :class:`Draft`.

        Raises:
            Store: If the requirement does not exist.
        """
        requirement = Need.get(self.repository, requirement_id)
        return Draft.from_requirement(
            requirement,
            principal=principal,
            action=action,
            resource=resource,
            policy_id=policy_id,
        )

    def list_existing_policies(self, domain: str) -> list[Existing]:
        """Return existing policies for ``domain`` as :class:`Existing` objects.

        Includes both true existing policies and any policy persisted
        with status ``"existing"``. The synthetic requirements
        produced by :meth:`import_existing_policies` are looked up by
        id when present.

        Args:
            domain: Domain identifier.

        Returns:
            A list of :class:`Existing` in storage order.
        """
        result: list[Existing] = []
        for stored in Stored.list(self.repository, domain=domain):
            requirement = Need.get(self.repository, stored.requirement_id or stored.id)
            result.append(
                Existing(
                    id=stored.id,
                    requirement=requirement,
                    cedar=stored.cedar,
                    parsed_intent=stored.intent,
                )
            )
        return result

    def list_compiled_policies(self, domain: str) -> list[Compiled]:
        """Return the compiled policies for ``domain`` as :class:`Compiled` objects.

        Args:
            domain: Domain identifier.

        Returns:
            A list of compiled policies whose storage status is
            ``"compiled"``. Orphan policies (those whose requirement
            has been deleted) are silently skipped.
        """
        result: list[Compiled] = []
        for stored in Stored.list(self.repository, domain=domain):
            if stored.status != "compiled":
                continue
            requirement_id = stored.requirement_id or stored.id
            # Skip orphan policies whose backing requirement has been
            # deleted from the store; the foreign key on
            # policies.requirement_id is ON DELETE SET NULL, so this
            # can happen in practice.
            try:
                requirement = Need.get(self.repository, requirement_id)
            except Store:
                continue
            result.append(
                Compiled(
                    id=stored.id,
                    requirement=requirement,
                    cedar=stored.cedar,
                    intent=stored.intent,
                )
            )
        return result

    def generate_draft(
        self,
        draft: Draft,
        schema: Schema,
        generator: Generator,
        *,
        existing: Sequence[Kind] = (),
    ) -> tuple[Draft, Result]:
        """Run ``generator`` against ``draft`` and persist the resulting proposal.

        Args:
            draft: Draft whose scopes and requirement seed the generator.
            schema: Cedar schema the draft must conform to.
            generator: Generator that produces the typed intent.
            existing: Existing policies the generator should be aware of.

        Returns:
            A tuple of ``(updated_draft, generation_result)``. The
            returned draft carries the generator's Cedar and
            provenance.
        """
        result = generator.generate(self._build_context(draft, schema, existing))
        proposal = result.proposal
        qualified_intent = self._qualify_intent(proposal.intent, schema)
        compiled_source = qualified_intent.compile()
        new_draft = Draft(
            id=draft.id,
            requirement=draft.requirement,
            cedar=compiled_source.cedar,
            created_at=datetime.now(UTC),
            principal=qualified_intent.principal,
            action=qualified_intent.action,
            resource=qualified_intent.resource,
            intent=qualified_intent,
            unresolved=tuple(proposal.unresolved),
            status="proposed",
            notes=proposal.notes,
            model=result.model,
            request_id=result.request_id,
        )
        new_draft.save(self.repository)
        return new_draft, result

    def verify_domain(self, domain: str, schema: Schema) -> Report:
        """Run static verification on a domain's compiled policies.

        The verifier analyzes the deployed Cedar source of every
        compiled policy, so coverage and shadowing reflect what
        will actually run. Action groups are expanded through the
        schema so ``action in Action::"group"`` covers every member
        action.

        Args:
            domain: Domain identifier.
            schema: Cedar schema used to compute coverage.

        Returns:
            A :class:`Report` aggregating findings and coverage metrics.
        """
        policies = self.list_compiled_policies(domain)
        requirement_ids = [
            requirement.id
            for requirement in Need.list(self.repository, domain=domain)
        ]
        return Verifier(schema).verify(
            policies,
            requirement_ids=requirement_ids,
            action_names=sorted(schema.action_names()),
            entity_type_names=sorted(schema.entity_type_names()),
            domain=domain,
        )

    def build_bundle(
        self,
        domain: str,
        *,
        metadata: Mapping[str, str] | None = None,
    ) -> Manifest:
        """Build a deployment manifest for ``domain`` from compiled policies.

        Args:
            domain: Domain identifier.
            metadata: Optional deployment metadata included in the
                manifest.

        Returns:
            The constructed :class:`Manifest`.

        Raises:
            Deploy: If no compiled policies are available.
        """
        policies = self.list_compiled_policies(domain)
        return Bundler().build(domain, policies, metadata=metadata)

    def write_bundle(self, manifest: Manifest, directory: Path) -> Path:
        """Write a manifest to ``directory`` without recording a deployment.

        Args:
            manifest: Manifest to write.
            directory: Target directory. Created if it does not exist.

        Returns:
            The directory the manifest was written to.
        """
        return Bundler().write_directory(manifest, directory)

    def deploy(
        self,
        domain: str,
        target: str,
        *,
        timeout: float = 30,
        headers: Mapping[str, str] | None = None,
        skip_verify: bool = False,
        allow_private_targets: bool = False,
        allow_loopback: bool = False,
    ) -> Record:
        """Build a manifest, verify it, and push it to ``target``.

        The verifier runs first; the deployment refuses to ship when
        warnings are reported. Set ``skip_verify=True`` to bypass the
        check (for example, when re-deploying a previously approved
        bundle after an emergency rollback).

        Args:
            domain: Domain to deploy.
            target: Local directory path or ``http(s)://`` URL.
            timeout: HTTP timeout in seconds.
            headers: Optional HTTP headers added to the POST request.
            skip_verify: When ``True``, bypass the verification gate.
            allow_private_targets: When ``True``, the deployment
                client's SSRF guard permits HTTP targets in RFC1918
                private network ranges. Defaults to ``False`` so the
                guard rejects loopback, link-local, and private
                networks.
            allow_loopback: When ``True``, permits loopback and
                link-local targets. Intended for tests that bind to
                ``127.0.0.1``; never enable in production.

        Returns:
            The persisted :class:`Record`.

        Raises:
            Deploy: If no compiled policies are available or the HTTP
                target returns non-2xx.
            Space: If the verifier reports warnings and ``skip_verify``
                is ``False``.
        """
        schema = self.load_schema(domain)
        if not skip_verify:
            report = self.verify_domain(domain, schema)
            if not report.passed:
                issues = ", ".join(finding.message for finding in report.findings)
                raise Space(
                    f"verifier rejected domain {domain!r}: {issues}; "
                    "pass skip_verify=True to bypass"
                )
        manifest = self.build_bundle(domain)
        client = Client(
            timeout=timeout,
            allow_private_targets=allow_private_targets,
            allow_loopback=allow_loopback,
        )
        record = client.deploy(manifest, target, headers=headers)
        record.save(self.repository)
        return record

    def list_deployments(self, domain: str | None = None) -> list[Record]:
        """Return deployment records, optionally filtered by ``domain``."""
        return Record.list(self.repository, domain=domain)

    def apply(
        self,
        draft: Draft,
        schema: Schema,
        *,
        scenarios: Sequence[Case] = (),
        entities: Sequence[Mapping[str, Any]] = (),
    ) -> Compiled:
        """Compile, validate, and persist ``draft`` as a :class:`Compiled`.

        The validation report, scenario test report, and compiled
        policy upsert all happen inside a single repository
        transaction. If scenarios fail the raise happens before the
        transaction commits, so the validation report, test report,
        and policy upsert are all rolled back together. A failed
        apply therefore never leaves the workspace in a half-applied
        state.

        Args:
            draft: Draft to apply.
            schema: Cedar schema to validate against.
            scenarios: Optional authorization scenarios to run.
            entities: Optional entities exposed to the Cedar engine.

        Returns:
            The persisted :class:`Compiled`.

        Raises:
            Space: If the draft has no Cedar source, has
                unresolved items, or any scenario fails.
        """
        if draft.cedar is None or not draft.cedar.strip():
            raise Space(
                f"draft {draft.id} has no Cedar source; call generate before apply"
            )
        if draft.unresolved:
            raise Space(
                f"draft {draft.id} has unresolved items: {', '.join(draft.unresolved)}"
            )
        report = Vreport.from_cedar([draft.cedar], schema)
        if scenarios:
            scenario_list: list[Case] = list(scenarios)
            test_report = draft.test(
                schema, scenario_list, entities=self._resolve_test_entities(entities)
            )
            if not test_report.passed:
                failures = [
                    result
                    for result in test_report.results
                    if not result.passed
                ]
                raise Space(
                    f"draft {draft.id} failed scenarios: "
                    + ", ".join(failure.scenario.name for failure in failures)
                )
        with self.repository.transaction():
            self._build_stored_report(draft.id, "validation", report).save(
                self.repository
            )
            if scenarios and test_report is not None:
                self._build_stored_report(draft.id, "test", test_report).save(
                    self.repository
                )
            compiled = Compiled(
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
        schema: Schema,
        *,
        scopes: tuple[Principal | None, Action | None, Resource | None] = (
            None,
            None,
            None,
        ),
        scenarios: Sequence[Case] = (),
    ) -> Compiled:
        """Apply the most recent draft that addresses ``requirement_id``.

        Looks up the requirement, finds the latest stored draft for
        it, and applies that draft. The reconstructed :class:`Draft`
        carries the typed intent and original scopes read from the
        stored JSON columns, so verification and deployment see
        exactly what the generator produced.

        Args:
            requirement_id: Identifier of the requirement to apply.
            schema: Cedar schema the draft must validate against.
            scopes: Optional ``(principal, action, resource)`` scopes
                used to compute the draft's stable identifier.
            scenarios: Optional scenarios to run during validation.

        Returns:
            The persisted :class:`Compiled`.

        Raises:
            Space: If no draft exists for the requirement.
        """
        requirement = Need.get(self.repository, requirement_id)
        placeholder = Draft.from_requirement(
            requirement,
            principal=scopes[0],
            action=scopes[1],
            resource=scopes[2],
        )
        try:
            stored_draft = DraftStored.latest(self.repository, placeholder.id)
        except Store as error:
            raise Space(
                f"no draft exists for requirement {requirement_id!r}; "
                "run 'cedrus policy generate' first"
            ) from error
        intent = self._intent_from_draft(stored_draft, placeholder.id, requirement_id)
        principal_payload = self._loads_optional_json(
            stored_draft.principal_scope_json
        )
        action_payload = self._loads_optional_json(stored_draft.action_scope_json)
        resource_payload = self._loads_optional_json(
            stored_draft.resource_scope_json
        )
        draft = Draft(
            id=stored_draft.policy_id,
            requirement=requirement,
            cedar=stored_draft.cedar,
            unresolved=stored_draft.unresolved,
            principal=Principal.from_dict(principal_payload)
            if principal_payload
            else placeholder.principal,
            action=Action.from_dict(action_payload)
            if action_payload
            else placeholder.action,
            resource=Resource.from_dict(resource_payload)
            if resource_payload
            else placeholder.resource,
            intent=intent,
            status="proposed",
        )
        return self.apply(draft, schema, scenarios=scenarios)

    def validate_policies(self, domain: str, schema: Schema) -> Vreport:
        """Validate every persisted compiled policy in ``domain``.

        Args:
            domain: Domain identifier.
            schema: Cedar schema to validate against.

        Returns:
            A :class:`Vreport` describing the outcome.

        Raises:
            Space: If no compiled policies exist for ``domain``.
        """
        policies = [
            policy.cedar
            for policy in self.list_compiled_policies(domain)
            if policy.cedar
        ]
        if not policies:
            raise Space(f"no compiled policies for domain {domain!r}")
        return Vreport.from_cedar(policies, schema)

    def test_domain(
        self,
        domain: str,
        schema: Schema,
        *,
        entities: Sequence[Mapping[str, Any]] = (),
    ) -> Suite:
        """Run every scenario for ``domain`` against its compiled policies.

        Args:
            domain: Domain identifier.
            schema: Cedar schema for scenario evaluation.
            entities: Optional entities exposed to the Cedar engine.

        Returns:
            A :class:`Suite` summarizing the outcomes.

        Raises:
            Space: If no scenarios or no compiled policies exist.
        """
        scenarios = self.load_scenarios(domain)
        if not scenarios:
            raise Space(f"no scenarios for domain {domain!r}")
        policies = [
            policy.cedar
            for policy in self.list_compiled_policies(domain)
            if policy.cedar
        ]
        if not policies:
            raise Space(f"no compiled policies for domain {domain!r}")
        effective_schema = schema or Schema.from_mapping(
            {"": {"entityTypes": {}, "actions": {}}}
        )
        run = Run(scenarios)
        result = run.evaluate(effective_schema, policies)
        return result or Suite(passed=True, results=())

    def export_domain(self, domain: str, output: Path) -> Path:
        """Write a Cedar bundle for ``domain`` to ``output``.

        Concatenates every compiled policy for ``domain`` into a
        single file separated by blank lines. Use this when the
        embedded Cedar engine reads policies from a single file.

        Args:
            domain: Domain identifier.
            output: Destination path. Parent directories are
                created.

        Returns:
            The path the bundle was written to.

        Raises:
            Space: If no compiled policies exist for ``domain``.
        """
        policies = self.list_compiled_policies(domain)
        if not policies:
            raise Space(f"no policies to export for domain {domain!r}")
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

    @staticmethod
    def _build_context(
        draft: Draft,
        schema: Schema,
        existing: Sequence[Kind],
    ) -> Context:
        """Build a :class:`Context` for a draft and existing policies.

        Existing policies with no parsed intent are excluded from
        the generation context; the LLM only sees policies it can
        reason about. Failing to parse an existing policy must not
        block the entire draft.

        Args:
            draft: Draft whose requirement, schema, and scopes seed
                the context.
            schema: Cedar schema for the generation pass.
            existing: Existing policies to surface to the generator.

        Returns:
            A :class:`Context` ready to hand to a :class:`Generator`.
        """
        existing_intents: list[Intent] = []
        for policy in existing:
            try:
                existing_intents.append(policy.to_intent())
            except Fault:
                continue
        return Context(
            need=draft.requirement,
            schema=schema,
            principal=draft.principal,
            action=draft.action,
            resource=draft.resource,
            existing=tuple(existing_intents),
        )

    @staticmethod
    def _build_stored_report(
        policy_id: str,
        kind: str,
        report: Vreport | Suite,
    ) -> ReportStored:
        """Build a :class:`ReportStored` from a validation or test report.

        Args:
            policy_id: Identifier of the policy the report belongs
                to.
            kind: Report kind (``"validation"`` or ``"test"``).
            report: Source report whose payload is serialized to JSON.

        Returns:
            A :class:`ReportStored` with ``created_at`` set to the
            current time.
        """
        return ReportStored(
            policy_id=policy_id,
            kind=kind,
            passed=report.passed,
            payload=dict(report.to_dict()),
            created_at=datetime.now(UTC),
        )

    @staticmethod
    def _qualify_intent(intent: Intent, schema: Schema) -> Intent:
        """Return a copy of ``intent`` with namespace-qualified type names.

        The generator emits ``User``, ``Photo``, ``viewPhoto`` and
        similar names without their namespace prefix.
        ``_qualify_intent`` looks each one up in the schema and
        rewrites it with its namespace when there is a unique match.
        Unresolved names pass through unchanged.

        Args:
            intent: Original intent from the generator.
            schema: Cedar schema used for namespace lookup.

        Returns:
            A new :class:`Intent` with qualified principal, action,
            and resource scopes.
        """
        qualified_principal = Principal(
            kind=intent.principal.kind,
            type_name=schema.qualify_type_name(intent.principal.type_name),
            entity_id=intent.principal.entity_id,
            group_type=schema.qualify_type_name(intent.principal.group_type),
            group_id=intent.principal.group_id,
        )
        qualified_resource = Resource(
            kind=intent.resource.kind,
            type_name=schema.qualify_type_name(intent.resource.type_name),
            entity_id=intent.resource.entity_id,
            parent_type=schema.qualify_type_name(intent.resource.parent_type),
            parent_id=intent.resource.parent_id,
        )
        qualified_action = Action(
            kind=intent.action.kind,
            name=intent.action.name,
            group=intent.action.group,
            namespace=self._find_action_namespace(intent.action, schema),
        )
        return Intent(
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

    @staticmethod
    def _find_action_namespace(action: Action, schema: Schema) -> str | None:
        """Return the namespace that owns the given action, or ``None``.

        Searches every namespace in ``schema.source`` for an action
        whose identifier matches either ``action.name`` or
        ``action.group``. When multiple namespaces claim the same
        action, raises :class:`Space` because the resolved namespace
        would otherwise depend on dict iteration order, producing
        non-deterministic compile output across schema reloads.

        Args:
            action: Action scope whose namespace to resolve.
            schema: Cedar schema used for the lookup.

        Returns:
            The matching namespace identifier, or ``None`` if the
            action is not found in any namespace. Falls back to
            ``action.namespace`` when set, allowing the caller to
            preserve an existing namespace.

        Raises:
            Space: When the action id is declared in more than one
                namespace and the caller has not supplied
                ``action.namespace``.
        """
        matches: list[str] = []
        for namespace, declaration in schema.source.items():
            if not isinstance(namespace, str) or not isinstance(declaration, Mapping):
                continue
            actions = declaration.get("actions", {})
            if not isinstance(actions, Mapping):
                continue
            identifier = action.name or action.group
            if identifier and identifier in actions:
                matches.append(namespace)
        if len(matches) > 1 and not action.namespace:
            raise Space(
                f"action {identifier!r} is declared in multiple namespaces "
                f"({', '.join(matches)}); set action.namespace explicitly to "
                "disambiguate"
            )
        if matches:
            return matches[0]
        return action.namespace

    @staticmethod
    def _resolve_test_entities(
        entities: Sequence[Mapping[str, Any]],
    ) -> list[Mapping[str, Any]]:
        """Normalize test entities for passing into the Cedar engine."""
        return [dict(entity) for entity in entities]

    @staticmethod
    def _loads_optional_json(payload: str | None) -> dict[str, Any] | None:
        """Deserialize a JSON string into a dict.

        Args:
            payload: JSON string to deserialize, or ``None``.

        Returns:
            The deserialized dict, or ``None`` when ``payload`` is
            empty or not a JSON object.
        """
        if not payload:
            return None
        data = json.loads(payload)
        if not isinstance(data, dict):
            return None
        return cast(dict[str, Any], data)

    @staticmethod
    def _intent_from_draft(
        draft: "DraftStored", intent_id: str, requirement_id: str
    ) -> Intent | None:
        """Rebuild the typed intent for a stored draft.

        Returns the parsed :class:`Intent` when the stored draft
        carries ``intent_json`` that round-trips successfully. Returns
        ``None`` when no intent can be reconstructed (legacy drafts
        without ``intent_json`` or drafts whose stored JSON is
        corrupt). Callers must handle the ``None`` case explicitly;
        this function no longer synthesizes a permissive
        ``permit(any/any/any)`` fallback because that would silently
        bypass verification gates downstream.

        Both the canonical ``when_clauses``/``unless_clauses`` shape
        and the legacy ``when``/``unless`` shape are accepted on
        read for backward compatibility with rows stored by earlier
        cedrus versions.

        Args:
            draft: Stored draft to rehydrate from.
            intent_id: Id to assign when the stored intent has none.
            requirement_id: Requirement id to assign when the stored
                intent has none.

        Returns:
            The reconstructed :class:`Intent`, or ``None`` when no
            intent can be reconstructed.

        Raises:
            Space: When ``intent_json`` is present but cannot be
                parsed into the expected scope shape.
        """
        if draft.intent is None:
            return None
        data = Workspace._loads_optional_json(draft.intent.to_dict())
        if data is None:
            return None
        try:
            intent = Intent.from_dict(data)
        except (KeyError, TypeError, ValueError) as error:
            raise Space(
                f"stored draft {draft.id!r} has corrupt intent JSON ({error}); "
                "re-run `cedrus policy generate` for the requirement"
            ) from error
        if intent is None:
            raise Space(
                f"stored draft {draft.id!r} has empty intent JSON; "
                "re-run `cedrus policy generate` for the requirement"
            )
        if not intent.id:
            intent = Intent(
                id=intent_id,
                requirement_id=intent.requirement_id or requirement_id,
                effect=intent.effect,
                principal=intent.principal,
                action=intent.action,
                resource=intent.resource,
                when_clauses=intent.when_clauses,
                unless_clauses=intent.unless_clauses,
                notes=dict(intent.notes),
            )
        elif not intent.requirement_id:
            intent = Intent(
                id=intent.id,
                requirement_id=requirement_id,
                effect=intent.effect,
                principal=intent.principal,
                action=intent.action,
                resource=intent.resource,
                when_clauses=intent.when_clauses,
                unless_clauses=intent.unless_clauses,
                notes=dict(intent.notes),
            )
        return intent


__all__ = [
    "DEFAULT_REQUIREMENTS_DIRNAME",
    "DEFAULT_SCHEMA_FILENAME",
    "DEFAULT_SCENARIOS_FILENAME",
    "DEFAULT_STORAGE_FILENAME",
    "Space",
    "Workspace",
]
