"""Authorization scenarios for testing compiled policies.

A :class:`Scenario` represents a single Cedar authorization request and the
expected decision. Scenarios are executed through :func:`run_scenarios`,
which returns a structured :class:`TestReport`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from cedarpy import PolicySet, is_authorized

from .errors import ValidationError
from .schema import CedarSchema

Decision = Literal["Allow", "Deny"]


@dataclass(frozen=True, slots=True)
class Scenario:
    """A single Cedar authorization scenario.

    Attributes:
        name: Human-readable scenario identifier.
        principal: Cedar principal string for the request.
        action: Cedar action string for the request.
        resource: Cedar resource string for the request.
        context: Free-form context attributes for the request.
        expected: The expected decision (``"Allow"`` or ``"Deny"``).
    """

    name: str
    principal: str
    action: str
    resource: str
    context: Mapping[str, Any]
    expected: Decision

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("scenario name must be non-empty")
        if self.expected not in {"Allow", "Deny"}:
            raise ValueError(f"scenario {self.name} expected must be Allow or Deny")


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    """Outcome of running a single scenario."""

    scenario: Scenario
    actual: Decision
    passed: bool
    diagnostics: Mapping[str, Any]

    def to_dict(self) -> Mapping[str, object]:
        """Return a JSON-friendly representation of the scenario result."""
        return {
            "scenario": self.scenario.name,
            "expected": self.scenario.expected,
            "actual": self.actual,
            "passed": self.passed,
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class TestReport:
    """Aggregate outcome of a scenario run."""

    passed: bool
    results: tuple[ScenarioResult, ...]

    def to_dict(self) -> Mapping[str, object]:
        """Return a JSON-friendly representation of the test report."""
        return {
            "passed": self.passed,
            "results": [result.to_dict() for result in self.results],
        }


def load_scenarios(mapping: Sequence[Mapping[str, Any]]) -> list[Scenario]:
    """Build :class:`Scenario` objects from a JSON-friendly mapping.

    Args:
        mapping: Sequence of dictionaries with ``principal``, ``action``,
            ``resource``, ``context``, ``expected``, and optional ``name``.

    Returns:
        The list of parsed scenarios.
    """
    scenarios: list[Scenario] = []
    for index, item in enumerate(mapping):
        if not isinstance(item, Mapping):
            raise ValueError(f"scenario entry {index} is not an object")
        expected = str(item["expected"])
        if expected not in {"Allow", "Deny"}:
            raise ValueError(
                f"scenario {index} expected must be Allow or Deny, got {expected!r}"
            )
        scenarios.append(
            Scenario(
                name=str(item.get("name") or f"scenario-{index}"),
                principal=str(item["principal"]),
                action=str(item["action"]),
                resource=str(item["resource"]),
                context=dict(item.get("context") or {}),
                expected=expected,  # type: ignore[arg-type]
            )
        )
    return scenarios


def run_scenarios(
    policies: Sequence[str],
    entities: Sequence[Mapping[str, Any]],
    scenarios: Sequence[Scenario],
    schema: CedarSchema | None = None,
) -> TestReport:
    """Execute a set of scenarios against compiled policies.

    Args:
        policies: Cedar source for every compiled policy to test.
        entities: Entities to expose to the Cedar engine during evaluation.
        scenarios: Scenarios to execute.
        schema: Optional schema; an empty schema is used when omitted.

    Returns:
        A :class:`TestReport` containing the outcome of each scenario.
    """
    effective_schema = schema
    if effective_schema is None:
        try:
            effective_schema = CedarSchema.from_mapping(
                {"": {"entityTypes": {}, "actions": {}}}
            )
        except ValidationError as error:  # pragma: no cover - defensive
            raise RuntimeError("default schema failed") from error
    policy_set = PolicySet.from_str("\n\n".join(policies))
    entity_list: list[dict[str, Any]] = [dict(entity) for entity in entities]
    results: list[ScenarioResult] = []
    for scenario in scenarios:
        request: dict[str, Any] = {
            "principal": scenario.principal,
            "action": scenario.action,
            "resource": scenario.resource,
            "context": scenario.context,
        }
        auth_result = is_authorized(
            request, policy_set, entity_list, schema=effective_schema.handle
        )
        actual = "Allow" if auth_result.decision.name == "Allow" else "Deny"
        actual_decision: Decision = actual  # type: ignore[assignment]
        diagnostics: dict[str, Any] = {}
        reasons = getattr(getattr(auth_result, "diagnostics", None), "reasons", None)
        if reasons is not None:
            diagnostics["reasons"] = list(reasons)
        results.append(
            ScenarioResult(
                scenario=scenario,
                actual=actual_decision,
                passed=actual == scenario.expected,
                diagnostics=diagnostics,
            )
        )
    return TestReport(passed=all(result.passed for result in results), results=tuple(results))


__all__ = [
    "Decision",
    "Scenario",
    "ScenarioResult",
    "TestReport",
    "load_scenarios",
    "run_scenarios",
]
