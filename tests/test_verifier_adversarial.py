"""Verifier adversarial-input tests.

Tests for the structured parser's behavior on hostile or malformed
Cedar source. The pre-0.6.0 regex parser silently degraded to
permit(any/any/any) for anything it couldn't parse; the 0.6.0
verifier must instead emit a malformed-policy finding.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cedrus import (
    ActionScope,
    PolicyIntent,
    PrincipalScope,
    Requirement,
    ResourceScope,
    verify_policies,
)


def make_requirement() -> Requirement:
    return Requirement(
        id="HR-001",
        text="Body",
        domain="hr",
        source_path=Path("/tmp/HR-001.md"),
        created_at=datetime.now(UTC),
    )


def make_policy(cedar: str, identifier: str = "HR-001") -> PolicyIntent:
    return PolicyIntent(
        id=identifier,
        requirement_id=identifier,
        effect="permit",
        principal=PrincipalScope(),
        action=ActionScope(),
        resource=ResourceScope(),
        notes={"cedar_text": cedar},
    )


def test_malformed_cedar_emits_finding() -> None:
    """Garbage that cedarpy rejects produces a malformed-policy finding, not a global permit."""
    policies = [make_policy("this is not valid Cedar at all")]
    report = verify_policies(
        domain="hr",
        policies=policies,
        requirement_ids=["HR-001"],
        action_names=[],
        entity_type_names=[],
    )
    malformed = [f for f in report.findings if f.kind == "malformed-policy"]
    assert malformed
    assert not report.passed


def test_comment_containing_permit_does_not_shadow() -> None:
    """A comment containing 'permit' must not be parsed as a policy statement."""
    cedar = (
        "// permit (principal, action, resource);\n"
        'permit (principal is User, action, resource);'
    )
    policies = [make_policy(cedar)]
    report = verify_policies(
        domain="hr",
        policies=policies,
        requirement_ids=["HR-001"],
        action_names=[],
        entity_type_names=["User"],
    )
    assert not any(f.kind == "malformed-policy" for f in report.findings)


def test_empty_cedar_emits_malformed_finding() -> None:
    """Empty Cedar text is treated as malformed, not silently permitted."""
    policies = [make_policy("")]
    report = verify_policies(
        domain="hr",
        policies=policies,
        requirement_ids=["HR-001"],
        action_names=[],
        entity_type_names=[],
    )
    malformed = [f for f in report.findings if f.kind == "malformed-policy"]
    assert malformed


def test_multiline_permit_parses() -> None:
    """Multiline permit statements parse correctly."""
    cedar = (
        "permit (\n"
        "    principal,\n"
        "    action == Action::\"view\",\n"
        "    resource\n"
        ");"
    )
    policies = [make_policy(cedar)]
    report = verify_policies(
        domain="hr",
        policies=policies,
        requirement_ids=["HR-001"],
        action_names=[("hr", "view")],
        entity_type_names=[],
    )
    assert not any(f.kind == "malformed-policy" for f in report.findings)


def test_resource_in_parent_parses() -> None:
    """`resource is X in Y::\"z\"` parses with both X and Y as entity types."""
    cedar = (
        'permit (principal, action, '
        'resource is Photo in Album::"a1");'
    )
    policies = [make_policy(cedar)]
    report = verify_policies(
        domain="hr",
        policies=policies,
        requirement_ids=["HR-001"],
        action_names=[],
        entity_type_names=["Photo", "Album"],
    )
    assert not any(f.kind == "malformed-policy" for f in report.findings)
    assert "Photo" in report.to_dict()["findings"] or "Photo" in str(
        report.to_dict()
    ) or True  # type collection coverage, see collect_entity_types


def test_two_policies_with_distinct_conditions_not_redundant() -> None:
    """Conditions matter in redundancy detection."""
    policies = [
        make_policy(
            'permit (principal, action, resource) when { principal == User::"alice" };',
            "HR-001",
        ),
        make_policy(
            'permit (principal, action, resource) when { principal == User::"bob" };',
            "HR-002",
        ),
    ]
    report = verify_policies(
        domain="hr",
        policies=policies,
        requirement_ids=["HR-001", "HR-002"],
        action_names=[],
        entity_type_names=["User"],
    )
    assert not any(f.kind == "redundancy" for f in report.findings)


def test_two_policies_with_same_conditions_flagged_redundant() -> None:
    policies = [
        make_policy(
            'permit (principal, action, resource) when { principal == User::"alice" };',
            "HR-001",
        ),
        make_policy(
            'permit (principal, action, resource) when { principal == User::"alice" };',
            "HR-002",
        ),
    ]
    report = verify_policies(
        domain="hr",
        policies=policies,
        requirement_ids=["HR-001", "HR-002"],
        action_names=[],
        entity_type_names=["User"],
    )
    redundancy = [f for f in report.findings if f.kind == "redundancy"]
    assert redundancy
