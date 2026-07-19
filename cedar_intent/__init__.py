"""cedar-intent public API."""

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
from .policies import CompiledPolicy, DraftPolicy, ExistingPolicy, Policy
from .requirements import Requirement, load_requirement, load_requirements, render_requirement
from .scenarios import Scenario, ScenarioResult, TestReport, load_scenarios, run_scenarios
from .schema import CedarSchema
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
    "compile_intent",
    "extract_entity_types",
    "generate_record_id",
    "load_requirement",
    "load_requirements",
    "load_scenarios",
    "render_requirement",
    "run_scenarios",
    "validate_cedar",
    "verify_policies",
]
