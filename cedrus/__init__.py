"""cedrus public API.

The package exposes a typed, OOP-first surface for compiling
organizational authorization intent into validated, deployable
Cedar policies. Every public symbol in ``__all__`` is documented
under its own module; the package itself only re-exports.

Architecture at a glance
------------------------

The pipeline flows:

* :class:`~cedrus.need.Need` - Markdown with stable id and domain.
* :class:`~cedrus.policy.Draft` - scope-typed draft.
* :class:`~cedrus.generator.Generator` produces a typed
  :class:`~cedrus.compiler.Intent`; two implementations
  ship (:class:`~cedrus.generator.Offline` and
  :class:`~cedrus.generator.Llm`).
* :func:`~cedrus.compiler.compile_intent` renders the intent to
  Cedar source text.
* :func:`~cedrus.validation.validate` runs Cedar parse and
  schema validation.
* :func:`~cedrus.scenarios.run_scenarios` exercises the policy
  against authorization scenarios.
* :func:`~cedrus.verification.verify_policies` runs static
  checks for shadowing, redundancy, and coverage.
* :class:`~cedrus.deployment.Bundler` and
  :class:`~cedrus.deployment.Client` produce and push the
  deployment bundle.

The :class:`Space` class orchestrates every stage and is the
recommended entry point for Python users.

Schema migration
----------------

Starting with cedrus 0.6.0, every stored :class:`DraftStored`
carries a JSON-serialized typed intent and per-slot scope JSON, and
every :class:`Stored` carries the action scope JSON.
:mod:`cedrus.migrations` exposes detection and migration helpers;
the CLI surfaces them as ``cedrus migrate``. SQLite workspaces
created before this version refuse to open until the migration has
run, so the new fields are guaranteed to be populated.
"""

from .compiler import Intent, Source, compile_intent
from .deployment import (
    Bundler,
    Client,
    Guard,
    Manifest,
    Pin,
    Record,
    Transport,
    generate_record_id,
)
from .error import (
    Compile,
    Config,
    Deploy,
    Error,
    Fault,
    Generate,
    Require,
    ScopeFault,
    Store,
    Validate,
)
from .error import (
    Space as SpaceError,
)
from .generator import (
    Context,
    Generator,
    Llm,
    Offline,
    Proposal,
    Result,
)
from .migrations import detect_legacy_rows, migrate_legacy_rows
from .policies import Compiled, Draft, Existing, Kind
from .requirements import Need, load_requirement, load_requirements, render_requirement
from .scenarios import Case, Outcome, Suite, load_scenarios, run_scenarios
from .schema import Schema
from .scope_json import (
    action_scope_from_dict,
    action_scope_to_dict,
    condition_clauses_from_list,
    condition_clauses_to_list,
    intent_from_dict,
    intent_to_dict,
    principal_scope_from_dict,
    principal_scope_to_dict,
    resource_scope_from_dict,
    resource_scope_to_dict,
)
from .scopes import Action, Clause, Principal, Resource
from .storage import Memory, Repository, Sqlite
from .validation import Vreport, validate_cedar
from .validation import validate_cedar as validate
from .verification import (
    Extraction,
    Finding,
    Report,
    extract_entity_types,
    verify_policies,
)
from .verification import (
    verify_policies as verify,
)
from .workspace import Space, Workspace

__version__ = "0.7.0"

__all__ = [
    "Action",
    "Bundler",
    "Case",
    "Clause",
    "Client",
    "Compile",
    "Compiled",
    "Config",
    "Context",
    "Deploy",
    "Draft",
    "Error",
    "Existing",
    "Extraction",
    "Fault",
    "Finding",
    "Generate",
    "Generator",
    "Guard",
    "Intent",
    "Kind",
    "Llm",
    "Manifest",
    "Memory",
    "Need",
    "Offline",
    "Outcome",
    "Pin",
    "Principal",
    "Proposal",
    "Record",
    "Repository",
    "Require",
    "Resource",
    "Result",
    "Schema",
    "ScopeFault",
    "Source",
    "Space",
    "SpaceError",
    "Sqlite",
    "Store",
    "Suite",
    "Transport",
    "Validate",
    "Verifier",
    "Vreport",
    "Workspace",
    "__version__",
    "action_scope_from_dict",
    "action_scope_to_dict",
    "compile_intent",
    "condition_clauses_from_list",
    "condition_clauses_to_list",
    "detect_legacy_rows",
    "extract_entity_types",
    "generate_record_id",
    "intent_from_dict",
    "intent_to_dict",
    "load_scenarios",
    "migrate_legacy_rows",
    "principal_scope_from_dict",
    "principal_scope_to_dict",
    "render_requirement",
    "load_requirement",
    "load_requirements",
    "validate_cedar",
    "verify_policies",
    "Report",
    "load_requirement",
    "load_requirements",
    "resource_scope_from_dict",
    "resource_scope_to_dict",
    "run_scenarios",
    "validate",
    "verify",
]
