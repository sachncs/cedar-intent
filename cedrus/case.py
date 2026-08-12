"""Authorization scenarios for testing compiled policies.

A :class:`Case` represents a single Cedar authorization request
(principal, action, resource, context) plus the expected decision
(``"Allow"`` or ``"Deny"``). Scenarios are executed through
:class:`Runner`, which returns a structured :class:`Suite` with
per-scenario outcomes.

Why scenarios as a separate concept
------------------------------------

Cedar validation only proves that a policy parses and references the
schema correctly. Scenarios prove that the policy produces the
expected decision for a concrete request. Without scenarios, a
``forbid`` shadowing a ``permit`` would still pass schema validation
even though the ``permit`` never fires; only a scenario test catches
that.

Scenarios are intentionally JSON-serializable so a CI run can load
them from a file and compare the output to a recorded expected set
without running the Python API directly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from cedarpy import PolicySet, is_authorized

from .error import Validate
from .schema import Schema

Decision = Literal["Allow", "Deny"]


@dataclass(frozen=True, slots=True)
class Case:
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

    @classmethod
    def load(cls, mapping: Sequence[Mapping[str, Any]]) -> list[Case]:
        """Build :class:`Case` objects from a JSON-friendly mapping.

        Args:
            mapping: Sequence of dictionaries with ``principal``, ``action``,
                ``resource``, ``context``, ``expected``, and optional ``name``.

        Returns:
            The list of parsed scenarios.
        """
        cases: list[Case] = []
        for index, item in enumerate(mapping):
            if not isinstance(item, Mapping):
                raise ValueError(f"scenario entry {index} is not an object")
            expected = str(item["expected"])
            if expected not in {"Allow", "Deny"}:
                raise ValueError(
                    f"scenario {index} expected must be Allow or Deny, got {expected!r}"
                )
            cases.append(
                cls(
                    name=str(item.get("name") or f"scenario-{index}"),
                    principal=str(item["principal"]),
                    action=str(item["action"]),
                    resource=str(item["resource"]),
                    context=dict(item.get("context") or {}),
                    expected=expected,  # type: ignore[arg-type]
                )
            )
        return cases


@dataclass(frozen=True, slots=True)
class Outcome:
    """Outcome of running a single scenario."""

    scenario: Case
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
class Suite:
    """Aggregate outcome of a scenario run."""

    passed: bool
    results: tuple[Outcome, ...]

    def to_dict(self) -> Mapping[str, object]:
        """Return a JSON-friendly representation of the test report."""
        return {
            "passed": self.passed,
            "results": [result.to_dict() for result in self.results],
        }


class Runner:
    """Scenario runner. Subclass for alternate scenario backends.

    Attributes:
        schema: The Cedar schema to use for evaluation.
    """

    def __init__(self, schema: Schema) -> None:
        self.schema = schema

    def run(
        self,
        policies: Sequence[str],
        cases: Sequence[Case],
    ) -> Suite:
        """Execute every scenario against the supplied Cedar sources.

        Args:
            policies: Cedar source for every compiled policy under test.
            cases: Scenarios to execute.

        Returns:
            A :class:`Suite` containing the outcome of each scenario.
        """
        policy_set = PolicySet.from_str("\n\n".join(policies))
        entity_list: list[dict[str, Any]] = []
        results: list[Outcome] = []
        for scenario in cases:
            request: dict[str, Any] = {
                "principal": scenario.principal,
                "action": scenario.action,
                "resource": scenario.resource,
                "context": scenario.context,
            }
            auth_result = is_authorized(
                request, policy_set, entity_list, schema=self.schema.handle
            )
            actual_str = auth_result.decision.name
            actual: Decision = "Allow" if actual_str == "Allow" else "Deny"
            diagnostics: dict[str, Any] = {}
            reasons = getattr(
                getattr(auth_result, "diagnostics", None), "reasons", None
            )
            if reasons is not None:
                diagnostics["reasons"] = list(reasons)
            results.append(
                Outcome(
                    scenario=scenario,
                    actual=actual,
                    passed=actual == scenario.expected,
                    diagnostics=diagnostics,
                )
            )
        return Suite(
            passed=all(result.passed for result in results),
            results=tuple(results),
        )


__all__ = ["Case", "Decision", "Outcome", "Runner", "Suite"]
