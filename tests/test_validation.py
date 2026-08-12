"""Tests for :mod:`cedrus.validate` — Cedar validation and reports."""
from __future__ import annotations

import pytest

from cedrus import Schema, Validate, Vreport

VALID_POLICY = (
    'permit (principal == PhotoFlash::User::"alice", '
    'action == PhotoFlash::Action::"viewPhoto", '
    'resource == PhotoFlash::Photo::"p1");'
)


def _schema() -> Schema:
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
                    },
                },
            }
        }
    )


def test_vreport_from_cedar_returns_passed_report() -> None:
    schema = _schema()
    report = Vreport.from_cedar([VALID_POLICY], schema)
    assert report.passed is True
    assert report.errors == ()
    assert report.formatted
    assert "permit" in report.formatted[0]


def test_vreport_from_cedar_raises_on_unknown_action() -> None:
    schema = _schema()
    bogus = (
        'permit (principal == PhotoFlash::User::"alice", '
        'action == PhotoFlash::Action::"download", '
        'resource == PhotoFlash::Photo::"p1");'
    )
    with pytest.raises(Validate) as exc:
        Vreport.from_cedar([bogus], schema)
    assert exc.value.errors
    assert "download" in str(exc.value.errors)


def test_vreport_from_cedar_raises_on_malformed_cedar() -> None:
    schema = _schema()
    with pytest.raises(Validate):
        Vreport.from_cedar(["not valid cedar"], schema)


def test_vreport_from_cedar_raises_typeerror_on_non_string_input() -> None:
    """Validate enforces string input at the join step; TypeError is the contract."""
    schema = _schema()
    with pytest.raises(TypeError):
        Vreport.from_cedar([42], schema)  # type: ignore[list-item]


def test_vreport_to_dict_carries_passed_and_formatted() -> None:
    schema = _schema()
    report = Vreport.from_cedar([VALID_POLICY], schema)
    d = report.to_dict()
    assert d["passed"] is True
    assert d["errors"] == []
    assert d["formatted"]


def test_vreport_default_constructor_carries_empty_collections() -> None:
    report = Vreport(passed=True, errors=(), formatted=())
    assert report.passed is True
    assert report.errors == ()
    assert report.formatted == ()


def test_vreport_is_frozen() -> None:
    report = Vreport(passed=True, errors=(), formatted=())
    with pytest.raises(Exception):
        report.passed = False  # type: ignore[misc]


__all__ = []