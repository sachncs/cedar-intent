"""cedrus public API.

The package exposes a typed, OOP-first surface for compiling
organizational authorization intent into validated, deployable
Cedar policies. Every public symbol in ``__all__`` is documented
under its own module; the package itself only re-exports.

Architecture at a glance
------------------------

The pipeline flows:

* :class:`~cedrus.need.Need` — Markdown with stable id and domain.
* :class:`~cedrus.policy.Draft` — scope-typed draft.
* :class:`~cedrus.generate.Generator` produces a typed
  :class:`~cedrus.compile.Intent`; two implementations
  ship (:class:`~cedrus.generate.Offline` and
  :class:`~cedrus.generate.Llm`).
* :class:`~cedrus.compile.Compiler` renders the intent to
  Cedar source text.
* :class:`~cedrus.validate.Validator` runs Cedar parse and
  schema validation.
* :class:`~cedrus.case.Runner` exercises the policy against
  authorization scenarios.
* :class:`~cedrus.verify.Verifier` runs static checks for
  shadowing, redundancy, and coverage.
* :class:`~cedrus.deploy.Bundler` and
  :class:`~cedrus.deploy.Client` produce and push the
  deployment bundle.

The :class:`Space` class orchestrates every stage and is the
recommended entry point for Python users.

Schema migration
----------------

:mod:`cedrus.migrate` exposes the :class:`~cedrus.migrate.Migrator`
helper for upgrading pre-0.7.0 workspaces. SQLite workspaces
created before 0.7.0 refuse to open until the migration has run.
"""

from .case import Case, Outcome, Suite
from .compile import Intent, Source
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
from .error import Space as SpaceError
from .generate import (
    Context,
    Generator,
    Llm,
    Offline,
    Proposal,
    Result,
)
from .migrate import Migrator
from .need import Need
from .policies import Compiled, Draft, Existing, Kind
from .schema import Schema
from .scope import Action, Clause, Principal, Resource, Scope
from .space import Space
from .store import Backend, Memory, Repository
from .validate import Validator, Vreport
from .verify import Extraction, Finding, Report, Verifier

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
    "Migrator",
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
    "Scope",
    "ScopeFault",
    "Source",
    "Backend",
    "Space",
    "SpaceError",
    "Store",
    "Suite",
    "Transport",
    "Validate",
    "Validator",
    "Verifier",
    "Vreport",
    "__version__",
    "generate_record_id",
]
