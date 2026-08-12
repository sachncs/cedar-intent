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

Attributes:
    Case: A single Cedar authorization scenario.
    Outcome: Result of running a single :class:`Case`.
    Suite: Aggregate result of a :class:`Runner.run` call.
    Runner: Scenario runner. Subclass for alternate scenario backends.
    Decision: Literal type for the expected / actual decisions.

See Also:
    :mod:`cedrus.verify`: Static verification (shadowing / redundancy
        / coverage) that complements the dynamic scenario runner.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from cedarpy import PolicySet, is_authorized

from cedrus.error import Validate
from cedrus.schema import Schema

Decision = Literal["Allow", "Deny"]


def decision_from_str(value: str) -> Decision:
    """Map a Cedar engine decision string to the :data:`Decision` literal.

    Centralizes the ``"Allow"`` / ``"Deny"`` mapping so the runner
    doesn't have to know the engine's exact casing / naming.

    Args:
        value: Decision string from the engine (typically
            ``auth_result.decision.name``).

    Returns:
        The corresponding :data:`Decision` literal.

    Raises:
        Validate: If ``value`` is not a recognized decision.
    """
    if value == "Allow":
        return "Allow"
    if value == "Deny":
        return "Deny"
    raise Validate(f"unknown Cedar decision: {value!r}")


def case_from_mapping(item: Mapping[str, Any], index: int) -> Case:
    """Build a single :class:`Case` from one JSON-style mapping.

    Shared entry point used by :meth:`Case.load` (and any future
    single-mapping loader) so the field validation lives in one
    place.

    Args:
        item: Mapping carrying ``principal``, ``action``,
            ``resource``, ``context``, ``expected`` and optional
            ``name``.
        index: Position of the mapping in its parent sequence; used
            to build a default name when ``name`` is missing.

    Returns:
        The constructed :class:`Case`.

    Raises:
        ValueError: If the mapping is missing a required field or
            carries an invalid ``expected`` value.
    """
    if not isinstance(item, Mapping):
        raise ValueError(f"scenario entry {index} is not an object")
    expected = str(item["expected"])
    if expected not in {"Allow", "Deny"}:
        raise ValueError(
            f"scenario {index} expected must be Allow or Deny, got {expected!r}"
        )
    return Case(
        name=str(item.get("name") or f"scenario-{index}"),
        principal=str(item["principal"]),
        action=str(item["action"]),
        resource=str(item["resource"]),
        context=dict(item.get("context") or {}),
        expected=expected,  # type: ignore[arg-type]
    )


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
    def load(cls, source: Sequence[Mapping[str, Any]] | Mapping[str, Any]) -> list[Case]:
        """Build :class:`Case` objects from a JSON-style source.

        Polymorphic on the source shape: accepts either a single
        mapping (one scenario) or a sequence of mappings (a list of
        scenarios). The single-mapping form is sugar for
        ``[cls.load(seq)]`` and is convenient for one-off CLI / API
        calls.

        Args:
            source: Either a single dict or a sequence of dicts with
                ``principal``, ``action``, ``resource``, ``context``,
                ``expected`` and optional ``name`` keys.

        Returns:
            The list of parsed :class:`Case` objects.

        Raises:
            ValueError: If any entry is missing a required field or
                carries an invalid ``expected`` value.
        """
        if isinstance(source, Mapping):
            return [case_from_mapping(source, 0)]
        return [case_from_mapping(item, index) for index, item in enumerate(source)]


@dataclass(frozen=True, slots=True)
class Outcome:
    """Outcome of running a single scenario.

    Attributes:
        scenario: The :class:`Case` that was evaluated.
        actual: The decision the engine returned.
        passed: ``True`` when ``actual == scenario.expected``.
        diagnostics: Free-form diagnostics (e.g. policy trace).
    """

    scenario: Case
    actual: Decision
    passed: bool
    diagnostics: Mapping[str, Any]

    def to_dict(self) -> Mapping[str, object]:
        """Return a JSON-friendly representation of the scenario result.

        Returns:
            Dict with ``scenario``, ``expected``, ``actual``,
            ``passed`` and ``diagnostics`` keys.
        """
        return {
            "scenario": self.scenario.name,
            "expected": self.scenario.expected,
            "actual": self.actual,
            "passed": self.passed,
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class Suite:
    """Aggregate outcome of a scenario run.

    Attributes:
        passed: ``True`` when every :class:`Outcome` passed.
        results: Per-scenario :class:`Outcome` tuples in run order.
    """

    passed: bool
    results: tuple[Outcome, ...]

    def to_dict(self) -> Mapping[str, object]:
        """Return a JSON-friendly representation of the test report.

        Returns:
            Dict with ``passed`` and ``results`` keys.
        """
        return {
            "passed": self.passed,
            "results": [result.to_dict() for result in self.results],
        }


class Runner:
    """Scenario runner. Subclass for alternate scenario backends.

    The default implementation evaluates every :class:`Case` against
    the supplied Cedar sources via :func:`cedarpy.is_authorized`.
    Subclasses can override :meth:`run` (or just :meth:`evaluate_one`
    in :attr:`runner_engine`) to plug in a different engine while
    keeping the public :class:`Outcome` / :class:`Suite` contract.

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
            policies: Cedar source for every compiled policy under
                test.
            cases: Scenarios to execute.

        Returns:
            A :class:`Suite` containing the outcome of each scenario.
        """
        policy_set = PolicySet.from_str("\n\n".join(policies))
        results: list[Outcome] = []
        for scenario in cases:
            actual, diagnostics = self.evaluate_one(scenario, policy_set)
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

    def evaluate_one(
        self,
        scenario: Case,
        policy_set: Any,
    ) -> tuple[Decision, dict[str, Any]]:
        """Evaluate a single :class:`Case` against ``policy_set``.

        The default implementation calls :func:`cedarpy.is_authorized`.
        Subclasses override this to plug in a different evaluation
        engine (e.g. an in-process mock for hermetic unit tests).

        Args:
            scenario: The scenario to evaluate.
            policy_set: An already-built :class:`cedarpy.PolicySet`
                (or any backend-specific equivalent).

        Returns:
            A ``(actual, diagnostics)`` tuple. ``actual`` is the
            engine's decision as a :data:`Decision` literal;
            ``diagnostics`` is a free-form dict (e.g. ``{"reasons":
            [...]}``).
        """
        request: dict[str, Any] = {
            "principal": scenario.principal,
            "action": scenario.action,
            "resource": scenario.resource,
            "context": scenario.context,
        }
        auth_result = is_authorized(
            request, policy_set, [], schema=self.schema.handle
        )
        actual = decision_from_str(auth_result.decision.name)
        diagnostics: dict[str, Any] = {}
        reasons = getattr(
            getattr(auth_result, "diagnostics", None), "reasons", None
        )
        if reasons is not None:
            diagnostics["reasons"] = list(reasons)
        return actual, diagnostics


__all__ = ["Case", "Decision", "Outcome", "Runner", "Suite"]
