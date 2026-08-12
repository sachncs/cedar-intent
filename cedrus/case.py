"""Authorization scenarios for testing compiled policies.

A :class:`Case` represents a single Cedar authorization request
(principal, action, resource, context) plus the expected decision
(``"Allow"`` or ``"Deny"``). The :func:`Run` function evaluates a
sequence of :class:`Case` objects against compiled Cedar sources
and returns a structured :class:`Suite` with per-scenario outcomes.

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
    Suite: Aggregate result of a :func:`Run` call.
    Decision: Literal type for the expected / actual decisions.
    Run: Evaluate a list of :class:`Case` against Cedar sources and
        return a :class:`Suite` (the :attr:`Run.result` attribute).

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
        ``[cls.load([source])]`` and is convenient for one-off
        CLI / API calls.

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
            items: Sequence[Mapping[str, Any]] = [source]
        else:
            items = source
        cases: list[Case] = []
        for index, item in enumerate(items):
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
            A dict with ``scenario``, ``expected``, ``actual``,
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
            A dict with ``passed`` and ``results`` keys.
        """
        return {
            "passed": self.passed,
            "results": [result.to_dict() for result in self.results],
        }


@dataclass(frozen=True)
class Run:
    """Evaluate a sequence of :class:`Case` objects against a schema and policies.

    Subclass for alternate engines: override :meth:`evaluate_one`
    to plug in a different backend (e.g. an in-process mock for
    hermetic unit tests) while keeping the public :class:`Outcome` /
    :class:`Suite` contract.

    Attributes:
        cases: The scenarios to evaluate.
        result: Per-scenario outcomes aggregated into a :class:`Suite`
            (populated by :meth:`evaluate`; ``None`` until then).
    """

    cases: Sequence[Case]
    result: Suite | None = None

    def evaluate(
        self,
        schema: Schema,
        policies: Sequence[str],
    ) -> Suite:
        """Run every :attr:`cases` against ``policies`` and ``schema``.

        Args:
            schema: The Cedar schema to use for evaluation.
            policies: Cedar source for every compiled policy under
                test.

        Returns:
            The populated :class:`Suite`. Also stored on
                ``self.result`` so callers can inspect the run after
                the call returns.
        """
        policy_set = PolicySet.from_str("\n\n".join(policies))
        outcomes = tuple(
            self.evaluate_one(schema, scenario, policy_set)
            for scenario in self.cases
        )
        suite = Suite(
            passed=all(result.passed for result in outcomes),
            results=outcomes,
        )
        self.__dict__["result"] = suite  # bypass frozen __setattr__
        return suite

    def evaluate_one(
        self,
        schema: Schema,
        scenario: Case,
        policy_set: Any,
    ) -> Outcome:
        """Evaluate a single :class:`Case` against ``policy_set``.

        The default implementation calls :func:`cedarpy.is_authorized`.
        Subclasses override this to plug in a different engine.

        Args:
            schema: The Cedar schema to use.
            scenario: The scenario to evaluate.
            policy_set: An already-built :class:`cedarpy.PolicySet`
                (or any backend-specific equivalent).

        Returns:
            The :class:`Outcome` for ``scenario``.

        Raises:
            Validate: If the engine returns a decision string that is
                not ``"Allow"`` or ``"Deny"``.
        """
        request: dict[str, Any] = {
            "principal": scenario.principal,
            "action": scenario.action,
            "resource": scenario.resource,
            "context": scenario.context,
        }
        auth_result = is_authorized(
            request, policy_set, [], schema=schema.handle
        )
        actual_str = auth_result.decision.name
        if actual_str == "Allow":
            actual: Decision = "Allow"
        elif actual_str == "Deny":
            actual = "Deny"
        else:
            raise Validate(f"unknown Cedar decision: {actual_str!r}")
        diagnostics: dict[str, Any] = {}
        reasons = getattr(
            getattr(auth_result, "diagnostics", None), "reasons", None
        )
        if reasons is not None:
            diagnostics["reasons"] = list(reasons)
        return Outcome(
            scenario=scenario,
            actual=actual,
            passed=actual == scenario.expected,
            diagnostics=diagnostics,
        )


__all__ = ["Case", "Decision", "Outcome", "Run", "Suite"]