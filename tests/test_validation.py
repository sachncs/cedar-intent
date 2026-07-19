"""Tests for Cedar validation helpers."""

from __future__ import annotations

import pytest

from cedar_intent import CedarSchema, ValidationError, validate_cedar

VALID_POLICY = (
    'permit (principal == PhotoFlash::User::"alice", '
    'action == PhotoFlash::Action::"viewPhoto", '
    'resource == PhotoFlash::Photo::"p1");'
)


def test_validate_cedar_returns_report(schema: CedarSchema) -> None:
    report = validate_cedar([VALID_POLICY], schema)
    assert report.passed is True
    assert report.errors == ()
    assert report.formatted
    assert "permit" in report.formatted[0]


def test_validate_cedar_raises_on_invalid(schema: CedarSchema) -> None:
    bogus = (
        'permit (principal == PhotoFlash::User::"alice", '
        'action == PhotoFlash::Action::"download", '
        'resource == PhotoFlash::Photo::"p1");'
    )
    with pytest.raises(ValidationError) as exc:
        validate_cedar([bogus], schema)
    assert exc.value.errors
    assert "download" in str(exc.value.errors)


def test_validate_cedar_invalid_format_raises(schema: CedarSchema) -> None:
    bad = (
        'permit (principal is not valid syntax , '
        'action == Action::"viewPhoto", '
        'resource == PhotoFlash::Photo::"p1");'
    )
    with pytest.raises(ValidationError):
        validate_cedar([bad], schema)


def test_validate_cedar_report_serializable(schema: CedarSchema) -> None:
    report = validate_cedar([VALID_POLICY], schema)
    assert report.to_dict()["passed"] is True
