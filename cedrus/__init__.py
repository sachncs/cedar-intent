"""cedrus public API.

The package exposes a typed, OOP-first surface for compiling
organizational authorization intent into validated, deployable
Cedar policies. The package itself only re-exports; every public
symbol is defined under its own module and documented there.

Architecture at a glance
------------------------

The pipeline flows through these classes:

* :class:`~cedrus.need.Need` — Markdown requirement with stable id
  and domain.
* :class:`~cedrus.policies.draft.Draft` — scope-typed draft proposal.
* :class:`~cedrus.generate.Generator` produces a typed
  :class:`~cedrus.compile.Intent`; two implementations ship
  (:class:`~cedrus.generate.Offline` and :class:`~cedrus.generate.Llm`).
* :meth:`Intent.compile <cedrus.compile.Intent.compile>` renders the
  intent to Cedar source text.
* :class:`~cedrus.validate.Validator` runs Cedar parse and schema
  validation.
* :class:`~cedrus.case.Run` exercises a list of :class:`~cedrus.case.Case`
  against the policy and returns a :class:`~cedrus.case.Suite`.
* :class:`~cedrus.verify.Verifier` runs static checks for shadowing,
  redundancy, and coverage.
* :class:`~cedrus.deploy.Bundler` and :class:`~cedrus.deploy.Client`
  produce and push the deployment bundle.

The :class:`~cedrus.space.Workspace` class orchestrates every stage
and is the recommended entry point for Python users.

Attributes:
    Action: Scope shape for the ``action`` slot of a Cedar policy.
    Backend: SQLite-backed storage implementation.
    Bundler: Assembles and writes Cedar deployment bundles.
    Case: A single Cedar authorization scenario.
    Clause: A single ``when`` or ``unless`` clause carried by a draft.
    Client: Pushes a :class:`Manifest` to a local directory or HTTP endpoint.
    Compile: Raised when intent compilation fails.
    Compiled: A policy that has been compiled and validated.
    Config: Raised on invalid configuration or CLI input.
    Context: Input bundle for a generator call.
    Deploy: Raised on deployment failure.
    Domain: One authorization domain inside a :class:`~cedrus.space.Workspace`.
    Draft: A draft policy carrying explicit scopes.
    Error: Base class for every cedrus exception.
    Existing: A policy imported from raw Cedar source.
    Extraction: Scope and condition data extracted from a Cedar policy.
    Fault: Raised when a typed-object operation cannot complete.
    Finding: A single finding emitted by verification.
    Generate: Raised on generator failure.
    Generator: Protocol every generator implements.
    Guard: SSRF guard rejecting loopback / private / link-local targets.
    Intent: Typed authorization intent for one policy.
    Kind: Abstract base for every policy object.
    Llm: LiteLLM-backed generator.
    Manifest: Self-contained deployment artifact.
    Memory: Dictionary-backed repository for tests.
    Need: An atomic authorization requirement.
    Offline: Deterministic generator for offline / test use.
    Outcome: Result of running a single :class:`Case`.
    Pin: Pinned connection target returned by a :class:`Guard`.
    Principal: Scope shape for the ``principal`` slot.
    Proposal: One generator proposal for a single requirement.
    Record: Persisted record of a successful deployment.
    Repository: Protocol every storage backend must implement.
    Require: Raised on requirement parsing / validation failure.
    Resource: Scope shape for the ``resource`` slot.
    Result: Final output of a generator call with provenance.
    Schema: Parsed Cedar JSON schema.
    Scope: Abstract base for every scope shape.
    ScopeFault: Raised on invalid scope construction.
    Source: Output of the deterministic compiler.
    SpaceError: Alias for the workspace-level error class.
    Store: Raised on storage failure.
    Suite: Aggregate result of a :class:`Run` call.
    Transport: httpx transport that pins connections to a resolved IP.
    Validate: Raised on schema or engine validation failure.
    Validator: Schema validator wrapper around the Cedar engine.
    Verifier: Static symbolic verifier.
    Vreport: Outcome of a validation pass.
    Workspace: Top-level cedrus orchestrator.

See Also:
    :mod:`cedrus.case`: Authorization scenarios.
    :mod:`cedrus.compile`: Intent dataclass and deterministic compiler.
    :mod:`cedrus.deploy`: Bundle assembly and HTTP / local push.
    :mod:`cedrus.domain`: Per-domain state container.
    :mod:`cedrus.error`: Exception hierarchy.
    :mod:`cedrus.generate`: Generator protocol and implementations.
    :mod:`cedrus.need`: Requirement Markdown loader.
    :mod:`cedrus.policies`: Draft / Compiled / Existing policy shapes.
    :mod:`cedrus.schema`: Cedar JSON schema parser.
    :mod:`cedrus.scope`: Scope-shape dataclasses.
    :mod:`cedrus.space`: Workspace orchestrator (recommended entry point).
    :mod:`cedrus.store`: Storage Protocol and backends.
    :mod:`cedrus.validate`: Cedar parse + schema validation.
    :mod:`cedrus.verify`: Static verification (shadowing / redundancy / coverage).
"""

from __future__ import annotations

from cedrus.case import Case, Outcome, Suite
from cedrus.compile import Intent, Source
from cedrus.deploy import (
    Bundler,
    Client,
    Guard,
    Manifest,
    Pin,
    Record,
    Transport,
)
from cedrus.domain import Domain
from cedrus.error import (
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
from cedrus.error import Space as SpaceError
from cedrus.generate import (
    Context,
    Generator,
    Llm,
    Offline,
    Proposal,
    Result,
)
from cedrus.need import Need
from cedrus.policies import Compiled, Draft, Existing, Kind
from cedrus.schema import Schema
from cedrus.scope import Action, Clause, Principal, Resource, Scope
from cedrus.space import Workspace
from cedrus.store import Backend, Memory, Repository
from cedrus.validate import Validator, Vreport
from cedrus.verify import Extraction, Finding, Report, Verifier

__version__ = "0.7.0"

__all__ = [
    "Action",
    "Backend",
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
    "Scope",
    "ScopeFault",
    "Source",
    "SpaceError",
    "Store",
    "Suite",
    "Transport",
    "Validate",
    "Validator",
    "Verifier",
    "Vreport",
    "Workspace",
    "__version__",
]