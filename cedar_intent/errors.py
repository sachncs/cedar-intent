"""Exception hierarchy for cedar-intent.

Every error raised by the library inherits from :class:`CedarIntentError`,
which lets callers handle the entire family with a single ``except``
clause. More specific categories are exposed as direct subclasses so
callers can narrow their handling when needed.

Hierarchy
---------

The hierarchy is organized by responsibility, not by layer:

* :class:`CedarIntentError` - base class. Catch this when you want
  every cedar-intent error.
* :class:`ConfigError` - bad configuration (CLI flags, env vars,
  invalid generator options).
* :class:`RequirementError` - missing or malformed requirement files.
* :class:`PolicyError` - policy-level issues, plus four subclasses:
  :class:`CompilationError`, :class:`ValidationError`,
  :class:`GeneratorError`, :class:`ScopeError`.
* :class:`StorageError` - repository-level failures such as missing
  records.
* :class:`WorkspaceError` - workspace-level invariants violated.
* :class:`DeploymentError` - deployment operation failed.

Threading and pickling
----------------------

All exceptions are plain :class:`Exception` subclasses and are safe
to propagate across thread boundaries. The :class:`ValidationError`
adds ``errors`` and ``policy_source`` attributes for downstream
diagnostic surfaces; other errors keep the default :class:`Exception`
shape.
"""

from __future__ import annotations


class CedarIntentError(Exception):
    """Base class for every error raised by cedar-intent."""


class ConfigError(CedarIntentError):
    """Raised when a configuration value is missing or invalid."""


class RequirementError(CedarIntentError):
    """Raised when a requirement file is missing or malformed."""


class PolicyError(CedarIntentError):
    """Base class for every error related to a policy object."""


class CompilationError(PolicyError):
    """Raised when a draft cannot be compiled to Cedar source."""


class ValidationError(PolicyError):
    """Raised when Cedar parsing or schema validation fails.

    Attributes:
        errors: The list of error messages reported by the Cedar engine.
        policy_source: The Cedar source text that triggered the failure.
    """

    def __init__(self, errors: tuple[str, ...], policy_source: str) -> None:
        self.errors = errors
        self.policy_source = policy_source
        super().__init__("Cedar validation failed: " + "; ".join(errors))


class GeneratorError(PolicyError):
    """Raised when a generator fails to produce a proposal."""


class StorageError(CedarIntentError):
    """Raised for repository-level failures such as missing records."""


class ScopeError(PolicyError):
    """Raised when a scope object is malformed."""


class WorkspaceError(CedarIntentError):
    """Raised when the workspace is in an inconsistent state."""


class DeploymentError(CedarIntentError):
    """Raised when a deployment operation fails."""


__all__ = [
    "CedarIntentError",
    "CompilationError",
    "ConfigError",
    "DeploymentError",
    "GeneratorError",
    "PolicyError",
    "RequirementError",
    "ScopeError",
    "StorageError",
    "ValidationError",
    "WorkspaceError",
]
