"""Tests for workspace verify and deploy integration."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cedar_intent import (
    ActionScope,
    CompiledPolicy,
    PolicyIntent,
    PrincipalScope,
    Requirement,
    ResourceScope,
    VerificationReport,
    Workspace,
)

PHOTOFLASH_SCHEMA = {
    "PhotoFlash": {
        "entityTypes": {"User": {}, "Photo": {}},
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


def make_workspace_with_domain(tmp_path: Path) -> Workspace:
    domain = tmp_path / "hr"
    (domain / "requirements").mkdir(parents=True)
    (domain / "policies").mkdir(parents=True)
    (domain / "schema.json").write_text(json.dumps(PHOTOFLASH_SCHEMA), encoding="utf-8")
    return Workspace.open(tmp_path)


def make_requirement(identifier: str, tmp_path: Path) -> Requirement:
    return Requirement(
        id=identifier,
        text="Body",
        domain="hr",
        source_path=tmp_path / f"{identifier}.md",
        created_at=datetime.now(UTC),
    )


def test_workspace_verify_domain_passes(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        requirement = make_requirement("HR-001", tmp_path)
        workspace.repository.add_requirement(requirement)
        intent = PolicyIntent(
            id="hr-hr-001",
            requirement_id="HR-001",
            effect="permit",
            principal=PrincipalScope(kind="is_type", type_name="PhotoFlash::User"),
            action=ActionScope(kind="named", name="viewPhoto", namespace="PhotoFlash"),
            resource=ResourceScope(kind="is_type", type_name="PhotoFlash::Photo"),
        )
        cedar = (
            "permit (principal is PhotoFlash::User, "
            'action == PhotoFlash::Action::"viewPhoto", '
            "resource is PhotoFlash::Photo);"
        )
        compiled = CompiledPolicy(
            id="hr-hr-001", requirement=requirement, cedar=cedar, intent=intent
        )
        workspace.upsert_compiled(compiled)
        schema = workspace.load_schema("hr")
        report = workspace.verify_domain("hr", schema)
        assert isinstance(report, VerificationReport)
        assert report.requirements_uncovered == ()
    finally:
        workspace.close()


def test_workspace_verify_domain_reports_missing(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        schema = workspace.load_schema("hr")
        report = workspace.verify_domain("hr", schema)
        assert not report.passed
        assert report.requirements_uncovered == ()
        assert report.actions_uncovered == (("PhotoFlash", "viewPhoto"),)
    finally:
        workspace.close()


def test_workspace_build_bundle_writes_to_directory(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        requirement = make_requirement("HR-001", tmp_path)
        workspace.repository.add_requirement(requirement)
        intent = PolicyIntent(
            id="hr-hr-001",
            requirement_id="HR-001",
            effect="permit",
            principal=PrincipalScope(kind="any"),
            action=ActionScope(kind="any"),
            resource=ResourceScope(kind="any"),
        )
        cedar = (
            "permit (principal is PhotoFlash::User, "
            'action == PhotoFlash::Action::"viewPhoto", '
            "resource is PhotoFlash::Photo);"
        )
        workspace.upsert_compiled(
            CompiledPolicy(
                id="hr-hr-001", requirement=requirement, cedar=cedar, intent=intent
            )
        )
        manifest = workspace.build_bundle("hr", metadata={"channel": "prod"})
        output = tmp_path / "out" / "hr"
        workspace.write_bundle(manifest, output)
        assert (output / "bundle.cedar").exists()
        assert (output / "manifest.json").exists()
    finally:
        workspace.close()


def test_workspace_deploy_local_persists_record(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        requirement = make_requirement("HR-001", tmp_path)
        workspace.repository.add_requirement(requirement)
        intent = PolicyIntent(
            id="hr-hr-001",
            requirement_id="HR-001",
            effect="permit",
            principal=PrincipalScope(kind="any"),
            action=ActionScope(kind="any"),
            resource=ResourceScope(kind="any"),
        )
        cedar = (
            "permit (principal is PhotoFlash::User, "
            'action == PhotoFlash::Action::"viewPhoto", '
            "resource is PhotoFlash::Photo);"
        )
        workspace.upsert_compiled(
            CompiledPolicy(
                id="hr-hr-001", requirement=requirement, cedar=cedar, intent=intent
            )
        )
        target = tmp_path / "deploy" / "hr"
        record = workspace.deploy("hr", str(target))
        assert record.target_kind == "local"
        assert (target / "bundle.cedar").exists()
        history = workspace.list_deployments("hr")
        assert history and history[0].id == record.id
    finally:
        workspace.close()


def test_workspace_deploy_empty_domain_raises(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        from cedar_intent import DeploymentError

        with pytest.raises(DeploymentError):
            workspace.deploy("hr", str(tmp_path / "out"))
    finally:
        workspace.close()


def test_workspace_list_deployments_filtered(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        requirement = make_requirement("HR-001", tmp_path)
        workspace.repository.add_requirement(requirement)
        intent = PolicyIntent(
            id="hr-hr-001",
            requirement_id="HR-001",
            effect="permit",
            principal=PrincipalScope(kind="any"),
            action=ActionScope(kind="any"),
            resource=ResourceScope(kind="any"),
        )
        cedar = (
            "permit (principal is PhotoFlash::User, "
            'action == PhotoFlash::Action::"viewPhoto", '
            "resource is PhotoFlash::Photo);"
        )
        workspace.upsert_compiled(
            CompiledPolicy(
                id="hr-hr-001", requirement=requirement, cedar=cedar, intent=intent
            )
        )
        workspace.deploy("hr", str(tmp_path / "out1"))
        assert workspace.list_deployments() and not workspace.list_deployments("finance")
    finally:
        workspace.close()
