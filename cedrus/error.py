"""Exception hierarchy for cedrus.

Every error raised by the library inherits from :class:`Error`,
which lets callers handle the entire family with a single ``except``
clause. More specific categories are exposed as direct subclasses so
callers can narrow their handling when needed.

Hierarchy:
    The hierarchy is organized by responsibility, not by layer:

    * :class:`Error` - base class. Catch this when you want every
      cedrus error.
    * :class:`Config` - bad configuration (CLI flags, env vars, invalid
      generator options).
    * :class:`Require` - missing or malformed requirement files.
    * :class:`Fault` - policy-level issues, plus four subclasses:
      :class:`Compile`, :class:`Validate`, :class:`Generate`,
      :class:`ScopeFault`.
    * :class:`Store` - repository-level failures such as missing records.
    * :class:`Space` - workspace-level invariants violated.
    * :class:`Deploy` - deployment operation failed.
    * :class:`Parse` - cedarpy could not parse a policy.

Threading and pickling:
    All exceptions are plain :class:`Exception` subclasses and are
    safe to propagate across thread boundaries. The :class:`Validate`
    adds ``errors`` and ``policy_source`` attributes for downstream
    diagnostic surfaces; other errors keep the default
    :class:`Exception` shape.

Attributes:
    Error: Base class for every error raised by cedrus.
    Config: Bad configuration.
    Require: Missing or malformed requirement file.
    Fault: Base for policy-level errors.
    Compile: Draft could not be compiled to Cedar source.
    Validate: Cedar parse or schema-validation failure.
    Generate: Generator failed to produce a proposal.
    ScopeFault: Scope object is malformed.
    Store: Repository-level failure (e.g. missing record).
    Space: Workspace-level invariant violation.
    Deploy: Deployment operation failed.
    Parse: cedarpy could not parse a policy.
"""

from __future__ import annotations


class Error(Exception):
    """Base class for every error raised by cedrus."""


class Config(Error):
    """Raised when a configuration value is missing or invalid."""


class Require(Error):
    """Raised when a requirement file is missing or malformed."""


class Fault(Error):
    """Base class for every error related to a policy object."""


class Compile(Fault):
    """Raised when a draft cannot be compiled to Cedar source."""


class Generate(Fault):
    """Raised when a generator fails to produce a proposal."""


class ScopeFault(Fault):
    """Raised when a scope object is malformed."""


class Store(Error):
    """Raised for repository-level failures such as missing records."""


class Space(Error):
    """Raised when the workspace is in an inconsistent state."""


class Deploy(Error):
    """Raised when a deployment operation fails."""


class Parse(Error):
    """Raised when cedarpy cannot parse a policy."""


class Validate(Fault):
    """Raised when Cedar parsing or schema validation fails.

    Attributes:
        errors: The list of error messages reported by the Cedar engine.
        policy_source: The Cedar source text that triggered the failure.
    """

    def __init__(self, errors: tuple[str, ...], policy_source: str) -> None:
        """Initialize the validation error.

        Args:
            errors: Error messages reported by the Cedar engine.
            policy_source: The Cedar source text that triggered the
                failure.
        """
        self.errors = errors
        self.policy_source = policy_source
        super().__init__("Cedar validation failed: " + "; ".join(errors))


__all__ = [
    "Compile",
    "Config",
    "Deploy",
    "Error",
    "Fault",
    "Generate",
    "Parse",
    "Require",
    "ScopeFault",
    "Space",
    "Store",
    "Validate",
]
