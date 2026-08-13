"""Verifier adversarial-input tests.

Tests for the structured parser's behavior on hostile or malformed
Cedar source. The pre-0.6.0 regex parser silently degraded to
permit(any/any/any) for anything it couldn't parse; the 0.6.0
verifier must instead emit a malformed-policy finding.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from cedrus import (
    Action,
    Intent,
    Need,
    Principal,
    Resource,
    Verifier,
)


def make_requirement() -> Need:
    return Need(
        id="HR-001",
        text="Body",
        domain="hr",
        source_path=Path("/tmp/HR-001.md"),
        created_at=datetime.now(UTC),
    )


def build_schema():
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


def test_malformed_cedar_emits_finding() -> None:
    schema = build_schema()

    class StubPolicy:
        id = "bad"
        cedar = "this is not valid Cedar !!!"

    report = Verifier(schema).verify(
        [StubPolicy()],
        requirement_ids=["bad"],
        action_names=[("PhotoFlash", "viewPhoto")],
        entity_type_names=[],
        domain="hr",
    )
    malformed = [f for f in report.findings if f.kind == "malformed-policy"]
    assert malformed


def test_comment_containing_permit_does_not_shadow() -> None:
    """A comment with the word 'permit' is not a Cedar policy statement."""
    schema = build_schema()
    policy = type("P", (), {"id": "p", "cedar": "/* permit */"})()
    report = Verifier(schema).verify(
        [policy],
        requirement_ids=["p"],
        action_names=[("PhotoFlash", "viewPhoto")],
        entity_type_names=[],
        domain="hr",
    )
    malformed = [f for f in report.findings if f.kind == "malformed-policy"]
    assert malformed


def test_empty_cedar_emits_malformed_finding() -> None:
    schema = build_schema()
    policy = type("P", (), {"id": "p", "cedar": ""})()
    report = Verifier(schema).verify(
        [policy],
        requirement_ids=["p"],
        action_names=[("PhotoFlash", "viewPhoto")],
        entity_type_names=[],
        domain="hr",
    )
    malformed = [f for f in report.findings if f.kind == "malformed-policy"]
    assert malformed


def test_multiline_permit_parses() -> None:
    """A multi-line permit statement parses correctly."""
    schema = build_schema()
    policy = type("P", (), {"id": "p", "cedar": (
        'permit (\n'
        '    principal == PhotoFlash::User::"alice",\n'
        '    action == PhotoFlash::Action::"viewPhoto",\n'
        '    resource == PhotoFlash::Photo::"p1"\n'
        ');'
    )})()
    report = Verifier(schema).verify(
        [policy],
        requirement_ids=["p"],
        action_names=[("PhotoFlash", "viewPhoto")],
        entity_type_names=[],
        domain="hr",
    )
    # Either parses cleanly, or is flagged malformed — but should not
    # silently accept and then mis-extract.
    parsed_ok = not [f for f in report.findings if f.kind == "malformed-policy"]
    assert parsed_ok


def test_resource_in_parent_parses() -> None:
    """`resource is X in Y` syntax is extracted by cedarpy."""
    schema = build_schema()
    policy = type("P", (), {"id": "p", "cedar": (
        'permit (principal, action == PhotoFlash::Action::"viewPhoto", '
        'resource is PhotoFlash::Photo in PhotoFlash::Album::"v")'
        ';'
    )})()
    report = Verifier(schema).verify(
        [policy],
        requirement_ids=["p"],
        action_names=[("PhotoFlash", "viewPhoto")],
        entity_type_names=[],
        domain="hr",
    )
    # Parses or flagged malformed — not silently mis-extracted.
    assert not [f for f in report.findings if f.kind == "malformed-policy"]


def test_two_policies_with_distinct_conditions_not_redundant() -> None:
    """Two policies with the same scope but different conditions are not redundant."""
    schema = build_schema()
    policy_admin = type("P", (), {
        "id": "HR-001",
        "cedar": (
            'permit (principal, action == Action::"view", resource) '
            'when { principal.role == "admin" };'
        ),
    })()
    policy_anyone = type("P", (), {
        "id": "HR-002",
        "cedar": 'permit (principal, action == Action::"view", resource);',
    })()
    report = Verifier(schema).verify(
        [policy_admin, policy_anyone],
        requirement_ids=["HR-001", "HR-002"],
        action_names=[("PhotoFlash", "view")],
        entity_type_names=[],
        domain="hr",
    )
    assert not any(f.kind == "redundancy" for f in report.findings)


def test_two_policies_with_same_conditions_flagged_redundant() -> None:
    """Two policies with the same condition AST are flagged as redundant."""
    schema = build_schema()
    policy_a = type("P", (), {
        "id": "HR-001",
        "cedar": (
            'permit (principal, action == Action::"view", resource) '
            'when { principal == User::"alice" };'
        ),
    })()
    policy_b = type("P", (), {
        "id": "HR-002",
        "cedar": (
            'permit (principal, action == Action::"view", resource) '
            'when { principal == User::"alice" };'
        ),
    })()
    report = Verifier(schema).verify(
        [policy_a, policy_b],
        requirement_ids=["HR-001", "HR-002"],
        action_names=[("PhotoFlash", "view")],
        entity_type_names=[],
        domain="hr",
    )
    redundancy = [f for f in report.findings if f.kind == "redundancy"]
    assert redundancy
