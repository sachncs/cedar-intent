"""Tests for the verification module."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cedar_intent import (
    ActionScope,
    CompiledPolicy,
    PolicyIntent,
    PrincipalScope,
    Requirement,
    ResourceScope,
    VerificationFinding,
    VerificationReport,
    verify_policies,
)


def make_requirement(identifier: str) -> Requirement:
    return Requirement(
        id=identifier,
        text=f"Body for {identifier}",
        domain="hr",
        source_path=Path(f"/tmp/{identifier}.md"),
        created_at=datetime.now(UTC),
    )


def make_policy(
    identifier: str,
    effect: str = "permit",
    principal: PrincipalScope | None = None,
    action: ActionScope | None = None,
    resource: ResourceScope | None = None,
) -> CompiledPolicy:
    requirement = make_requirement(identifier)
    intent = PolicyIntent(
        id=identifier,
        requirement_id=identifier,
        effect=effect,  # type: ignore[arg-type]
        principal=principal or PrincipalScope(kind="any"),
        action=action or ActionScope(kind="any"),
        resource=resource or ResourceScope(kind="any"),
    )
    cedar = (
        f'{effect} (principal is Foo::User, '
        'action == Foo::Action::"view", '
        "resource is Foo::Photo);"
    )
    return CompiledPolicy(
        id=identifier, requirement=requirement, cedar=cedar, intent=intent
    )


def test_verify_policies_passes_when_clean() -> None:
    policies = [
        make_policy(
            "HR-001",
            principal=PrincipalScope(kind="is_type", type_name="Foo::User"),
            action=ActionScope(kind="named", name="view"),
            resource=ResourceScope(kind="is_type", type_name="Foo::Photo"),
        )
    ]
    report = verify_policies(
        domain="hr",
        policies=policies,
        requirement_ids=["HR-001"],
        action_names=["view"],
        entity_type_names=["Foo::User", "Foo::Photo"],
    )
    assert isinstance(report, VerificationReport)
    assert report.passed
    assert report.requirements_covered == ("HR-001",)
    assert report.requirements_uncovered == ()
    assert report.actions_covered == ("view",)
    assert report.actions_uncovered == ()


def test_verify_policies_reports_missing_requirement() -> None:
    policies = [
        make_policy(
            "HR-001",
            action=ActionScope(kind="named", name="view"),
        )
    ]
    report = verify_policies(
        domain="hr",
        policies=policies,
        requirement_ids=["HR-001", "HR-002"],
        action_names=["view"],
        entity_type_names=["Foo::User"],
    )
    assert not report.passed
    assert report.requirements_uncovered == ("HR-002",)
    assert any(finding.kind == "uncovered-requirement" for finding in report.findings)


def test_verify_policies_reports_missing_action() -> None:
    policies = [
        make_policy(
            "HR-001",
            action=ActionScope(kind="named", name="view"),
        )
    ]
    report = verify_policies(
        domain="hr",
        policies=policies,
        requirement_ids=["HR-001"],
        action_names=["view", "delete"],
        entity_type_names=["Foo::User"],
    )
    assert not report.passed
    assert report.actions_uncovered == ("delete",)
    assert any(finding.kind == "uncovered-action" for finding in report.findings)


def test_verify_policies_reports_missing_entity_type() -> None:
    policies = [
        make_policy(
            "HR-001",
            principal=PrincipalScope(kind="is_type", type_name="Foo::User"),
            action=ActionScope(kind="named", name="view"),
            resource=ResourceScope(kind="is_type", type_name="Foo::Photo"),
        )
    ]
    report = verify_policies(
        domain="hr",
        policies=policies,
        requirement_ids=["HR-001"],
        action_names=["view"],
        entity_type_names={"Foo::User", "Foo::Photo", "Foo::Album"},
    )
    assert not report.passed
    kinds = {finding.kind for finding in report.findings}
    assert "uncovered-entity-type" in kinds


def test_verify_policies_detects_shadowing() -> None:
    forbid = make_policy(
        "HR-002",
        effect="forbid",
        principal=PrincipalScope(kind="any"),
        action=ActionScope(kind="any"),
        resource=ResourceScope(kind="any"),
    )
    permit = make_policy(
        "HR-001",
        effect="permit",
        principal=PrincipalScope(kind="any"),
        action=ActionScope(kind="any"),
        resource=ResourceScope(kind="any"),
    )
    report = verify_policies(
        domain="hr",
        policies=[permit, forbid],
        requirement_ids=["HR-001", "HR-002"],
        action_names=["view"],
        entity_type_names=["Foo::User"],
    )
    assert not report.passed
    shadow = next(finding for finding in report.findings if finding.kind == "shadowing")
    assert isinstance(shadow, VerificationFinding)
    assert shadow.policy_id == "HR-001"
    assert shadow.related_policy_id == "HR-002"


def test_verify_policies_detects_redundancy() -> None:
    permit_a = make_policy(
        "HR-001",
        effect="permit",
        principal=PrincipalScope(kind="any"),
        action=ActionScope(kind="any"),
        resource=ResourceScope(kind="any"),
    )
    permit_b = make_policy(
        "HR-002",
        effect="permit",
        principal=PrincipalScope(kind="any"),
        action=ActionScope(kind="any"),
        resource=ResourceScope(kind="any"),
    )
    report = verify_policies(
        domain="hr",
        policies=[permit_a, permit_b],
        requirement_ids=["HR-001", "HR-002"],
        action_names=["view"],
        entity_type_names=["Foo::User"],
    )
    redundancy = next(
        finding for finding in report.findings if finding.kind == "redundancy"
    )
    assert redundancy.policy_id in {"HR-001", "HR-002"}


def test_verify_policies_distinguishes_distinct_scopes() -> None:
    permit_any = make_policy(
        "HR-001",
        effect="permit",
        principal=PrincipalScope(kind="any"),
        action=ActionScope(kind="any"),
        resource=ResourceScope(kind="any"),
    )
    permit_other = make_policy(
        "HR-002",
        effect="permit",
        principal=PrincipalScope(kind="is_type", type_name="User"),
        action=ActionScope(kind="named", name="view"),
        resource=ResourceScope(kind="is_type", type_name="Photo"),
    )
    report = verify_policies(
        domain="hr",
        policies=[permit_any, permit_other],
        requirement_ids=["HR-001", "HR-002"],
        action_names=["view"],
        entity_type_names=["Foo::User"],
    )
    assert not any(finding.kind == "redundancy" for finding in report.findings)


def test_verify_policies_to_dict_serializes_findings() -> None:
    report = verify_policies(
        domain="hr",
        policies=[],
        requirement_ids=["HR-001"],
        action_names=["view"],
        entity_type_names=["Foo::User"],
    )
    payload = report.to_dict()
    assert payload["domain"] == "hr"
    assert "findings" in payload
    assert payload["requirements_uncovered"] == ["HR-001"]


def test_scope_signature_distinguishes_principal_kinds() -> None:
    any_scope = PrincipalScope(kind="any")
    type_scope = PrincipalScope(kind="is_type", type_name="User")
    assert any_scope.kind != type_scope.kind
    assert PrincipalScope(kind="any") != PrincipalScope(kind="is_type", type_name="User")


def test_verify_policies_records_finding_severity_warning() -> None:
    forbid = make_policy(
        "HR-002",
        effect="forbid",
        principal=PrincipalScope(kind="any"),
        action=ActionScope(kind="any"),
        resource=ResourceScope(kind="any"),
    )
    permit = make_policy(
        "HR-001",
        effect="permit",
        principal=PrincipalScope(kind="any"),
        action=ActionScope(kind="any"),
        resource=ResourceScope(kind="any"),
    )
    report = verify_policies(
        domain="hr",
        policies=[permit, forbid],
        requirement_ids=["HR-001", "HR-002"],
        action_names=["view"],
        entity_type_names=["Foo::User"],
    )
    assert report.findings
    for finding in report.findings:
        assert finding.severity in {"warning", "info"}


def test_extract_entity_types_collects_references() -> None:
    from cedar_intent.verification import extract_entity_types

    policy = make_policy(
        "HR-001",
        principal=PrincipalScope(kind="in_group", group_type="Foo::Group", group_id="admins"),
        action=ActionScope(kind="any"),
        resource=ResourceScope(
            kind="in_parent",
            type_name="Foo::Photo",
            parent_type="Foo::Album",
            parent_id="a1",
        ),
    )
    types = extract_entity_types([policy])
    assert {"Foo::Group", "Foo::Photo", "Foo::Album"}.issubset(types)
