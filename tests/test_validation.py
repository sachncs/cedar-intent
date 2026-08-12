"""Tests for Cedar validation helpers."""

from __future__ import annotations

import pytest

from cedrus import Schema, Validate, validate_cedar

VALID_POLICY = (
    'permit (principal == PhotoFlash::User::"alice", '
    'action == PhotoFlash::Action::"viewPhoto", '
    'resource == PhotoFlash::Photo::"p1");'
)


def test_validate_cedar_returns_report(schema: Schema) -> None:
    report = validate_cedar([VALID_POLICY], schema)
    assert report.passed is True
    assert report.errors == ()
    assert report.formatted
    assert "permit" in report.formatted[0]


def test_validate_cedar_raises_on_invalid(schema: Schema) -> None:
    bogus = (
        'permit (principal == PhotoFlash::User::"alice", '
        'action == PhotoFlash::Action::"download", '
        'resource == PhotoFlash::Photo::"p1");'
    )
    with pytest.raises(Validate) as exc:
        validate_cedar([bogus], schema)
    assert exc.value.errors
    assert "download" in str(exc.value.errors)


def test_validate_cedar_invalid_format_raises(schema: Schema) -> None:
    bad = (
        'permit (principal is not valid syntax , '
        'action == Action::"viewPhoto", '
        'resource == PhotoFlash::Photo::"p1");'
    )
    with pytest.raises(Validate):
        validate_cedar([bad], schema)


def test_validate_cedar_report_serializable(schema: Schema) -> None:
    report = validate_cedar([VALID_POLICY], schema)
    assert report.to_dict()["passed"] is True
