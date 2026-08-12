"""Tests for :mod:`cedrus.need` — Markdown loader and helpers."""
from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cedrus.error import Require
from cedrus.need import (
    Need,
    derive_domain,
    parse_front_matter,
    render_requirement,
    slugify,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_slugify_lowercases_and_replaces_non_alnum() -> None:
    assert slugify("Hello World!!") == "hello-world"


def test_slugify_collapses_consecutive_hyphens() -> None:
    assert slugify("foo---bar") == "foo-bar"


def test_slugify_strips_leading_and_trailing_hyphens() -> None:
    assert slugify("--foo--") == "foo"


def test_slugify_handles_already_clean_string() -> None:
    assert slugify("hr-001") == "hr-001"


def test_slugify_empty_string() -> None:
    assert slugify("") == ""


def test_parse_front_matter_returns_dict_and_body() -> None:
    fm, body = parse_front_matter(
        "---\nid: HR-001\ndomain: hr\n---\n\nThe body.\n"
    )
    assert fm == {"id": "HR-001", "domain": "hr"}
    assert body == "The body."


def test_parse_front_matter_strips_quotes_from_value() -> None:
    fm, _ = parse_front_matter('---\nname: "Alice"\n---\n\nbody\n')
    assert fm["name"] == "Alice"


def test_parse_front_matter_returns_empty_dict_when_no_marker() -> None:
    fm, body = parse_front_matter("just body text\n")
    assert fm == {}
    assert body == "just body text"


def test_parse_front_matter_returns_empty_when_marker_unclosed() -> None:
    fm, body = parse_front_matter("---\nid: x\nno closing marker\n")
    assert fm == {}


def test_parse_front_matter_skips_comments_and_blanks() -> None:
    fm, _ = parse_front_matter(
        "---\n# header comment\n\nid: hr-001\n\n# inline comment\nkey: val\n---\nbody"
    )
    assert fm["id"] == "hr-001"
    assert fm["key"] == "val"


def test_parse_front_matter_raises_on_malformed_line() -> None:
    with pytest.raises(Require):
        parse_front_matter("---\nnot-a-valid-line\n---\nbody\n")


def test_derive_domain_returns_first_dir_under_workspace() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sub = root / "hr"
        sub.mkdir()
        md = sub / "HR-001.md"
        md.touch()
        assert derive_domain(md, root) == "hr"


def test_derive_domain_returns_default_when_at_root() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        md = root / "HR-001.md"
        md.touch()
        assert derive_domain(md, root) == "default"


def test_render_requirement_round_trip() -> None:
    need = Need(
        id="HR-001",
        text="The body.",
        domain="hr",
        source_path=Path("/tmp/HR-001.md"),
        created_at=datetime.now(UTC),
    )
    rendered = render_requirement(need)
    assert "id: HR-001" in rendered
    assert "domain: hr" in rendered
    assert "The body." in rendered


# ---------------------------------------------------------------------------
# Need data modelling
# ---------------------------------------------------------------------------


def test_need_rejects_empty_id() -> None:
    with pytest.raises(Require):
        Need(id="", text="x", domain="hr", source_path=Path("/tmp/x"), created_at=datetime.now(UTC))


def test_need_rejects_whitespace_id() -> None:
    with pytest.raises(Require):
        Need(id="   ", text="x", domain="hr", source_path=Path("/tmp/x"), created_at=datetime.now(UTC))


def test_need_rejects_empty_text() -> None:
    with pytest.raises(Require):
        Need(id="x", text="", domain="hr", source_path=Path("/tmp/x"), created_at=datetime.now(UTC))


def test_need_rejects_empty_domain() -> None:
    with pytest.raises(Require):
        Need(id="x", text="y", domain="", source_path=Path("/tmp/x"), created_at=datetime.now(UTC))


def test_need_parse_round_trips_via_to_data() -> None:
    need = Need(
        id="HR-001",
        text="Body",
        domain="hr",
        source_path=Path("/tmp/HR-001.md"),
        created_at=datetime.now(UTC),
    )
    rebuilt = Need.parse(need.to_data())
    assert rebuilt.id == need.id
    assert rebuilt.text == need.text
    assert rebuilt.domain == need.domain
    assert str(rebuilt.source_path) == str(need.source_path)


# ---------------------------------------------------------------------------
# Need.from_markdown / from_directory
# ---------------------------------------------------------------------------


def test_from_markdown_uses_id_from_front_matter() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        md = root / "hr" / "HR-001.md"
        md.parent.mkdir(parents=True)
        md.write_text(
            "---\nid: HR-001\ndomain: hr\n---\n\nBody.\n", encoding="utf-8"
        )
        need = Need.from_markdown(md, workspace_root=root)
        assert need.id == "HR-001"
        assert need.domain == "hr"


def test_from_markdown_falls_back_to_filename_stem_when_no_id() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        md = root / "hr" / "HR-042.md"
        md.parent.mkdir(parents=True)
        md.write_text("---\ndomain: hr\n---\n\nBody.\n", encoding="utf-8")
        need = Need.from_markdown(md, workspace_root=root)
        assert need.id == "HR-042"


def test_from_markdown_derives_domain_from_path_when_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        md = root / "hr" / "HR-001.md"
        md.parent.mkdir(parents=True)
        md.write_text("---\nid: HR-001\n---\n\nBody.\n", encoding="utf-8")
        need = Need.from_markdown(md, workspace_root=root)
        assert need.domain == "hr"


def test_from_markdown_raises_for_missing_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with pytest.raises(Require):
            Need.from_markdown(root / "missing.md", workspace_root=root)


def test_from_markdown_raises_for_empty_body() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        md = root / "hr" / "HR-001.md"
        md.parent.mkdir(parents=True)
        md.write_text("---\nid: HR-001\ndomain: hr\n---\n", encoding="utf-8")
        with pytest.raises(Require):
            Need.from_markdown(md, workspace_root=root)


def test_from_markdown_uses_default_domain_at_root() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        md = root / "HR-001.md"
        md.write_text("---\nid: HR-001\n---\n\nBody.\n", encoding="utf-8")
        need = Need.from_markdown(md, workspace_root=root)
        assert need.domain == "default"


def test_from_directory_loads_every_md_in_sorted_order() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        d = root / "hr" / "requirements"
        d.mkdir(parents=True)
        (d / "HR-002.md").write_text(
            "---\nid: HR-002\ndomain: hr\n---\n\nB.\n", encoding="utf-8"
        )
        (d / "HR-001.md").write_text(
            "---\nid: HR-001\ndomain: hr\n---\n\nA.\n", encoding="utf-8"
        )
        needs = Need.from_directory(d, workspace_root=root)
        assert [n.id for n in needs] == ["HR-001", "HR-002"]


def test_from_directory_skips_non_md_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        d = root / "hr" / "requirements"
        d.mkdir(parents=True)
        (d / "HR-001.md").write_text(
            "---\nid: HR-001\ndomain: hr\n---\n\nA.\n", encoding="utf-8"
        )
        (d / "ignore.txt").write_text("ignored", encoding="utf-8")
        needs = Need.from_directory(d, workspace_root=root)
        assert [n.id for n in needs] == ["HR-001"]


def test_from_directory_raises_for_missing_directory() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(Require):
            Need.from_directory(Path(tmp) / "nope")


__all__ = []