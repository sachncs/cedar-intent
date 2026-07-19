"""cedar-intent public API.

The package exposes a typed, OOP-first surface for compiling
organizational authorization intent into validated, deployable
Cedar policies. Every public symbol in ``__all__`` is documented
under its own module; the package itself only re-exports.

Architecture at a glance
------------------------

The pipeline flows:

* :class:`~cedar_intent.requirements.Requirement` - Markdown with
  stable id and domain.
* :class:`~cedar_intent.policies.DraftPolicy` - scope-typed draft.
* :class:`~cedar_intent.generator.Generator` produces a typed
  :class:`~cedar_intent.compiler.PolicyIntent`; two implementations
  ship (:class:`~cedar_intent.generator.OfflineGenerator` and
  :class:`~cedar_intent.generator.LiteLLMGenerator`).
* :func:`~cedar_intent.compiler.compile_intent` renders the intent to
  Cedar source text.
* :func:`~cedar_intent.validation.validate_cedar` runs Cedar parse and
  schema validation.
* :func:`~cedar_intent.scenarios.run_scenarios` exercises the policy
  against authorization scenarios.
* :func:`~cedar_intent.verification.verify_policies` runs static
  checks for shadowing, redundancy, and coverage.
* :class:`~cedar_intent.deployment.BundleExporter` and
  :class:`~cedar_intent.deployment.DeploymentClient` produce and push
  the deployment bundle.

The :class:`Workspace` class orchestrates every stage and is the
recommended entry point for Python users.

Schema migration
----------------

Starting with cedar-intent 0.6.0, every stored :class:`StoredDraft`
carries a JSON-serialized typed intent and per-slot scope JSON, and
every :class:`StoredPolicy` carries the action scope JSON.
:mod:`cedar_intent.migrations` exposes detection and migration
helpers; the CLI surfaces them as ``cedar-intent migrate``. SQLite
workspaces created before this version refuse to open until the
migration has run, so the new fields are guaranteed to be populated.
"""

from .compiler import CompiledSource, PolicyIntent, compile_intent
from .deployment import (
    BundleExporter,
    DeploymentClient,
    DeploymentManifest,
    DeploymentRecord,
    generate_record_id,
)
from .errors import (
    CedarIntentError,
    CompilationError,
    ConfigError,
    DeploymentError,
    GeneratorError,
    PolicyError,
    RequirementError,
    ScopeError,
    StorageError,
    ValidationError,
    WorkspaceError,
)
from .generator import (
    DraftProposal,
    GenerationContext,
    GenerationResult,
    Generator,
    LiteLLMGenerator,
    OfflineGenerator,
)
from .migrations import detect_legacy_rows, migrate_legacy_rows
from .policies import CompiledPolicy, DraftPolicy, ExistingPolicy, Policy
from .requirements import Requirement, load_requirement, load_requirements, render_requirement
from .scenarios import Scenario, ScenarioResult, TestReport, load_scenarios, run_scenarios
from .schema import CedarSchema
from .scope_json import (
    action_scope_from_dict,
    action_scope_to_dict,
    condition_clauses_from_list,
    condition_clauses_to_list,
    principal_scope_from_dict,
    principal_scope_to_dict,
    resource_scope_from_dict,
    resource_scope_to_dict,
)
from .scopes import ActionScope, ConditionClause, PrincipalScope, ResourceScope
from .storage import InMemoryRepository, Repository, SqliteRepository
from .validation import ValidationReport, validate_cedar
from .verification import (
    VerificationFinding,
    VerificationReport,
    extract_entity_types,
    verify_policies,
)
from .workspace import Workspace

__version__ = "0.6.0"

__all__ = [
    "ActionScope",
    "BundleExporter",
    "CedarIntentError",
    "CedarSchema",
    "CompilationError",
    "CompiledPolicy",
    "CompiledSource",
    "ConditionClause",
    "ConfigError",
    "DeploymentClient",
    "DeploymentError",
    "DeploymentManifest",
    "DeploymentRecord",
    "DraftPolicy",
    "DraftProposal",
    "ExistingPolicy",
    "GenerationContext",
    "GenerationResult",
    "Generator",
    "GeneratorError",
    "InMemoryRepository",
    "LiteLLMGenerator",
    "OfflineGenerator",
    "Policy",
    "PolicyError",
    "PolicyIntent",
    "PrincipalScope",
    "Repository",
    "Requirement",
    "RequirementError",
    "ResourceScope",
    "Scenario",
    "ScenarioResult",
    "ScopeError",
    "SqliteRepository",
    "StorageError",
    "TestReport",
    "ValidationError",
    "ValidationReport",
    "VerificationFinding",
    "VerificationReport",
    "Workspace",
    "WorkspaceError",
    "__version__",
    "action_scope_from_dict",
    "action_scope_to_dict",
    "compile_intent",
    "condition_clauses_from_list",
    "condition_clauses_to_list",
    "detect_legacy_rows",
    "extract_entity_types",
    "generate_record_id",
    "load_requirement",
    "load_requirements",
    "load_scenarios",
    "migrate_legacy_rows",
    "principal_scope_from_dict",
    "principal_scope_to_dict",
    "render_requirement",
    "resource_scope_from_dict",
    "resource_scope_to_dict",
    "run_scenarios",
    "validate_cedar",
    "verify_policies",
]
