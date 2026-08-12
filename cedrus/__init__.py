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
* :class:`~cedrus.generate.Generator` produces a typed
  :class:`~cedrus.compile.Intent`; two implementations
  ship (:class:`~cedrus.generate.Offline` and
  :class:`~cedrus.generate.Llm`).
* :func:`~cedrus.compile.compile_intent` renders the intent to
  Cedar source text.
* :func:`~cedrus.validate.validate` runs Cedar parse and
  schema validation.
* :func:`~cedrus.case.run_scenarios` exercises the policy
  against authorization scenarios.
* :func:`~cedrus.verify.verify_policies` runs static
  checks for shadowing, redundancy, and coverage.
* :class:`~cedrus.deploy.Bundler` and
  :class:`~cedrus.deploy.Client` produce and push the
  deployment bundle.

The :class:`Space` class orchestrates every stage and is the
recommended entry point for Python users.

Schema migration
----------------

Starting with cedrus 0.6.0, every stored :class:`DraftStored`
carries a JSON-serialized typed intent and per-slot scope JSON, and
every :class:`Stored` carries the action scope JSON.
:mod:`cedrus.migrate` exposes detection and migration helpers;
the CLI surfaces them as ``cedrus migrate``. SQLite workspaces
created before this version refuse to open until the migration has
run, so the new fields are guaranteed to be populated.
"""

from .case import Case, Outcome, Suite, load_scenarios, run_scenarios
from .compile import Intent, Source, compile_intent
from .deploy import (
    Bundler,
    Client,
    Guard,
    Manifest,
    Pin,
    Record,
    Transport,
    generate_record_id,
)
from .domain import Domain
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
from .generate import (
    Context,
    Generator,
    Llm,
    Offline,
    Proposal,
    Result,
)
from .migrate import detect_legacy_rows, migrate_legacy_rows
from .need import Need, load_requirement, load_requirements, render_requirement
from .policies import Compiled, Draft, Existing, Kind
from .schema import Schema
from .scope import (
    Action,
    Clause,
    Principal,
    Resource,
    action_scope_from_dict,
    action_scope_to_dict,
    condition_clauses_from_list,
    condition_clauses_to_list,
    principal_scope_from_dict,
    principal_scope_to_dict,
    resource_scope_from_dict,
    resource_scope_to_dict,
)
from .space import Space, Workspace
from .store import Memory, Repository, Sqlite
from .validate import Vreport, validate_cedar
from .validate import validate_cedar as validate
from .verify import (
    Extraction,
    Finding,
    Report,
    extract_entity_types,
    verify_policies,
)
from .verify import (
    verify_policies as verify,
)

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
    "Domain",
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
