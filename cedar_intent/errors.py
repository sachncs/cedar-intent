"""Exception hierarchy for cedar-intent.

Every error raised by the library inherits from :class:`CedarIntentError`,
which lets callers handle the entire family with a single ``except`` clause.
More specific categories are exposed as direct subclasses.
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
