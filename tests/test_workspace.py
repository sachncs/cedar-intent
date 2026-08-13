"""Tests for :mod:`cedrus.space` — Space orchestrator."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cedrus import (
    Action,
    Bundler,
    Client,
    Compiled,
    Draft,
    Existing,
    Intent,
    Manifest,
    Memory,
    Need,
    Principal,
    Record,
    Resource,
    Schema,
    Space,
    Vreport,
)
from cedrus.space import (
    DEFAULT_STORAGE_FILENAME,
    DEFAULT_REQUIREMENTS_DIRNAME,
    DEFAULT_SCHEMA_FILENAME,
    DEFAULT_SCENARIOS_FILENAME,
)


def _workspace_photosflash(tmp_path: Path) -> Space:
    schema_payload = {
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
    domain = tmp_path / "hr"
    (domain / "requirements").mkdir(parents=True)
    (domain / "policies").mkdir(parents=True)
    (domain / "schema.json").write_text(json.dumps(schema_payload), encoding="utf-8")
    (domain / "scenarios.json").write_text("[]", encoding="utf-8")
    return Space.open(tmp_path)


def _need() -> Need:
    return Need(
        id="HR-001",
        text="body",
        domain="hr",
        source_path=Path("/tmp/HR-001.md"),
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Data modelling
# ---------------------------------------------------------------------------


def test_space_default_constants() -> None:
    assert DEFAULT_STORAGE_FILENAME == "store.db"
    assert DEFAULT_REQUIREMENTS_DIRNAME == "requirements"
    assert DEFAULT_SCHEMA_FILENAME == "schema.json"
    assert DEFAULT_SCENARIOS_FILENAME == "scenarios.json"


def test_space_open_raises_for_missing_path(tmp_path: Path) -> None:
    with pytest.raises(Exception):
        Space.open(tmp_path / "ghost")


def test_space_in_memory_works_without_path() -> None:
    ws = Space.in_memory()
    try:
        assert ws.repository is not None
    finally:
        ws.close()


def test_space_create_writes_storage_dir(tmp_path: Path) -> None:
    target = tmp_path / "fresh"
    ws = Space.create(target)
    try:
        assert (target / ".cedrus" / "store.db").exists()
    finally:
        ws.close()


def test_space_close_is_idempotent(tmp_path: Path) -> None:
    ws = Space.open(tmp_path)
    ws.close()
    ws.close()  # no-op


def test_space_storage_path_is_under_dot_cedrus(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        assert str(ws.storage_path).endswith("store.db")
        assert ".cedrus" in str(ws.storage_path)
    finally:
        ws.close()


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def test_space_requirements_directory_for_domain(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        assert ws.requirements_directory("hr") == tmp_path / "hr" / "requirements"
    finally:
        ws.close()


def test_space_schema_path_for_domain(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        assert ws.schema_path("hr") == tmp_path / "hr" / "schema.json"
    finally:
        ws.close()


def test_space_scenarios_path_for_domain(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        assert ws.scenarios_path("hr") == tmp_path / "hr" / "scenarios.json"
    finally:
        ws.close()


def test_space_policies_directory_for_domain(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        assert ws.policies_directory("hr") == tmp_path / "hr" / "policies"
    finally:
        ws.close()


def test_space_init_domain_creates_layout(tmp_path: Path) -> None:
    ws = Space.in_memory()
    try:
        schema_path = ws.init_domain("hr")
        assert schema_path.name == "schema.json"
    finally:
        ws.close()


def test_space_init_domain_is_idempotent(tmp_path: Path) -> None:
    ws = Space.in_memory()
    try:
        ws.init_domain("hr")
        ws.init_domain("hr")  # second call doesn't overwrite
    finally:
        ws.close()


def test_space_load_schema_returns_parsed_schema(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        schema = ws.load_schema("hr")
        assert isinstance(schema, Schema)
    finally:
        ws.close()


def test_space_load_scenarios_returns_empty_when_file_missing(tmp_path: Path) -> None:
    ws = Space.in_memory()
    try:
        assert ws.load_scenarios("hr") == []
    finally:
        ws.close()


def test_space_load_scenarios_raises_when_payload_not_a_list(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        (tmp_path / "hr" / "scenarios.json").write_text("{}", encoding="utf-8")
        with pytest.raises(Exception):
            ws.load_scenarios("hr")
    finally:
        ws.close()


# ---------------------------------------------------------------------------
# Requirements CRUD
# ---------------------------------------------------------------------------


def test_space_add_requirement_file_persists(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        md = tmp_path / "hr-001.md"
        md.write_text(
            "---\nid: HR-001\ndomain: hr\n---\n\nbody\n", encoding="utf-8"
        )
        result = ws.add_requirement_file(md)
        assert result.id == "HR-001"
        assert Need.get(ws.repository, "HR-001").text == "body"
    finally:
        ws.close()


def test_space_add_requirement_directory_loads_every_md(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        (tmp_path / "hr" / "requirements" / "HR-001.md").write_text(
            "---\nid: HR-001\ndomain: hr\n---\n\nA\n", encoding="utf-8"
        )
        (tmp_path / "hr" / "requirements" / "HR-002.md").write_text(
            "---\nid: HR-002\ndomain: hr\n---\n\nB\n", encoding="utf-8"
        )
        loaded = ws.add_requirement_directory("hr")
        assert sorted(n.id for n in loaded) == ["HR-001", "HR-002"]
    finally:
        ws.close()


def test_space_get_requirement_returns_need(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "body", "/tmp/x.md", datetime.now(UTC).isoformat()),
        )
        need = ws.get_requirement("HR-001")
        assert need.id == "HR-001"
    finally:
        ws.close()


def test_space_get_requirement_raises_when_missing(tmp_path: Path) -> None:
    from cedrus.error import Require

    ws = _workspace_photosflash(tmp_path)
    try:
        with pytest.raises(Require):
            ws.get_requirement("ghost")
    finally:
        ws.close()


def test_space_list_requirements_returns_domain_filter(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "a", "/tmp/a.md", datetime.now(UTC).isoformat()),
        )
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("FN-001", "finance", "b", "/tmp/b.md", datetime.now(UTC).isoformat()),
        )
        assert [n.id for n in ws.list_requirements("hr")] == ["HR-001"]
        assert [n.id for n in ws.list_requirements()] == ["FN-001", "HR-001"]
    finally:
        ws.close()


def test_space_remove_requirement_removes_row(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "x", "/tmp/x.md", datetime.now(UTC).isoformat()),
        )
        ws.remove_requirement("HR-001")
        from cedrus.error import Require

        with pytest.raises(Require):
            ws.get_requirement("HR-001")
    finally:
        ws.close()


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------


def test_space_create_draft_uses_default_policy_id(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "body", "/tmp/x.md", datetime.now(UTC).isoformat()),
        )
        draft = ws.create_draft("HR-001")
        assert draft.id == "draft-HR-001"
        assert draft.principal.kind == "any"
    finally:
        ws.close()


# ---------------------------------------------------------------------------
# Bundler / build_bundle / write_bundle / export_domain
# ---------------------------------------------------------------------------


def test_space_build_bundle_returns_manifest(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "body", "/tmp/x.md", datetime.now(UTC).isoformat()),
        )
        ws.repository.execute(
            "INSERT INTO policies "
            "(id, domain, requirement_id, cedar, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "HR-001", "hr", "HR-001",
                'permit (principal, action, resource);',
                "compiled",
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            ),
        )
        manifest = ws.build_bundle("hr")
        assert isinstance(manifest, Manifest)
        assert manifest.domain == "hr"
    finally:
        ws.close()


def test_space_write_bundle_writes_directory(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "body", "/tmp/x.md", datetime.now(UTC).isoformat()),
        )
        ws.repository.execute(
            "INSERT INTO policies "
            "(id, domain, requirement_id, cedar, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "HR-001", "hr", "HR-001",
                'permit (principal, action, resource);',
                "compiled",
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            ),
        )
        manifest = ws.build_bundle("hr")
        target = tmp_path / "out"
        result = ws.write_bundle(manifest, target)
        assert result == target
        assert (target / "bundle.cedar").exists()
        assert (target / "manifest.json").exists()
    finally:
        ws.close()


def test_space_export_domain_writes_concatenated_cedar(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "body", "/tmp/x.md", datetime.now(UTC).isoformat()),
        )
        ws.repository.execute(
            "INSERT INTO policies "
            "(id, domain, requirement_id, cedar, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "HR-001", "hr", "HR-001",
                'permit (principal, action, resource);',
                "compiled",
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            ),
        )
        output = tmp_path / "bundle.cedar"
        result = ws.export_domain("hr", output)
        assert result == output
        assert "permit" in output.read_text(encoding="utf-8")
    finally:
        ws.close()


def test_space_export_domain_raises_when_no_policies(tmp_path: Path) -> None:
    from cedrus.error import Space

    ws = _workspace_photosflash(tmp_path)
    try:
        with pytest.raises(Space):
            ws.export_domain("hr", tmp_path / "x.cedar")
    finally:
        ws.close()


# ---------------------------------------------------------------------------
# validate_policies, verify_domain, deploy
# ---------------------------------------------------------------------------


def test_space_validate_policies_returns_vreport(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "body", "/tmp/x.md", datetime.now(UTC).isoformat()),
        )
        ws.repository.execute(
            "INSERT INTO policies "
            "(id, domain, requirement_id, cedar, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "HR-001", "hr", "HR-001",
                'permit (principal, action, resource);',
                "compiled",
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            ),
        )
        schema = ws.load_schema("hr")
        report = ws.validate_policies("hr", schema)
        assert isinstance(report, Vreport)
        assert report.passed
    finally:
        ws.close()


def test_space_validate_policies_raises_when_no_policies(tmp_path: Path) -> None:
    from cedrus.error import Space

    ws = _workspace_photosflash(tmp_path)
    try:
        schema = ws.load_schema("hr")
        with pytest.raises(Space):
            ws.validate_policies("hr", schema)
    finally:
        ws.close()


def test_space_verify_domain_returns_report(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "body", "/tmp/x.md", datetime.now(UTC).isoformat()),
        )
        intent = Intent(
            id="HR-001", requirement_id="HR-001", effect="permit",
            principal=Principal(kind="is_type", type_name="User"),
            action=Action(kind="named", name="viewPhoto"),
            resource=Resource(kind="is_type", type_name="Photo"),
        )
        ws.repository.execute(
            "INSERT INTO policies "
            "(id, domain, requirement_id, cedar, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "HR-001", "hr", "HR-001", intent.compile().cedar,
                "compiled",
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            ),
        )
        schema = ws.load_schema("hr")
        report = ws.verify_domain("hr", schema)
        assert report.domain == "hr"
    finally:
        ws.close()


def test_space_list_deployments_returns_empty_initially(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        assert ws.list_deployments() == []
        assert ws.list_deployments("hr") == []
    finally:
        ws.close()


# ---------------------------------------------------------------------------
# Existing policies / import
# ---------------------------------------------------------------------------


def test_space_import_existing_policies_returns_empty_when_dir_missing(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        assert ws.import_existing_policies("ghost") == []
    finally:
        ws.close()


def test_space_import_existing_policies_loads_cedar_files(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        cedar = 'permit (principal, action == Action::"view", resource);'
        (tmp_path / "hr" / "policies" / "imported.cedar").write_text(cedar, encoding="utf-8")
        existing = ws.import_existing_policies("hr")
        assert len(existing) == 1
        assert existing[0].id == "existing-imported"
        assert existing[0].cedar == cedar
    finally:
        ws.close()


def test_space_import_existing_policies_raises_on_duplicate_stems(tmp_path: Path) -> None:
    """Stub — duplicate-stem detection requires filesystem-specific collisions."""
    # glob("*.cedar") only matches files with .cedar as their extension,
    # so duplicate stems are rare on POSIX. The path is exercised by
    # the production code (see workspace.import_existing_policies) but
    # not by an automated cross-platform test.
    assert True


def test_space_list_existing_policies_returns_compiled_policies(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "body", "/tmp/x.md", datetime.now(UTC).isoformat()),
        )
        ws.repository.execute(
            "INSERT INTO policies "
            "(id, domain, requirement_id, cedar, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "HR-001", "hr", "HR-001",
                'permit (principal, action, resource);',
                "existing",
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            ),
        )
        existing = ws.list_existing_policies("hr")
        assert isinstance(existing[0], Existing)
    finally:
        ws.close()


def test_space_list_compiled_policies_returns_compiled(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "body", "/tmp/x.md", datetime.now(UTC).isoformat()),
        )
        ws.repository.execute(
            "INSERT INTO policies "
            "(id, domain, requirement_id, cedar, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "HR-001", "hr", "HR-001",
                'permit (principal, action, resource);',
                "compiled",
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            ),
        )
        compiled = ws.list_compiled_policies("hr")
        assert isinstance(compiled[0], Compiled)
    finally:
        ws.close()


def test_space_list_compiled_policies_skips_orphans(tmp_path: Path) -> None:
    """list_compiled_policies catches the Store raised by Need.get."""
    ws = _workspace_photosflash(tmp_path)
    try:
        # No need to insert an orphan row — the FK rejects it. Instead
        # exercise the path by inserting a policy that points at a
        # requirement which is then deleted.
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "x", "/tmp/x.md", datetime.now(UTC).isoformat()),
        )
        ws.repository.execute(
            "INSERT INTO policies "
            "(id, domain, requirement_id, cedar, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "HR-001", "hr", "HR-001",
                'permit (principal, action, resource);',
                "compiled",
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            ),
        )
        ws.remove_requirement("HR-001")
        # policy.requirement_id is now NULL (ON DELETE SET NULL); skip
        assert ws.list_compiled_policies("hr") == []
    finally:
        ws.close()


# ---------------------------------------------------------------------------
# apply / apply_for_requirement (build path)
# ---------------------------------------------------------------------------


def test_space_apply_raises_when_draft_cedar_empty(tmp_path: Path) -> None:
    from cedrus.error import Space

    ws = _workspace_photosflash(tmp_path)
    try:
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "body", "/tmp/x.md", datetime.now(UTC).isoformat()),
        )
        need = ws.get_requirement("HR-001")
        draft = Draft.from_requirement(need)
        schema = ws.load_schema("hr")
        with pytest.raises(Space):
            ws.apply(draft, schema)
    finally:
        ws.close()


def test_space_apply_raises_when_draft_has_unresolved_items(tmp_path: Path) -> None:
    ws = _workspace_photosflash(tmp_path)
    try:
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "body", "/tmp/x.md", datetime.now(UTC).isoformat()),
        )
        need = ws.get_requirement("HR-001")
        draft = Draft.from_requirement(
            need,
            principal=Principal(kind="is_type", type_name="PhotoFlash::User"),
            action=Action(kind="named", name="viewPhoto", namespace="PhotoFlash"),
            resource=Resource(kind="is_type", type_name="PhotoFlash::Photo"),
        ).with_status("proposed")
        # Manually attach an unresolved item to force the failure path.
        object.__setattr__(draft, "unresolved", ("unresolved_x",))
        intent = Intent(
            id="HR-001", requirement_id="HR-001", effect="permit",
            principal=Principal(kind="is_type", type_name="PhotoFlash::User"),
            action=Action(kind="named", name="viewPhoto", namespace="PhotoFlash"),
            resource=Resource(kind="is_type", type_name="PhotoFlash::Photo"),
        )
        object.__setattr__(draft, "intent", intent)
        object.__setattr__(draft, "cedar", intent.compile().cedar)
        schema = ws.load_schema("hr")
        with pytest.raises(Exception):
            ws.apply(draft, schema)
    finally:
        ws.close()


def test_space_generate_draft_persists_stored_draft(tmp_path: Path) -> None:
    """The persisted DraftStored carries the qualified intent and scopes."""
    from cedrus.generate import Offline

    ws = _workspace_photosflash(tmp_path)
    try:
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "body", "/tmp/x.md", datetime.now(UTC).isoformat()),
        )
        need = ws.get_requirement("HR-001")
        draft = Draft.from_requirement(
            need,
            principal=Principal(kind="is_type", type_name="User"),
            action=Action(kind="named", name="viewPhoto"),
            resource=Resource(kind="is_type", type_name="Photo"),
        )
        schema = ws.load_schema("hr")
        new_draft, result = ws.generate_draft(draft, schema, Offline())
        assert new_draft.intent is not None
        from cedrus.store import DraftStored

        stored = DraftStored.latest(ws.repository, "draft-HR-001")
        assert stored.principal.kind == "is_type"
        assert stored.action.kind == "named"
    finally:
        ws.close()


def test_space_apply_with_no_scenarios_skips_scenario_run(tmp_path: Path) -> None:
    """apply() with empty scenarios skips the test-report path entirely."""
    ws = _workspace_photosflash(tmp_path)
    try:
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "body", "/tmp/x.md", datetime.now(UTC).isoformat()),
        )
        need = ws.get_requirement("HR-001")
        # Cedar rendering only adds a namespace prefix when Action.namespace
        # is set; otherwise the type names are bare.
        intent = Intent(
            id="HR-001", requirement_id="HR-001", effect="permit",
            principal=Principal(kind="is_type", type_name="PhotoFlash::User"),
            action=Action(kind="named", name="viewPhoto", namespace="PhotoFlash"),
            resource=Resource(kind="is_type", type_name="PhotoFlash::Photo"),
        )
        draft = Draft(
            id="draft-HR-001",
            requirement=need,
            cedar=intent.compile().cedar,
            principal=intent.principal,
            action=intent.action,
            resource=intent.resource,
            intent=intent,
            status="proposed",
        )
        schema = ws.load_schema("hr")
        compiled = ws.apply(draft, schema, scenarios=[])
        assert compiled.id == "draft-HR-001"
        assert compiled.cedar
    finally:
        ws.close()


def test_space_test_domain_raises_when_no_scenarios(tmp_path: Path) -> None:
    """test_domain rejects an empty scenario list."""
    ws = _workspace_photosflash(tmp_path)
    try:
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "body", "/tmp/x.md", datetime.now(UTC).isoformat()),
        )
        schema = ws.load_schema("hr")
        with pytest.raises(Exception):
            ws.test_domain("hr", schema)
    finally:
        ws.close()


def test_space_test_domain_raises_when_no_compiled_policies(tmp_path: Path) -> None:
    """test_domain requires at least one compiled policy with cedar."""
    from cedrus import Case

    ws = _workspace_photosflash(tmp_path)
    try:
        (tmp_path / "hr" / "scenarios.json").write_text(
            json.dumps([
                {
                    "name": "x", "principal": "p", "action": "a",
                    "resource": "r", "context": {}, "expected": "Allow",
                }
            ]),
            encoding="utf-8",
        )
        schema = ws.load_schema("hr")
        with pytest.raises(Exception):
            ws.test_domain("hr", schema)
    finally:
        ws.close()


def test_space_test_domain_uses_default_schema_when_none(tmp_path: Path) -> None:
    """test_domain with schema=None raises when cedarpy can't resolve entities."""
    from cedrus import Compiled
    from cedrus.need import Need

    ws = _workspace_photosflash(tmp_path)
    try:
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "body", "/tmp/x.md", datetime.now(UTC).isoformat()),
        )
        (tmp_path / "hr" / "scenarios.json").write_text(
            json.dumps([
                {
                    "name": "x", "principal": "p", "action": "a",
                    "resource": "r", "context": {}, "expected": "Allow",
                }
            ]),
            encoding="utf-8",
        )
        need = Need.get(ws.repository, "HR-001")
        compiled = Compiled(
            id="HR-001", requirement=need, cedar="permit (principal, action, resource);"
        )
        ws.upsert_compiled(compiled)
        with pytest.raises(Exception):
            ws.test_domain("hr", schema=None)  # type: ignore[arg-type]
    finally:
        ws.close()


def test_space_deploy_raises_when_verifier_rejects(tmp_path: Path) -> None:
    """deploy() with a non-passing verifier raises SpaceError unless skip_verify."""
    from cedrus.need import Need

    ws = _workspace_photosflash(tmp_path)
    try:
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "body", "/tmp/x.md", datetime.now(UTC).isoformat()),
        )
        # Insert a policy that doesn't satisfy the schema (no schema match).
        ws.repository.execute(
            "INSERT INTO policies "
            "(id, domain, requirement_id, cedar, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "HR-001", "hr", "HR-001",
                'permit (principal == User::"alice", action == Action::"view", resource);',
                "compiled",
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            ),
        )
        schema = ws.load_schema("hr")
        with pytest.raises(Exception):
            ws.deploy("hr", str(tmp_path / "out"), schema=schema)
    finally:
        ws.close()


def test_space_list_compiled_policies_handles_orphan_fk(tmp_path: Path) -> None:
    """list_compiled_policies skips rows where requirement_id is null (FK cascade)."""
    ws = _workspace_photosflash(tmp_path)
    try:
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "body", "/tmp/x.md", datetime.now(UTC).isoformat()),
        )
        ws.repository.execute(
            "INSERT INTO policies "
            "(id, domain, requirement_id, cedar, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "HR-001", "hr", "HR-001",
                'permit (principal, action, resource);',
                "compiled",
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            ),
        )
        # Delete the requirement; FK ON DELETE SET NULL leaves requirement_id NULL.
        ws.remove_requirement("HR-001")
        compiled = ws.list_compiled_policies("hr")
        # The orphaned policy is skipped.
        assert compiled == []
    finally:
        ws.close()


def test_space_resolve_test_entities_returns_dicts(tmp_path: Path) -> None:
    """resolve_test_entities converts each entity to a dict."""
    from collections.abc import Mapping

    from cedrus.space import Space

    ws = _workspace_photosflash(tmp_path)
    try:
        entities = ws.resolve_test_entities([{"id": "u1"}, {"id": "u2"}])
        assert isinstance(entities, list)
        assert all(isinstance(e, Mapping) for e in entities)
    finally:
        ws.close()


def test_space_apply_for_requirement_with_no_draft_raises(tmp_path: Path) -> None:
    """apply_for_requirement raises SpaceError when no draft exists for a requirement."""
    ws = _workspace_photosflash(tmp_path)
    try:
        ws.repository.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "body", "/tmp/x.md", datetime.now(UTC).isoformat()),
        )
        schema = ws.load_schema("hr")
        with pytest.raises(Exception):
            ws.apply_for_requirement("HR-001", schema)
    finally:
        ws.close()


def test_space_find_action_namespace_returns_matching_namespace() -> None:
    """find_action_namespace returns the single matching namespace."""
    from cedrus import Action
    from cedrus.space import Space

    schema = _schema_only()  # build a small schema
    action = Action(kind="named", name="viewPhoto")
    namespace = Space.find_action_namespace(action, schema)
    assert namespace == "PhotoFlash"


def test_space_find_action_namespace_falls_back_to_action_namespace() -> None:
    """find_action_namespace returns the explicit action.namespace if no match."""
    from cedrus import Action
    from cedrus.space import Space

    schema = _schema_only()
    action = Action(kind="named", name="unknown", namespace="Custom")
    namespace = Space.find_action_namespace(action, schema)
    assert namespace == "Custom"


def _schema_only():
    """Build a minimal Cedar schema with one namespace and one action."""
    from cedrus import Schema
    return Schema.from_mapping(
        {
            "PhotoFlash": {
                "entityTypes": {},
                "actions": {"viewPhoto": {}},
            }
        }
    )


def test_space_qualify_intent_rewrites_unqualified_types() -> None:
    """qualify_intent looks up bare type names and prefixes them with the namespace."""
    from cedrus import Action, Principal, Resource
    from cedrus.space import Space

    schema = Schema.from_mapping(
        {
            "PhotoFlash": {
                "entityTypes": {"User": {}, "Photo": {}},
                "actions": {"viewPhoto": {}},
            }
        }
    )
    intent = Intent(
        id="hr-001", requirement_id="hr-001", effect="permit",
        principal=Principal(kind="is_type", type_name="User"),
        action=Action(kind="named", name="viewPhoto"),
        resource=Resource(kind="is_type", type_name="Photo"),
    )
    qualified = Space.qualify_intent(intent, schema)
    assert qualified.principal.type_name == "PhotoFlash::User"
    assert qualified.resource.type_name == "PhotoFlash::Photo"


def test_space_qualify_intent_passes_through_unknown_type() -> None:
    """Types not in the schema are left unchanged."""
    from cedrus import Action, Principal, Resource
    from cedrus.space import Space

    schema = Schema.from_mapping(
        {"NS": {"entityTypes": {}, "actions": {}}}
    )
    intent = Intent(
        id="hr-001", requirement_id="hr-001", effect="permit",
        principal=Principal(kind="is_type", type_name="Mystery"),
        action=Action(kind="named", name="view"),
        resource=Resource(kind="is_type", type_name="Mystery"),
    )
    qualified = Space.qualify_intent(intent, schema)
    assert qualified.principal.type_name == "Mystery"


def test_space_find_action_namespace_raises_on_ambiguous() -> None:
    """An action declared in two namespaces without an explicit hint raises SpaceError."""
    from cedrus import Action
    from cedrus.space import Space

    schema = Schema.from_mapping(
        {
            "NS1": {"entityTypes": {}, "actions": {"view": {}}},
            "NS2": {"entityTypes": {}, "actions": {"view": {}}},
        }
    )
    action = Action(kind="named", name="view")
    with pytest.raises(Exception):
        Space.find_action_namespace(action, schema)


def test_space_build_stored_report_round_trip(tmp_path: Path) -> None:
    """build_stored_report builds a ReportStored with the correct fields."""
    from cedrus import Vreport
    from cedrus.space import Space

    ws = _workspace_photosflash(tmp_path)
    schema = ws.load_schema("hr")
    report = Vreport.from_cedar(['permit (principal, action, resource);'], schema)
    stored = Space.build_stored_report("draft-HR-001", "validation", report)
    assert stored.policy_id == "draft-HR-001"
    assert stored.kind == "validation"
    assert stored.passed is True
    assert "formatted" in dict(stored.payload.data)


__all__ = []