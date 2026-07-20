"""Tests for the schema wrapper."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cedar_intent import CedarSchema
from cedar_intent.errors import ValidationError


def test_schema_from_mapping_exposes_types_and_actions() -> None:
    schema = CedarSchema.from_mapping(
        {"PhotoFlash": {"entityTypes": {"User": {}, "Photo": {}}, "actions": {"viewPhoto": {}}}}
    )
    assert schema.entity_type_names() == {"PhotoFlash::User", "PhotoFlash::Photo"}
    assert schema.action_names() == {("PhotoFlash", "viewPhoto")}
    assert schema.namespace_of("PhotoFlash::User") == "PhotoFlash"


def test_schema_from_mapping_empty_raises() -> None:
    with pytest.raises(ValidationError):
        CedarSchema.from_mapping({})


def test_schema_from_mapping_invalid_data_raises() -> None:
    with pytest.raises(ValidationError):
        CedarSchema.from_mapping({"namespace": "not-a-mapping"})


def test_schema_from_json_file(tmp_path: Path) -> None:
    payload = {"Demo": {"entityTypes": {"User": {}}, "actions": {"view": {}}}}
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    schema = CedarSchema.from_json_file(path)
    assert "Demo::User" in schema.entity_type_names()


def test_schema_from_json_file_missing(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        CedarSchema.from_json_file(tmp_path / "absent.json")


def test_schema_from_json_file_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not valid", encoding="utf-8")
    with pytest.raises(ValidationError):
        CedarSchema.from_json_file(path)


def test_schema_from_json_file_non_object(tmp_path: Path) -> None:
    path = tmp_path / "list.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValidationError):
        CedarSchema.from_json_file(path)


def test_schema_namespace_of_unqualified_returns_none() -> None:
    schema = CedarSchema.from_mapping(
        {"Demo": {"entityTypes": {"User": {}}, "actions": {}}}
    )
    assert schema.namespace_of("User") is None
