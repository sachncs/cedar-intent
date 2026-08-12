"""Tests for :mod:`cedrus.case` — Case / Outcome / Suite / Run."""
from __future__ import annotations

import pytest

from cedrus import Case, Outcome, Suite
from cedrus.case import Run, Decision


# ---------------------------------------------------------------------------
# Case data modelling
# ---------------------------------------------------------------------------


def test_case_default_decision_field() -> None:
    case = Case(
        name="HR-001",
        principal='PhotoFlash::User::"alice"',
        action='PhotoFlash::Action::"viewPhoto"',
        resource='PhotoFlash::Photo::"p1"',
        context={},
        expected="Allow",
    )
    assert case.expected == "Allow"


def test_case_rejects_invalid_expected_decision() -> None:
    with pytest.raises(ValueError):
        Case(
            name="x",
            principal="p",
            action="a",
            resource="r",
            context={},
            expected="Maybe",  # type: ignore[arg-type]
        )


def test_case_rejects_empty_name() -> None:
    with pytest.raises(ValueError):
        Case(
            name="",
            principal="p",
            action="a",
            resource="r",
            context={},
            expected="Allow",
        )


def test_case_rejects_whitespace_name() -> None:
    with pytest.raises(ValueError):
        Case(
            name="   ",
            principal="p",
            action="a",
            resource="r",
            context={},
            expected="Allow",
        )


# ---------------------------------------------------------------------------
# Case.load — JSON loader
# ---------------------------------------------------------------------------


def test_case_load_accepts_list_of_dicts() -> None:
    items = [
        {
            "name": "test1",
            "principal": "User::\"alice\"",
            "action": "Action::\"view\"",
            "resource": "Photo::\"p1\"",
            "context": {"k": "v"},
            "expected": "Allow",
        },
        {
            "name": "test2",
            "principal": "User::\"bob\"",
            "action": "Action::\"delete\"",
            "resource": "Photo::\"p2\"",
            "context": {},
            "expected": "Deny",
        },
    ]
    cases = Case.load(items)
    assert len(cases) == 2
    assert cases[0].name == "test1"
    assert cases[1].expected == "Deny"


def test_case_load_accepts_single_dict_as_one_case_list() -> None:
    cases = Case.load({
        "name": "single",
        "principal": "p",
        "action": "a",
        "resource": "r",
        "context": {},
        "expected": "Allow",
    })
    assert len(cases) == 1
    assert cases[0].name == "single"


def test_case_load_rejects_non_dict_entry() -> None:
    with pytest.raises(ValueError):
        Case.load([{"name": "x", "principal": "p", "action": "a",
                    "resource": "r", "context": {}, "expected": "Allow"}, 42])


def test_case_load_assigns_default_name_when_missing() -> None:
    cases = Case.load([
        {"principal": "p", "action": "a", "resource": "r",
         "context": {}, "expected": "Allow"}
    ])
    assert cases[0].name  # default non-empty


def test_case_load_raises_on_missing_required_key() -> None:
    with pytest.raises(KeyError):
        Case.load([{"name": "x", "principal": "p", "resource": "r",
                    "context": {}, "expected": "Allow"}])  # missing action


# ---------------------------------------------------------------------------
# Outcome / Suite
# ---------------------------------------------------------------------------


def test_outcome_to_dict_carries_all_fields() -> None:
    case = Case(name="x", principal="p", action="a", resource="r",
                context={}, expected="Allow")
    outcome = Outcome(scenario=case, actual="Allow", passed=True, diagnostics={})
    d = outcome.to_dict()
    assert d["scenario"] == "x"
    assert d["expected"] == "Allow"
    assert d["actual"] == "Allow"
    assert d["passed"] is True
    assert d["diagnostics"] == {}


def test_suite_to_dict_preserves_results() -> None:
    suite = Suite(passed=True, results=())
    d = suite.to_dict()
    assert d["passed"] is True
    assert d["results"] == []


# ---------------------------------------------------------------------------
# Run.evaluate — defaults
# ---------------------------------------------------------------------------


def test_run_default_attributes() -> None:
    run = Run(())
    assert run.cases == ()
    assert run.result is None


def test_run_evaluate_with_empty_cases_returns_passed_suite() -> None:
    run = Run(())
    suite = run.evaluate(_schema(), [])
    assert suite.passed
    assert suite.results == ()


def _schema() -> "Schema":
    from cedrus import Schema

    return Schema.from_mapping(
        {
            "PhotoFlash": {
                "entityTypes": {
                    "User": {"shape": {"type": "Record", "attributes": {}}},
                    "Photo": {"shape": {"type": "Record", "attributes": {}}},
                },
                "actions": {
                    "viewPhoto": {
                        "appliesTo": {
                            "principalTypes": ["User"],
                            "resourceTypes": ["Photo"],
                        }
                    }
                },
            }
        }
    )


__all__ = []