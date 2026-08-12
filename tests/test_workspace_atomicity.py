"""Tests for workspace atomicity and dedup.

Covers the three Workspace hardening items from audit O-6, O-9, O-12:

- Workspace.apply wraps validation report + scenario test report +
  policy upsert in a single transaction. If a scenario fails, no
  report or policy is persisted.
- Workspace.init_domain writes schema.json atomically (temp file +
  rename), so a crash mid-write can never leave a truncated file.
- Workspace.import_existing_policies raises Space on
  duplicate file stems instead of silently merging them via upsert.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cedrus import (
    Action,
    Case,
    Intent,
    Need,
    Principal,
    Resource,
    Space,
    Workspace,
)


def _make_requirement(domain: str = "hr", identifier: str = "HR-001") -> Need:
    return Need(
        id=identifier,
        text="Body",
        domain=domain,
        source_path=Path(f"/tmp/{identifier}.md"),
        created_at=datetime.now(UTC),
    )


def _init_domain(workspace: Workspace) -> None:
    """Initialise a domain with a PhotoFlash schema for the apply test."""
    workspace.init_domain("hr")
    schema_path = workspace.schema_path("hr")
    schema_path.write_text(
        '{"PhotoFlash": {"entityTypes": {"User": {}, "Photo": {}}, '
        '"actions": {"view": {"appliesTo": {"principalTypes": ["User"], '
        '"resourceTypes": ["Photo"]}}, "edit": {}}}}',
        encoding="utf-8",
    )


# ---- Workspace.apply atomicity -----------------------------------------------


def test_apply_persists_validation_report_and_policy_in_one_transaction(
    tmp_path: Path,
) -> None:
    workspace = Workspace.create(tmp_path / "acme")
    _init_domain(workspace)
    schema = workspace.load_schema("hr")
    requirement = _make_requirement()
    workspace.repository.add_requirement(requirement)

    from cedrus.policies import Draft

    intent = Intent(
        id=requirement.id,
        requirement_id=requirement.id,
        effect="permit",
        principal=Principal(kind="is_type", type_name="User"),
        action=Action(kind="named", name="view", namespace="PhotoFlash"),
        resource=Resource(kind="is_type", type_name="Photo"),
    )
    draft = Draft(
        id=requirement.id,
        requirement=requirement,
        intent=intent,
        principal=intent.principal,
        action=intent.action,
        resource=intent.resource,
        cedar='permit (principal is PhotoFlash::User, '
        'action == PhotoFlash::Action::"view", resource is PhotoFlash::Photo);',
        unresolved=(),
        notes={},
    )
    compiled = workspace.apply(draft, schema)
    assert "permit" in compiled.cedar
    assert workspace.repository.latest_report(requirement.id, "validation").passed


def test_apply_rolls_back_when_scenario_fails(tmp_path: Path) -> None:
    """A failed scenario must roll back the validation report and the policy."""
    workspace = Workspace.create(tmp_path / "acme")
    _init_domain(workspace)
    schema = workspace.load_schema("hr")
    requirement = _make_requirement()
    workspace.repository.add_requirement(requirement)

    from cedrus.policies import Draft

    intent = Intent(
        id=requirement.id,
        requirement_id=requirement.id,
        effect="permit",
        principal=Principal(kind="is_type", type_name="User"),
        action=Action(kind="named", name="view"),
        resource=Resource(kind="any"),
    )
    draft = Draft(
        id=requirement.id,
        requirement=requirement,
        intent=intent,
        principal=intent.principal,
        action=intent.action,
        resource=intent.resource,
        cedar='permit (principal is PhotoFlash::User, '
        'action == PhotoFlash::Action::"view", resource);',
        unresolved=(),
        notes={},
    )
    scenarios = [
        Case(
            name="deny-alice",
            principal="PhotoFlash::User::\"alice\"",
            action='PhotoFlash::Action::"view"',
            resource="PhotoFlash::Photo::\"p1\"",
            context={},
            expected="Deny",
        )
    ]
    with pytest.raises(Space):
        workspace.apply(draft, schema, scenarios=scenarios)

    # The apply was rolled back: no policy row, no validation report,
    # no test report.
    with sqlite3.connect(workspace.repository.path) as conn:
        policy_rows = conn.execute(
            "SELECT COUNT(*) FROM policies WHERE id = ?", (requirement.id,)
        ).fetchone()[0]
        validation_rows = conn.execute(
            "SELECT COUNT(*) FROM reports WHERE policy_id = ? AND kind = 'validation'",
            (requirement.id,),
        ).fetchone()[0]
        test_rows = conn.execute(
            "SELECT COUNT(*) FROM reports WHERE policy_id = ? AND kind = 'test'",
            (requirement.id,),
        ).fetchone()[0]
    assert policy_rows == 0
    assert validation_rows == 0
    assert test_rows == 0


def test_apply_passes_when_scenario_succeeds(tmp_path: Path) -> None:
    """Passing scenario persists all reports and the compiled policy."""
    workspace = Workspace.create(tmp_path / "acme")
    _init_domain(workspace)
    schema = workspace.load_schema("hr")
    requirement = _make_requirement()
    workspace.repository.add_requirement(requirement)

    from cedrus.policies import Draft

    intent = Intent(
        id=requirement.id,
        requirement_id=requirement.id,
        effect="permit",
        principal=Principal(kind="is_type", type_name="User"),
        action=Action(kind="named", name="view"),
        resource=Resource(kind="any"),
    )
    draft = Draft(
        id=requirement.id,
        requirement=requirement,
        intent=intent,
        principal=intent.principal,
        action=intent.action,
        resource=intent.resource,
        cedar='permit (principal is PhotoFlash::User, '
        'action == PhotoFlash::Action::"view", resource);',
        unresolved=(),
        notes={},
    )
    scenarios = [
        Case(
            name="allow-alice",
            principal="PhotoFlash::User::\"alice\"",
            action='PhotoFlash::Action::"view"',
            resource="PhotoFlash::Photo::\"p1\"",
            context={},
            expected="Allow",
        )
    ]
    workspace.apply(draft, schema, scenarios=scenarios)
    with sqlite3.connect(workspace.repository.path) as conn:
        policy_rows = conn.execute(
            "SELECT COUNT(*) FROM policies WHERE id = ?", (requirement.id,)
        ).fetchone()[0]
        report_kinds = conn.execute(
            "SELECT kind FROM reports WHERE policy_id = ? ORDER BY kind",
            (requirement.id,),
        ).fetchall()
    assert policy_rows == 1
    assert {row[0] for row in report_kinds} == {"test", "validation"}


# ---- Workspace.init_domain atomicity ----------------------------------------


def test_init_domain_writes_schema_atomically(tmp_path: Path) -> None:
    """No partial schema.json is left behind on disk after init_domain."""
    workspace = Workspace.create(tmp_path / "acme")
    _init_domain(workspace)
    schema_path = workspace.schema_path("hr")
    assert schema_path.exists()
    # No leftover staging file.
    staging = list(schema_path.parent.glob(f".{schema_path.name}.*.tmp"))
    assert staging == []
    contents = schema_path.read_text(encoding="utf-8")
    assert "PhotoFlash" in contents


def test_init_domain_idempotent(tmp_path: Path) -> None:
    """Calling init_domain twice leaves the existing schema untouched."""
    workspace = Workspace.create(tmp_path / "acme")
    _init_domain(workspace)
    schema_path = workspace.schema_path("hr")
    original = schema_path.read_text(encoding="utf-8")
    # Re-running should not touch the file because it already exists.
    workspace.init_domain("hr")
    assert schema_path.read_text(encoding="utf-8") == original


# ---- Workspace.import_existing_policies dedup ------------------------------


def test_import_existing_policies_rejects_duplicate_stems(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two glob hits with the same stem raise Space.

    Stem collisions cannot happen on a single directory because two
    files cannot share a name, but the dedup guards against a
    future feature (recursive globbing, symlink following) that
    could yield duplicates.
    """
    workspace = Workspace.create(tmp_path / "acme")
    _init_domain(workspace)
    policies_dir = workspace.policies_directory("hr")
    policies_dir.mkdir(parents=True, exist_ok=True)
    policy_path = policies_dir / "HR-001.cedar"
    policy_path.write_text(
        "permit (principal, action, resource);", encoding="utf-8"
    )
    # Stub Path.glob so the dedup check sees the same path twice.
    original_glob = Path.glob

    def duplicate_glob(self: Path, pattern: str) -> list[Path]:
        matches = list(original_glob(self, pattern))
        return matches + matches

    monkeypatch.setattr(Path, "glob", duplicate_glob)
    with pytest.raises(Space) as excinfo:
        workspace.import_existing_policies("hr")
    assert "duplicate" in str(excinfo.value).lower()


def test_import_existing_policies_imports_unique_files(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path / "acme")
    _init_domain(workspace)
    policies_dir = workspace.policies_directory("hr")
    policies_dir.mkdir(parents=True, exist_ok=True)
    (policies_dir / "HR-001.cedar").write_text(
        "permit (principal, action, resource);", encoding="utf-8"
    )
    (policies_dir / "HR-002.cedar").write_text(
        "forbid (principal, action, resource);", encoding="utf-8"
    )
    imported = workspace.import_existing_policies("hr")
    assert len(imported) == 2
    ids = {policy.id for policy in imported}
    assert ids == {"existing-HR-001", "existing-HR-002"}
