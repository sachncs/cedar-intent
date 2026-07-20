"""Tests for the verification module."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cedar_intent import (
    ActionScope,
    PolicyIntent,
    PrincipalScope,
    Requirement,
    ResourceScope,
    VerificationFinding,
    VerificationReport,
    extract_entity_types,
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
    cedar: str = "permit (principal, action, resource);",
) -> PolicyIntent:
    """Build a :class:`PolicyIntent` with optional scope overrides.

    The Cedar source is regenerated from the scopes so verification
    that analyzes Cedar sees the same shape callers provide.
    """
    if principal is not None or action is not None or resource is not None:
        # Build Cedar from the scopes so Cedar-based extraction matches
        # the typed intent exactly.
        principal_text = "principal"
        if principal is not None and principal.kind != "any":
            if principal.kind == "is_type":
                principal_text = f"principal is {principal.type_name}"
            elif principal.kind == "specific":
                principal_text = (
                    f'principal == {principal.type_name}::"{principal.entity_id}"'
                )
            elif principal.kind == "type":
                identifier = principal.entity_id or "*"
                principal_text = f'principal == {principal.type_name}::"{identifier}"'
            elif principal.kind == "in_group":
                principal_text = (
                    f'principal in {principal.group_type}::"{principal.group_id}"'
                )
        action_text = "action"
        if action is not None and action.kind != "any":
            if action.kind == "named":
                namespace_prefix = (
                    f"{action.namespace}::" if action.namespace else ""
                )
                action_text = (
                    f"action == {namespace_prefix}Action::"
                    f'"{action.name}"'
                )
            elif action.kind == "in_group":
                namespace_prefix = (
                    f"{action.namespace}::" if action.namespace else ""
                )
                action_text = (
                    f"action in {namespace_prefix}Action::"
                    f'"{action.group}"'
                )
        resource_text = "resource"
        if resource is not None and resource.kind != "any":
            if resource.kind == "is_type":
                resource_text = f"resource is {resource.type_name}"
            elif resource.kind == "specific":
                resource_text = (
                    f'resource == {resource.type_name}::"{resource.entity_id}"'
                )
            elif resource.kind == "in_parent":
                resource_text = (
                    f'resource is {resource.type_name} '
                    f'in {resource.parent_type}::"{resource.parent_id}"'
                )
        cedar = f"{effect} ({principal_text}, {action_text}, {resource_text});"
    return PolicyIntent(
        id=identifier,
        requirement_id=identifier,
        effect=effect,  # type: ignore[arg-type]
        principal=principal or PrincipalScope(),
        action=action or ActionScope(),
        resource=resource or ResourceScope(),
        notes={"cedar_text": cedar},
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
        action_names=[("Foo", "view")],
        entity_type_names=["Foo::User", "Foo::Photo"],
        actions_by_namespace={"Foo": {"view": (), "delete": (), "edit": ()}},
    )
    assert isinstance(report, VerificationReport)
    assert report.passed
    assert report.requirements_covered == ("HR-001",)
    assert report.requirements_uncovered == ()
    assert report.actions_covered == (("Foo", "view"),)
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
        action_names=[("Foo", "view")],
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
        requirement_ids=["HR-001", "HR-002"],
        action_names=[("Foo", "view"), ("Foo", "delete")],
        entity_type_names=["Foo::User"],
        actions_by_namespace={"Foo": {"view": (), "delete": ()}},
    )
    assert not report.passed
    assert report.requirements_uncovered == ("HR-002",)
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
        action_names=[("Foo", "view")],
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
        action=ActionScope(kind="named", name="view"),
        resource=ResourceScope(kind="any"),
    )
    permit = make_policy(
        "HR-001",
        effect="permit",
        principal=PrincipalScope(kind="any"),
        action=ActionScope(kind="named", name="view"),
        resource=ResourceScope(kind="any"),
    )
    report = verify_policies(
        domain="hr",
        policies=[permit, forbid],
        requirement_ids=["HR-001", "HR-002"],
        action_names=[("Foo", "view")],
        entity_type_names=[],
    )
    assert not report.passed
    shadow = next(finding for finding in report.findings if finding.kind == "shadowing")
    assert isinstance(shadow, VerificationFinding)
    assert shadow.policy_id == "HR-001"
    assert shadow.related_policy_id == "HR-002"


def test_verify_policies_does_not_shadow_any_with_specific_forbid() -> None:
    """A forbid on Alice must not shadow a permit on any principal."""
    forbid = make_policy(
        "HR-002",
        effect="forbid",
        principal=PrincipalScope(
            kind="specific", type_name="Foo::User", entity_id="alice"
        ),
        action=ActionScope(kind="named", name="view"),
        resource=ResourceScope(kind="is_type", type_name="Foo::Photo"),
    )
    permit = make_policy(
        "HR-001",
        effect="permit",
        principal=PrincipalScope(kind="any"),
        action=ActionScope(kind="named", name="view"),
        resource=ResourceScope(kind="is_type", type_name="Foo::Photo"),
    )
    report = verify_policies(
        domain="hr",
        policies=[permit, forbid],
        requirement_ids=["HR-001", "HR-002"],
        action_names=[("Foo", "view")],
        entity_type_names=[],
        actions_by_namespace={"Foo": {"view": ()}},
    )
    assert report.passed, (
        f"any-permit must not be shadowed by a specific forbid; "
        f"findings were {[f.message for f in report.findings]}"
    )


def test_verify_policies_detects_redundancy() -> None:
    permit_a = make_policy(
        "HR-001",
        action=ActionScope(kind="named", name="view"),
    )
    permit_b = make_policy(
        "HR-002",
        action=ActionScope(kind="named", name="view"),
    )
    report = verify_policies(
        domain="hr",
        policies=[permit_a, permit_b],
        requirement_ids=["HR-001", "HR-002"],
        action_names=[("Foo", "view")],
        entity_type_names=[],
    )
    redundancy = next(
        finding for finding in report.findings if finding.kind == "redundancy"
    )
    assert redundancy.policy_id in {"HR-001", "HR-002"}


def test_verify_policies_does_not_flag_different_conditions_as_redundant() -> None:
    """Two policies with the same scope but different conditions are not redundant."""
    permit_admin = make_policy(
        "HR-001",
        cedar=(
            'permit (principal, action == Action::"view", resource) '
            'when { principal.role == "admin" };'
        ),
    )
    permit_anyone = make_policy(
        "HR-002",
        cedar='permit (principal, action == Action::"view", resource);',
    )
    report = verify_policies(
        domain="hr",
        policies=[permit_admin, permit_anyone],
        requirement_ids=["HR-001", "HR-002"],
        action_names=[("Foo", "view")],
        entity_type_names=[],
    )
    assert not any(finding.kind == "redundancy" for finding in report.findings)


def test_verify_policies_distinguishes_distinct_scopes() -> None:
    permit_a = make_policy(
        "HR-001",
        principal=PrincipalScope(kind="any"),
        action=ActionScope(kind="named", name="view"),
        resource=ResourceScope(kind="is_type", type_name="Foo::Photo"),
    )
    permit_b = make_policy(
        "HR-002",
        principal=PrincipalScope(kind="is_type", type_name="Foo::User"),
        action=ActionScope(kind="named", name="view"),
        resource=ResourceScope(kind="is_type", type_name="Foo::Photo"),
    )
    report = verify_policies(
        domain="hr",
        policies=[permit_a, permit_b],
        requirement_ids=["HR-001", "HR-002"],
        action_names=[("Foo", "view")],
        entity_type_names=["Foo::User", "Foo::Photo"],
    )
    assert not any(finding.kind == "redundancy" for finding in report.findings)


def test_verify_policies_to_dict_serializes_findings() -> None:
    report = verify_policies(
        domain="hr",
        policies=[],
        requirement_ids=["HR-001"],
        action_names=[("Foo", "view")],
        entity_type_names=["Foo::User"],
    )
    payload = report.to_dict()
    assert payload["domain"] == "hr"
    assert "findings" in payload
    assert payload["requirements_uncovered"] == ["HR-001"]


def test_action_coverage_expands_groups() -> None:
    """An ``action in Action::"group"`` policy covers every member action."""
    policies = [
        make_policy(
            "HR-001",
            cedar='permit (principal, action in Action::"readers", resource);',
        )
    ]
    actions_by_namespace = {"Foo": {"readers": ("view", "delete", "edit")}}
    report = verify_policies(
        domain="hr",
        policies=policies,
        requirement_ids=["HR-001"],
        action_names=[
            ("Foo", "view"),
            ("Foo", "delete"),
            ("Foo", "edit"),
            ("Foo", "create"),
        ],
        entity_type_names=[],
        actions_by_namespace=actions_by_namespace,
    )
    assert set(report.actions_covered) == {
        ("Foo", "view"),
        ("Foo", "delete"),
        ("Foo", "edit"),
    }
    assert report.actions_uncovered == (("Foo", "create"),)


def test_action_coverage_handles_same_action_in_two_namespaces() -> None:
    """Two namespaces declaring 'view' are tracked independently."""
    policies = [
        make_policy(
            "HR-001",
            cedar='permit (principal, action == Hr::"view", resource);',
        )
    ]
    report = verify_policies(
        domain="hr",
        policies=policies,
        requirement_ids=["HR-001"],
        action_names=[("Hr", "view"), ("Finance", "view")],
        entity_type_names=[],
    )
    assert ("Hr", "view") in report.actions_covered
    assert ("Finance", "view") in report.actions_uncovered


def test_extract_entity_types_collects_references() -> None:
    policies = [
        make_policy(
            "HR-001",
            principal=PrincipalScope(
                kind="in_group", group_type="Foo::Group", group_id="admins"
            ),
            action=ActionScope(kind="named", name="view"),
            resource=ResourceScope(
                kind="in_parent",
                type_name="Foo::Photo",
                parent_type="Foo::Album",
                parent_id="a1",
            ),
        )
    ]
    types = extract_entity_types(policies)
    assert {"Foo::Group", "Foo::Photo", "Foo::Album"}.issubset(types)


def test_scope_signature_distinguishes_principal_kinds() -> None:
    any_scope = PrincipalScope(kind="any")
    type_scope = PrincipalScope(kind="is_type", type_name="User")
    assert any_scope.kind != type_scope.kind


def test_verify_policies_records_finding_severity_warning() -> None:
    forbid = make_policy(
        "HR-002",
        effect="forbid",
        principal=PrincipalScope(kind="any"),
        action=ActionScope(kind="named", name="view"),
        resource=ResourceScope(kind="any"),
    )
    permit = make_policy(
        "HR-001",
        principal=PrincipalScope(kind="any"),
        action=ActionScope(kind="named", name="view"),
        resource=ResourceScope(kind="any"),
    )
    report = verify_policies(
        domain="hr",
        policies=[permit, forbid],
        requirement_ids=["HR-001", "HR-002"],
        action_names=[("Foo", "view")],
        entity_type_names=[],
    )
    assert report.findings
    for finding in report.findings:
        assert finding.severity in {"warning", "info"}
