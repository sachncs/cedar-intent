"""Validation wrappers for Cedar source text.

Validation is a strict two-step process: every policy statement must
parse, and the resulting set must validate against the supplied schema.
We do not check intent or correctness here; those concerns belong to
:mod:`cedar_intent.scenarios`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cedarpy import format_policies, validate_policies

from .errors import ValidationError
from .schema import CedarSchema


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Outcome of a validation pass.

    Attributes:
        passed: ``True`` when every statement parsed and validated.
        errors: Error messages reported by the Cedar engine (empty on success).
        formatted: Formatted Cedar source text for every accepted statement.
    """

    passed: bool
    errors: tuple[str, ...]
    formatted: tuple[str, ...]

    def to_dict(self) -> Mapping[str, object]:
        """Return a JSON-friendly representation of the validation result."""
        return {
            "passed": self.passed,
            "errors": list(self.errors),
            "formatted": list(self.formatted),
        }


def validate_cedar(policies: Sequence[str], schema: CedarSchema) -> ValidationReport:
    """Validate Cedar statements against the schema and return a structured report.

    Args:
        policies: Cedar source text for each statement.
        schema: The Cedar schema to validate against.

    Returns:
        A :class:`ValidationReport` describing the outcome.

    Raises:
        ValidationError: If parsing or schema validation fails.
    """
    policy_text = tuple(policies)
    combined = "\n\n".join(policy_text)
    try:
        result = validate_policies(combined, schema.handle)
    except (TypeError, ValueError) as error:
        raise ValidationError((str(error),), combined) from error
    if not result.validation_passed:
        raise ValidationError(tuple(str(error) for error in result.errors), combined)
    formatted: list[str] = []
    for source in policy_text:
        try:
            formatted.append(format_policies(source).strip())
        except (TypeError, ValueError) as error:
            raise ValidationError((f"format failed: {error}",), source) from error
    return ValidationReport(passed=True, errors=(), formatted=tuple(formatted))


__all__ = ["ValidationReport", "validate_cedar"]
