"""Tests for scenario loading and execution."""

from __future__ import annotations

import pytest

from cedar_intent import (
    CedarSchema,
    Scenario,
    load_scenarios,
    run_scenarios,
)

VALID_POLICY = (
    'permit (principal == PhotoFlash::User::"alice", '
    'action == PhotoFlash::Action::"viewPhoto", '
    'resource == PhotoFlash::Photo::"p1");'
)
FORBID_POLICY = (
    'forbid (principal == PhotoFlash::User::"bob", '
    'action == PhotoFlash::Action::"viewPhoto", '
    'resource);'
)


def test_scenario_rejects_invalid_decision() -> None:
    with pytest.raises(ValueError):
        Scenario(
            name="bad",
            principal='User::"alice"',
            action='Action::"view"',
            resource='Photo::"p1"',
            context={},
            expected="Maybe",  # type: ignore[arg-type]
        )


def test_scenario_rejects_empty_name() -> None:
    with pytest.raises(ValueError):
        Scenario(
            name="",
            principal='User::"alice"',
            action='Action::"view"',
            resource='Photo::"p1"',
            context={},
            expected="Allow",
        )


def test_load_scenarios_handles_missing_keys() -> None:
    scenarios = load_scenarios(
        [
            {
                "name": "ok",
                "principal": 'User::"alice"',
                "action": 'Action::"view"',
                "resource": 'Photo::"p1"',
                "context": {},
                "expected": "Allow",
            }
        ]
    )
    assert scenarios[0].expected == "Allow"


def test_load_scenarios_rejects_non_mapping() -> None:
    with pytest.raises(ValueError):
        load_scenarios(["not a dict"])  # type: ignore[list-item]


def test_load_scenarios_assigns_default_names() -> None:
    scenarios = load_scenarios(
        [
            {
                "principal": 'User::"alice"',
                "action": 'Action::"view"',
                "resource": 'Photo::"p1"',
                "context": {},
                "expected": "Allow",
            }
        ]
    )
    assert scenarios[0].name == "scenario-0"


def test_run_scenarios_allow_and_deny(schema: CedarSchema) -> None:
    scenarios = [
        Scenario(
            name="alice-can-view",
            principal='PhotoFlash::User::"alice"',
            action='PhotoFlash::Action::"viewPhoto"',
            resource='PhotoFlash::Photo::"p1"',
            context={},
            expected="Allow",
        ),
        Scenario(
            name="bob-denied-by-forbid",
            principal='PhotoFlash::User::"bob"',
            action='PhotoFlash::Action::"viewPhoto"',
            resource='PhotoFlash::Photo::"p1"',
            context={},
            expected="Deny",
        ),
    ]
    report = run_scenarios([VALID_POLICY, FORBID_POLICY], [], scenarios, schema=schema)
    assert report.passed
    assert {result.scenario.name for result in report.results} == {
        "alice-can-view",
        "bob-denied-by-forbid",
    }


def test_run_scenarios_records_failures(schema: CedarSchema) -> None:
    scenarios = [
        Scenario(
            name="wrong-expectation",
            principal='PhotoFlash::User::"alice"',
            action='PhotoFlash::Action::"viewPhoto"',
            resource='PhotoFlash::Photo::"p1"',
            context={},
            expected="Deny",
        )
    ]
    report = run_scenarios([VALID_POLICY], [], scenarios, schema=schema)
    assert not report.passed
    assert report.results[0].passed is False


def test_run_scenarios_without_schema_uses_default() -> None:
    scenarios = [
        Scenario(
            name="deny-default",
            principal='User::"alice"',
            action='Action::"view"',
            resource='Photo::"p1"',
            context={},
            expected="Deny",
        )
    ]
    report = run_scenarios([FORBID_POLICY], [], scenarios)
    assert report.passed
