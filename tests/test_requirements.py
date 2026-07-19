"""Tests for the requirements module."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from cedar_intent import Requirement, load_requirement, load_requirements, render_requirement
from cedar_intent.errors import RequirementError
from cedar_intent.requirements import (
    derive_domain,
    parse_front_matter,
    slugify,
)


def test_parse_front_matter_with_metadata() -> None:
    source = (
        "---\n"
        "id: HR-001\n"
        'title: "Photo access"\n'
        "---\n\n"
        "Body text.\n"
    )
    front_matter, body = parse_front_matter(source)
    assert front_matter == {"id": "HR-001", "title": "Photo access"}
    assert body == "Body text."


def test_parse_front_matter_without_metadata() -> None:
    front_matter, body = parse_front_matter("# Hello world\n\nBody.\n")
    assert front_matter == {}
    assert body == "# Hello world\n\nBody."


def test_parse_front_matter_ignores_comments_and_blanks() -> None:
    source = (
        "---\n"
        "# a comment\n"
        "\n"
        "id: HR-042\n"
        "---\n\n"
        "Body\n"
    )
    front_matter, _ = parse_front_matter(source)
    assert front_matter == {"id": "HR-042"}


def test_parse_front_matter_unterminated_returns_body() -> None:
    front_matter, body = parse_front_matter("---\nid: missing\n\nBody")
    assert front_matter == {}
    assert "Body" in body


def test_parse_front_matter_malformed_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.md"
    path.write_text("---\nnot_a_valid_line\n---\n\nBody", encoding="utf-8")
    with pytest.raises(RequirementError):
        load_requirement(path)


def test_slugify_handles_punctuation_and_case() -> None:
    assert slugify("Hello, World!") == "hello-world"
    assert slugify("  --trim--  ") == "trim"
    assert slugify("CamelCase") == "camelcase"


def test_derive_domain_uses_first_directory(tmp_path: Path) -> None:
    root = tmp_path
    target = root / "hr" / "requirements" / "HR-042.md"
    target.parent.mkdir(parents=True)
    target.touch()
    assert derive_domain(target, root) == "hr"


def test_derive_domain_defaults_for_root_level(tmp_path: Path) -> None:
    target = tmp_path / "orphan.md"
    target.touch()
    assert derive_domain(target, tmp_path) == "default"


def test_load_requirement_from_file(tmp_path: Path) -> None:
    path = tmp_path / "hr" / "HR-042.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\nid: HR-042\ndomain: hr\n---\n\nBody text.\n", encoding="utf-8"
    )
    requirement = load_requirement(path, workspace_root=tmp_path)
    assert requirement.id == "HR-042"
    assert requirement.domain == "hr"
    assert "Body text." in requirement.text


def test_load_requirement_without_domain_uses_path(tmp_path: Path) -> None:
    path = tmp_path / "hr" / "requirements" / "HR-100.md"
    path.parent.mkdir(parents=True)
    path.write_text("Body", encoding="utf-8")
    requirement = load_requirement(path, workspace_root=tmp_path)
    assert requirement.domain == "hr"
    assert requirement.id == "HR-100"


def test_load_requirement_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(RequirementError):
        load_requirement(tmp_path / "nope.md")


def test_load_requirement_empty_body_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.md"
    path.write_text("---\nid: X\ndomain: hr\n---\n\n   \n", encoding="utf-8")
    with pytest.raises(RequirementError):
        load_requirement(path)


def test_load_requirements_returns_sorted_list(tmp_path: Path) -> None:
    directory = tmp_path
    for identifier in ("HR-003", "HR-001", "HR-002"):
        path = directory / f"{identifier}.md"
        path.write_text(
            f"---\nid: {identifier}\ndomain: hr\n---\n\nBody {identifier}\n",
            encoding="utf-8",
        )
    requirements = load_requirements(directory)
    assert [req.id for req in requirements] == ["HR-001", "HR-002", "HR-003"]


def test_load_requirements_missing_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(RequirementError):
        load_requirements(tmp_path / "missing")


def test_requirement_validation_enforces_non_empty_fields() -> None:
    with pytest.raises(RequirementError):
        Requirement(
            id="",
            text="body",
            domain="hr",
            source_path=Path("/tmp/x"),
            created_at=datetime.now(UTC),
        )
    with pytest.raises(RequirementError):
        Requirement(
            id="X",
            text="",
            domain="hr",
            source_path=Path("/tmp/x"),
            created_at=datetime.now(UTC),
        )
    with pytest.raises(RequirementError):
        Requirement(
            id="X",
            text="body",
            domain="",
            source_path=Path("/tmp/x"),
            created_at=datetime.now(UTC),
        )


def test_render_requirement_round_trip(requirement: Requirement) -> None:
    rendered = render_requirement(requirement)
    assert f"id: {requirement.id}" in rendered
    assert f"domain: {requirement.domain}" in rendered
    assert requirement.text in rendered
