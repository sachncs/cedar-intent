"""Validation wrappers for Cedar source text.

Validation is a strict two-step process: every policy statement must
parse, and the resulting set must validate against the supplied schema.
This module does not check intent or correctness — those concerns
belong to :mod:`cedar_intent.scenarios` and :mod:`cedar_intent.verification`.

Why a two-step pipeline
----------------------

Cedar's parse step catches syntactic errors (mismatched parentheses,
malformed operators, etc.) while the schema-validation step catches
semantic errors (unknown entity types, wrong-typed attributes,
inapplicable actions). Reporting both errors separately gives the
caller enough context to fix the policy without round-tripping
through cedarpy's internal types.

The Cedar source is also passed through Cedar's formatter after a
successful parse so the stored and emitted policies use a single
canonical layout.
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
    # cedarpy raises TypeError for non-string policies and ValueError for
    # malformed Cedar syntax; surface each with a distinct message.
    try:
        result = validate_policies(combined, schema.handle)
    except TypeError as error:
        raise ValidationError((f"policy input is not a string: {error}",), combined) from error
    except ValueError as error:
        raise ValidationError((str(error),), combined) from error
    if not result.validation_passed:
        raise ValidationError(tuple(str(error) for error in result.errors), combined)
    formatted: list[str] = []
    for source in policy_text:
        # ``format_policies`` only raises ValueError on truly unparseable
        # input that was already accepted by validate_policies; the TypeError
        # branch is defensive against the rare case where cedarpy tightens
        # its typing.
        try:
            formatted.append(format_policies(source).strip())
        except ValueError as error:
            raise ValidationError((f"format failed: {error}",), source) from error
        except TypeError as error:
            raise ValidationError(
                (f"format received non-string input: {error}",), source
            ) from error
    return ValidationReport(passed=True, errors=(), formatted=tuple(formatted))


__all__ = ["ValidationReport", "validate_cedar"]
