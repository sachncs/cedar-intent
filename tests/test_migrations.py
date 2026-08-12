"""Tests for the schema migration path.

These tests construct a hand-crafted pre-0.6.0 SQLite database (no
action_scope_json, no draft intent/scope JSON) and exercise:

- detect_legacy_rows counts the legacy rows
- migrate_legacy_rows populates the new columns
- Sqlite.__post_init__ refuses to open a legacy database
- cedrus migrate CLI exits with the right code in each mode
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cedrus import Workspace
from cedrus.error import Store
from cedrus.migrate import detect_legacy_rows, migrate_legacy_rows


@pytest.fixture
def legacy_workspace(tmp_path: Path) -> Workspace:
    """Build a pre-0.6.0 SQLite workspace fixture.

    The fixture writes rows that lack the action_scope_json column
    (policies) and the intent_json + scope JSON columns (drafts), so
    detect_legacy_rows returns a positive count.
    """
    workspace_root = tmp_path / "acme"
    workspace_root.mkdir()
    workspace = Workspace.create(workspace_root)
    db = workspace.repository.path
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "Only admins can view.", "/tmp/HR-001.md", now),
        )
        connection.execute(
            "INSERT INTO policies (id, domain, requirement_id, intent_json, cedar, "
            "status, created_at, updated_at, action_scope_json) "
            "VALUES (?, ?, ?, NULL, ?, ?, ?, ?, NULL)",
            (
                "HR-001",
                "hr",
                "HR-001",
                'permit (principal, action == Action::"view", resource);',
                "compiled",
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO drafts (id, policy_id, model, request_id, "
            "unresolved_json, cedar, created_at, intent_json, "
            "principal_scope_json, action_scope_json, resource_scope_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL)",
            (
                "draft-1",
                "HR-001",
                "offline",
                None,
                "[]",
                'permit (principal, action == Action::"view", resource);',
                now,
            ),
        )
        connection.execute("DELETE FROM meta")
        connection.commit()
    return workspace


def test_detect_legacy_rows_returns_positive(legacy_workspace: Workspace) -> None:
    """detect_legacy_rows reports the legacy policy and draft count."""
    pending = detect_legacy_rows(legacy_workspace.repository)
    assert pending >= 1


def test_sqlite_repository_refuses_to_open_legacy_db(
    tmp_path: Path,
) -> None:
    """Opening a legacy database raises Store."""
    workspace_root = tmp_path / "acme"
    workspace_root.mkdir()
    Workspace.create(workspace_root)
    db = workspace_root / ".cedrus" / "store.db"
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(db) as connection:
        # Insert a row without action_scope_json so the post-migration
        # refuse_legacy_rows check finds a legacy row.
        connection.execute(
            "INSERT INTO requirements (id, domain, text, source_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("HR-001", "hr", "Body", "/tmp/HR-001.md", now),
        )
        connection.execute(
            "INSERT INTO policies (id, domain, requirement_id, intent_json, cedar, "
            "status, created_at, updated_at, action_scope_json) "
            "VALUES (?, ?, ?, NULL, ?, ?, ?, ?, NULL)",
            (
                "HR-001",
                "hr",
                "HR-001",
                'permit (principal, action == Action::"view", resource);',
                "compiled",
                now,
                now,
            ),
        )
        connection.execute("DELETE FROM meta")
        connection.commit()
    with pytest.raises(Store):
        Workspace.open(workspace_root)


def test_migrate_legacy_rows_populates_columns(legacy_workspace: Workspace) -> None:
    """migrate_legacy_rows writes the missing JSON columns."""
    repository = legacy_workspace.repository
    upgraded = migrate_legacy_rows(repository)
    assert upgraded >= 1
    assert detect_legacy_rows(repository) == 0


def test_migrate_cli_default_reports_count(
    legacy_workspace: Workspace, tmp_path: Path
) -> None:
    """``cedrus migrate`` prints the pending count and exits 0."""
    workspace_root = legacy_workspace.root
    result = subprocess.run(
        [sys.executable, "-m", "cedrus", "--workspace", str(workspace_root), "migrate"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "pending" in result.stdout.lower()


def test_migrate_cli_check_returns_nonzero_on_legacy(
    legacy_workspace: Workspace,
) -> None:
    """``cedrus migrate --check`` exits 1 when legacy rows exist."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "cedrus",
            "--workspace",
            str(legacy_workspace.root),
            "migrate",
            "--check",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1


def test_migrate_cli_check_returns_zero_after_apply(
    legacy_workspace: Workspace,
) -> None:
    """``--check`` exits 0 after a successful ``--apply``."""
    workspace_root = legacy_workspace.root
    apply = subprocess.run(
        [
            sys.executable,
            "-m",
            "cedrus",
            "--workspace",
            str(workspace_root),
            "migrate",
            "--apply",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert apply.returncode == 0, apply.stderr
    check = subprocess.run(
        [
            sys.executable,
            "-m",
            "cedrus",
            "--workspace",
            str(workspace_root),
            "migrate",
            "--check",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0


def test_migrate_cli_json_shape(legacy_workspace: Workspace) -> None:
    """``--json`` output contains the pending count."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "cedrus",
            "--json",
            "--workspace",
            str(legacy_workspace.root),
            "migrate",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "pending" in payload
