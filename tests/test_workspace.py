"""Tests for the Workspace orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cedar_intent import (
    ActionScope,
    DraftPolicy,
    ExistingPolicy,
    OfflineGenerator,
    PolicyIntent,
    PrincipalScope,
    ResourceScope,
    Workspace,
    WorkspaceError,
)

PHOTOFLASH_SCHEMA = {
    "PhotoFlash": {
        "entityTypes": {"User": {}, "Photo": {}, "Album": {}},
        "actions": {
            "viewPhoto": {
                "appliesTo": {
                    "principalTypes": ["User"],
                    "resourceTypes": ["Photo"],
                }
            },
            "listAlbums": {
                "appliesTo": {
                    "principalTypes": ["User"],
                    "resourceTypes": ["Album"],
                }
            },
        },
    }
}


def make_workspace_with_domain(tmp_path: Path) -> Workspace:
    root = tmp_path
    domain = root / "hr"
    (domain / "requirements").mkdir(parents=True)
    (domain / "policies").mkdir(parents=True)
    (domain / "schema.json").write_text(json.dumps(PHOTOFLASH_SCHEMA), encoding="utf-8")
    return Workspace.open(root)


def test_workspace_open_always_uses_sqlite(tmp_path: Path) -> None:
    workspace = Workspace.open(tmp_path)
    try:
        assert workspace.repository.__class__.__name__ == "SqliteRepository"
    finally:
        workspace.close()


def test_workspace_open_missing_root_raises(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError):
        Workspace.open(tmp_path / "missing")


def test_workspace_create_initialises_storage(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)
    try:
        assert (tmp_path / ".cedar-intent" / "store.db").exists()
    finally:
        workspace.close()


def test_init_domain_creates_layout(tmp_path: Path) -> None:
    workspace = Workspace.in_memory(tmp_path)
    try:
        schema_path = workspace.init_domain("hr")
        assert schema_path.exists()
        assert workspace.requirements_directory("hr").exists()
        assert workspace.policies_directory("hr").exists()
    finally:
        workspace.close()


def test_init_domain_does_not_overwrite_existing_schema(tmp_path: Path) -> None:
    workspace = Workspace.in_memory(tmp_path)
    try:
        workspace.init_domain("hr")
        custom = {"Custom": {"entityTypes": {"User": {}}, "actions": {"view": {}}}}
        (workspace.schema_path("hr")).write_text(json.dumps(custom), encoding="utf-8")
        workspace.init_domain("hr")
        assert json.loads(workspace.schema_path("hr").read_text()) == custom
    finally:
        workspace.close()


def test_workspace_round_trips_requirements(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        path = workspace.requirements_directory("hr") / "HR-042.md"
        path.write_text(
            "---\nid: HR-042\ndomain: hr\n---\n\nOnly owners can view private photos.\n",
            encoding="utf-8",
        )
        requirements = workspace.add_requirement_directory("hr")
        assert [req.id for req in requirements] == ["HR-042"]
        assert workspace.get_requirement("HR-042").text.startswith("Only")
        assert {r.id for r in workspace.list_requirements(domain="hr")} == {"HR-042"}
    finally:
        workspace.close()


def test_workspace_add_requirement_file_infers_domain(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        path = workspace.requirements_directory("hr") / "HR-007.md"
        path.write_text(
            "---\nid: HR-007\n---\n\nOnly admins can read records.\n", encoding="utf-8"
        )
        requirement = workspace.add_requirement_file(path)
        assert requirement.domain == "hr"
    finally:
        workspace.close()


def test_workspace_remove_requirement(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        path = workspace.requirements_directory("hr") / "HR-042.md"
        path.write_text(
            "---\nid: HR-042\ndomain: hr\n---\n\nBody.\n", encoding="utf-8"
        )
        workspace.add_requirement_file(path)
        workspace.remove_requirement("HR-042")
        from cedar_intent import StorageError

        with pytest.raises(StorageError):
            workspace.get_requirement("HR-042")
    finally:
        workspace.close()


def test_workspace_imports_existing_policies(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        policy_path = workspace.policies_directory("hr") / "p1.cedar"
        policy_path.write_text(
            'permit (principal == PhotoFlash::User::"alice", '
            'action == PhotoFlash::Action::"viewPhoto", '
            'resource == PhotoFlash::Photo::"p1");',
            encoding="utf-8",
        )
        policies = workspace.import_existing_policies("hr")
        assert [policy.id for policy in policies] == ["existing-p1"]
        assert workspace.list_existing_policies("hr")[0].cedar.startswith("permit")
    finally:
        workspace.close()


def test_workspace_create_draft_uses_scopes(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        path = workspace.requirements_directory("hr") / "HR-042.md"
        path.write_text(
            "---\nid: HR-042\ndomain: hr\n---\n\nBody.\n", encoding="utf-8"
        )
        workspace.add_requirement_file(path)
        draft = workspace.create_draft(
            "HR-042",
            principal=PrincipalScope(kind="is_type", type_name="User"),
            action=ActionScope(kind="named", name="viewPhoto"),
            resource=ResourceScope(kind="is_type", type_name="Photo"),
        )
        assert draft.principal.type_name == "User"
        assert draft.action.name == "viewPhoto"
    finally:
        workspace.close()


def test_workspace_generate_draft_persists(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        path = workspace.requirements_directory("hr") / "HR-042.md"
        path.write_text(
            "---\nid: HR-042\ndomain: hr\n---\n\nOnly admins can view photos.\n",
            encoding="utf-8",
        )
        workspace.add_requirement_file(path)
        schema = workspace.load_schema("hr")
        draft = workspace.create_draft(
            "HR-042",
            principal=PrincipalScope(kind="is_type", type_name="User"),
            action=ActionScope(kind="named", name="viewPhoto"),
            resource=ResourceScope(kind="is_type", type_name="Photo"),
        )
        generator = OfflineGenerator()
        updated, result = workspace.generate_draft(draft, schema, generator)
        assert updated.cedar
        assert result.model == generator.model
        drafts = list(workspace.repository.list_drafts(policy_id=updated.id))
        assert drafts
        assert drafts[-1].cedar == updated.cedar
    finally:
        workspace.close()


def test_workspace_generate_draft_uses_existing(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        path = workspace.requirements_directory("hr") / "HR-042.md"
        path.write_text(
            "---\nid: HR-042\ndomain: hr\n---\n\nOnly admins can view photos.\n",
            encoding="utf-8",
        )
        workspace.add_requirement_file(path)
        schema = workspace.load_schema("hr")
        existing = ExistingPolicy.from_requirement(
            workspace.get_requirement("HR-042"),
            cedar="permit (principal, action, resource);",
        )
        draft = workspace.create_draft(
            "HR-042",
            principal=PrincipalScope(kind="is_type", type_name="User"),
            action=ActionScope(kind="named", name="viewPhoto"),
            resource=ResourceScope(kind="is_type", type_name="Photo"),
        )
        generator = OfflineGenerator()
        updated, _ = workspace.generate_draft(draft, schema, generator, existing=[existing])
        assert updated.cedar
    finally:
        workspace.close()


def test_workspace_apply_validates_and_persists(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        path = workspace.requirements_directory("hr") / "HR-042.md"
        path.write_text(
            "---\nid: HR-042\ndomain: hr\n---\n\nOnly admins can view photos.\n",
            encoding="utf-8",
        )
        workspace.add_requirement_file(path)
        schema = workspace.load_schema("hr")
        draft = DraftPolicy(
            id="hr-hr-042",
            requirement=workspace.get_requirement("HR-042"),
            cedar=(
                'permit (principal is PhotoFlash::User, '
                'action == PhotoFlash::Action::"viewPhoto", '
                'resource is PhotoFlash::Photo);'
            ),
            intent=PolicyIntent(
                id="hr-hr-042",
                requirement_id="HR-042",
                effect="permit",
                principal=PrincipalScope(kind="is_type", type_name="User"),
                action=ActionScope(kind="named", name="viewPhoto"),
                resource=ResourceScope(kind="is_type", type_name="Photo"),
            ),
        )
        compiled = workspace.apply(draft, schema)
        assert compiled.cedar.startswith("permit")
        report = workspace.repository.latest_report("hr-hr-042", "validation")
        assert report.passed
    finally:
        workspace.close()


def test_workspace_apply_with_scenarios(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        path = workspace.requirements_directory("hr") / "HR-042.md"
        path.write_text(
            "---\nid: HR-042\ndomain: hr\n---\n\nOnly admins can view photos.\n",
            encoding="utf-8",
        )
        workspace.add_requirement_file(path)
        workspace.scenarios_path("hr").write_text(
            json.dumps(
                [
                    {
                        "name": "alice-can-view",
                        "principal": 'PhotoFlash::User::"alice"',
                        "action": 'PhotoFlash::Action::"viewPhoto"',
                        "resource": 'PhotoFlash::Photo::"p1"',
                        "context": {},
                        "expected": "Allow",
                    }
                ]
            ),
            encoding="utf-8",
        )
        schema = workspace.load_schema("hr")
        cedar = (
            'permit (principal == PhotoFlash::User::"alice", '
            'action == PhotoFlash::Action::"viewPhoto", '
            'resource == PhotoFlash::Photo::"p1");'
        )
        draft = DraftPolicy(
            id="hr-hr-042",
            requirement=workspace.get_requirement("HR-042"),
            cedar=cedar,
            intent=PolicyIntent(
                id="hr-hr-042",
                requirement_id="HR-042",
                effect="permit",
                principal=PrincipalScope(kind="specific", type_name="User", entity_id="alice"),
                action=ActionScope(kind="named", name="viewPhoto"),
                resource=ResourceScope(kind="specific", type_name="Photo", entity_id="p1"),
            ),
        )
        scenarios = workspace.load_scenarios("hr")
        compiled = workspace.apply(draft, schema, scenarios=scenarios)
        assert compiled.cedar.startswith("permit")
        report = workspace.repository.latest_report("hr-hr-042", "test")
        assert report.passed
    finally:
        workspace.close()


def test_workspace_apply_with_failing_scenarios(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        path = workspace.requirements_directory("hr") / "HR-042.md"
        path.write_text(
            "---\nid: HR-042\ndomain: hr\n---\n\nBody.\n", encoding="utf-8"
        )
        workspace.add_requirement_file(path)
        workspace.scenarios_path("hr").write_text(
            json.dumps(
                [
                    {
                        "name": "deny-bob",
                        "principal": 'PhotoFlash::User::"bob"',
                        "action": 'PhotoFlash::Action::"viewPhoto"',
                        "resource": 'PhotoFlash::Photo::"p1"',
                        "context": {},
                        "expected": "Allow",
                    }
                ]
            ),
            encoding="utf-8",
        )
        schema = workspace.load_schema("hr")
        cedar = (
            'forbid (principal == PhotoFlash::User::"bob", '
            'action == PhotoFlash::Action::"viewPhoto", '
            'resource);'
        )
        draft = DraftPolicy(
            id="hr-hr-042",
            requirement=workspace.get_requirement("HR-042"),
            cedar=cedar,
            intent=PolicyIntent(
                id="hr-hr-042",
                requirement_id="HR-042",
                effect="forbid",
                principal=PrincipalScope(kind="specific", type_name="User", entity_id="bob"),
                action=ActionScope(kind="named", name="viewPhoto"),
                resource=ResourceScope(kind="any"),
            ),
        )
        scenarios = workspace.load_scenarios("hr")
        with pytest.raises(WorkspaceError):
            workspace.apply(draft, schema, scenarios=scenarios)
    finally:
        workspace.close()


def test_workspace_apply_without_cedar_raises(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        path = workspace.requirements_directory("hr") / "HR-042.md"
        path.write_text(
            "---\nid: HR-042\ndomain: hr\n---\n\nBody.\n", encoding="utf-8"
        )
        workspace.add_requirement_file(path)
        schema = workspace.load_schema("hr")
        draft = DraftPolicy.from_requirement(workspace.get_requirement("HR-042"))
        with pytest.raises(WorkspaceError):
            workspace.apply(draft, schema)
    finally:
        workspace.close()


def test_workspace_apply_with_unresolved_raises(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        path = workspace.requirements_directory("hr") / "HR-042.md"
        path.write_text(
            "---\nid: HR-042\ndomain: hr\n---\n\nBody.\n", encoding="utf-8"
        )
        workspace.add_requirement_file(path)
        schema = workspace.load_schema("hr")
        draft = DraftPolicy(
            id="hr-hr-042",
            requirement=workspace.get_requirement("HR-042"),
            cedar="permit (principal, action, resource);",
            unresolved=("needs review",),
        )
        with pytest.raises(WorkspaceError):
            workspace.apply(draft, schema)
    finally:
        workspace.close()


def test_workspace_validate_policies(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        cedar = (
            'permit (principal == PhotoFlash::User::"alice", '
            'action == PhotoFlash::Action::"viewPhoto", '
            'resource == PhotoFlash::Photo::"p1");'
        )
        (workspace.policies_directory("hr") / "p1.cedar").write_text(cedar, encoding="utf-8")
        workspace.import_existing_policies("hr")
        schema = workspace.load_schema("hr")
        report = workspace.validate_policies("hr", schema)
        assert report.passed
    finally:
        workspace.close()


def test_workspace_validate_policies_empty_raises(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        schema = workspace.load_schema("hr")
        with pytest.raises(WorkspaceError):
            workspace.validate_policies("hr", schema)
    finally:
        workspace.close()


def test_workspace_test_domain(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        cedar = (
            'permit (principal == PhotoFlash::User::"alice", '
            'action == PhotoFlash::Action::"viewPhoto", '
            'resource == PhotoFlash::Photo::"p1");'
        )
        (workspace.policies_directory("hr") / "p1.cedar").write_text(cedar, encoding="utf-8")
        workspace.import_existing_policies("hr")
        workspace.scenarios_path("hr").write_text(
            json.dumps(
                [
                    {
                        "name": "alice-can-view",
                        "principal": 'PhotoFlash::User::"alice"',
                        "action": 'PhotoFlash::Action::"viewPhoto"',
                        "resource": 'PhotoFlash::Photo::"p1"',
                        "context": {},
                        "expected": "Allow",
                    }
                ]
            ),
            encoding="utf-8",
        )
        schema = workspace.load_schema("hr")
        report = workspace.test_domain("hr", schema)
        assert report.passed
    finally:
        workspace.close()


def test_workspace_test_domain_missing_inputs(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        schema = workspace.load_schema("hr")
        with pytest.raises(WorkspaceError):
            workspace.test_domain("hr", schema)
    finally:
        workspace.close()


def test_workspace_export_domain(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        cedar = (
            'permit (principal == PhotoFlash::User::"alice", '
            'action == PhotoFlash::Action::"viewPhoto", '
            'resource == PhotoFlash::Photo::"p1");'
        )
        (workspace.policies_directory("hr") / "p1.cedar").write_text(cedar, encoding="utf-8")
        workspace.import_existing_policies("hr")
        schema = workspace.load_schema("hr")
        workspace.validate_policies("hr", schema)
        output = workspace.export_domain("hr", tmp_path / "dist" / "hr.cedar")
        bundle = output.read_text()
        assert "permit" in bundle
    finally:
        workspace.close()


def test_workspace_export_domain_no_policies_raises(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        with pytest.raises(WorkspaceError):
            workspace.export_domain("hr", tmp_path / "out.cedar")
    finally:
        workspace.close()


def test_workspace_scenarios_helper_handles_missing_file(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        scenarios = workspace.load_scenarios("hr")
        assert scenarios == []
    finally:
        workspace.close()


def test_workspace_scenarios_helper_rejects_bad_payload(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        workspace.scenarios_path("hr").write_text("{}", encoding="utf-8")
        with pytest.raises(WorkspaceError):
            workspace.load_scenarios("hr")
    finally:
        workspace.close()


def test_workspace_upsert_compiled_with_unknown_intent(tmp_path: Path) -> None:
    workspace = make_workspace_with_domain(tmp_path)
    try:
        path = workspace.requirements_directory("hr") / "HR-042.md"
        path.write_text(
            "---\nid: HR-042\ndomain: hr\n---\n\nBody.\n", encoding="utf-8"
        )
        workspace.add_requirement_file(path)
        existing = ExistingPolicy.from_requirement(
            workspace.get_requirement("HR-042"),
            cedar="permit (principal, action, resource);",
        )
        workspace.upsert_compiled(existing)
        stored = workspace.repository.get_policy(existing.id)
        assert stored.intent is None
    finally:
        workspace.close()


def test_workspace_in_memory_close_is_noop(tmp_path: Path) -> None:
    workspace = Workspace.in_memory(tmp_path)
    workspace.close()
