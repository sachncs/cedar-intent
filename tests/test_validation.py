"""Tests for :mod:`cedrus.validate` — Cedar validation and reports."""
from __future__ import annotations

from typing import cast

import pytest

from cedrus import Schema, Validate, Vreport

VALID_POLICY = (
    'permit (principal == PhotoFlash::User::"alice", '
    'action == PhotoFlash::Action::"viewPhoto", '
    'resource == PhotoFlash::Photo::"p1");'
)


def build_schema() -> Schema:
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
    schema = build_schema()
    report = Vreport.from_cedar([VALID_POLICY], schema)
    assert report.passed is True
    assert report.errors == ()
    assert report.formatted
    assert "permit" in report.formatted[0]


def test_vreport_from_cedar_raises_on_unknown_action() -> None:
    schema = build_schema()
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
    schema = build_schema()
    with pytest.raises(Validate):
        Vreport.from_cedar(["not valid cedar"], schema)


def test_vreport_from_cedar_raises_typeerror_on_non_string_input() -> None:
    """Validate enforces string input; raises Validate via the TypeError branch."""
    from typing import cast

    schema = build_schema()
    with pytest.raises(Validate):
        Vreport.from_cedar(cast(list, [42]), schema)


def test_vreport_to_dict_carries_passed_and_formatted() -> None:
    schema = build_schema()
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
    """Vreport is a frozen dataclass."""
    from dataclasses import asdict

    instance = Vreport(passed=True, errors=(), formatted=())
    snapshot = asdict(instance)
    # asdict preserves the underlying tuple types: errors is a
    # tuple, formatted is a tuple, not list.
    assert snapshot == {"passed": True, "errors": (), "formatted": ()}
    # Frozen instances are also hashable.
    assert hash(instance) == hash(instance)


def test_validator_validate_delegates_to_from_cedar() -> None:
    from cedrus.validate import Validator

    schema = build_schema()
    validator = Validator(schema)
    report = validator.validate([VALID_POLICY])
    assert report.passed


def test_vreport_from_cedar_wraps_typeerror() -> None:
    """Non-string policy input raises Validate via the TypeError branch."""
    schema = build_schema()
    with pytest.raises(Validate) as exc:
        Vreport.from_cedar(cast(list, [42]), schema)
    assert "not a string" in str(exc.value.errors)


def test_vreport_from_cedar_wraps_valueerror() -> None:
    """cedarpy ValueError is rewrapped as Validate."""
    schema = build_schema()
    with pytest.raises(Validate):
        Vreport.from_cedar(["this is not valid cedar syntax !!!"], schema)


def test_vreport_from_cedar_wraps_cedarpy_validation_errors() -> None:
    """When validation fails, the cedarpy error list is surfaced as Validate."""
    schema = build_schema()
    bogus = (
        'permit (principal == PhotoFlash::User::"alice", '
        'action == PhotoFlash::Action::"download", '
        'resource == PhotoFlash::Photo::"p1");'
    )
    with pytest.raises(Validate) as exc:
        Vreport.from_cedar([bogus], schema)
    assert exc.value.errors


__all__ = []