"""Shared pytest fixtures for cedar-intent."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cedar_intent import (
    DraftPolicy,
    ExistingPolicy,
    Requirement,
)
from cedar_intent.schema import CedarSchema

PHOTOFLASH_SCHEMA = {
    "PhotoFlash": {
        "entityTypes": {
            "User": {"shape": {"type": "Record", "attributes": {"role": {"type": "String"}}}},
            "Photo": {
                "shape": {
                    "type": "Record",
                    "attributes": {"private": {"type": "Boolean"}},
                },
                "memberOfTypes": ["Album"],
            },
            "Album": {
                "shape": {
                    "type": "Record",
                    "attributes": {"private": {"type": "Boolean"}},
                }
            },
        },
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
            "viewAlbum": {
                "appliesTo": {
                    "principalTypes": ["User"],
                    "resourceTypes": ["Album"],
                }
            },
        },
    }
}


@pytest.fixture
def schema() -> CedarSchema:
    return CedarSchema.from_mapping(PHOTOFLASH_SCHEMA)


@pytest.fixture
def requirement() -> Requirement:
    return Requirement(
        id="HR-042",
        text="Only the album owner can view private photos.",
        domain="hr",
        source_path=Path("/tmp/HR-042.md"),
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def requirement_file(tmp_path: Path) -> Path:
    content = (
        "---\n"
        "id: HR-042\n"
        "domain: hr\n"
        "---\n\n"
        "Only the album owner can view private photos.\n"
    )
    path = tmp_path / "HR-042.md"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    domain = tmp_path / "hr"
    (domain / "requirements").mkdir(parents=True)
    (domain / "policies").mkdir(parents=True)
    (domain / "schema.json").write_text(json.dumps(PHOTOFLASH_SCHEMA), encoding="utf-8")
    (domain / "scenarios.json").write_text("[]", encoding="utf-8")
    (domain / "requirements" / "HR-001.md").write_text(
        "---\nid: HR-001\ndomain: hr\n---\n\nOnly owners can view private photos.\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def workspace(workspace_root: Path):
    from cedar_intent.workspace import Workspace

    ws = Workspace.open(workspace_root)
    try:
        yield ws
    finally:
        ws.close()


@pytest.fixture
def in_memory_workspace() -> Iterator:
    from cedar_intent.workspace import Workspace

    ws = Workspace.in_memory()
    try:
        yield ws
    finally:
        ws.close()


@pytest.fixture
def draft_policy(requirement: Requirement) -> DraftPolicy:
    return DraftPolicy.from_requirement(requirement)


@pytest.fixture
def existing_policy(requirement: Requirement) -> ExistingPolicy:
    cedar = (
        'permit (principal == PhotoFlash::User::"alice", '
        'action == PhotoFlash::Action::"viewPhoto", '
        'resource == PhotoFlash::Photo::"p1");'
    )
    return ExistingPolicy.from_requirement(requirement, cedar=cedar)
