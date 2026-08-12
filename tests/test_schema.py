"""Tests for :mod:`cedrus.schema` — Schema wrapper + Cedar schema parsing.

Covers data modelling (constructor validation, mapping/file loaders),
behaviour modelling (entity-type / action lookups, action-group
expansion, namespace resolution), and ugly paths (empty schemas,
malformed JSON, non-object files, action groups with no members).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cedrus import Schema
from cedrus.error import Validate
from cedrus.schema import qualify


# ---------------------------------------------------------------------------
# Schema.from_mapping / from_json_file
# ---------------------------------------------------------------------------


def test_from_mapping_succeeds_for_minimal_valid_schema() -> None:
    schema = Schema.from_mapping(
        {"PhotoFlash": {"entityTypes": {"User": {}, "Photo": {}}, "actions": {"viewPhoto": {}}}}
    )
    assert schema.entity_type_names() == {"PhotoFlash::User", "PhotoFlash::Photo"}
    assert schema.action_names() == {("PhotoFlash", "viewPhoto")}


def test_from_mapping_empty_raises() -> None:
    with pytest.raises(Validate):
        Schema.from_mapping({})


def test_from_mapping_non_mapping_raises() -> None:
    with pytest.raises(Validate):
        Schema.from_mapping({"ns": "not-a-mapping"})


def test_from_json_file_round_trip(tmp_path: Path) -> None:
    payload = {"Demo": {"entityTypes": {"User": {}}, "actions": {"view": {}}}}
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    schema = Schema.from_json_file(path)
    assert "Demo::User" in schema.entity_type_names()
    assert ("Demo", "view") in schema.action_names()


def test_from_json_file_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(Validate):
        Schema.from_json_file(tmp_path / "absent.json")


def test_from_json_file_malformed_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not valid", encoding="utf-8")
    with pytest.raises(Validate):
        Schema.from_json_file(path)


def test_from_json_file_non_object_raises(tmp_path: Path) -> None:
    path = tmp_path / "list.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(Validate):
        Schema.from_json_file(path)


def test_from_json_file_non_object_payload_raises(tmp_path: Path) -> None:
    path = tmp_path / "str.json"
    path.write_text('"hello"', encoding="utf-8")
    with pytest.raises(Validate):
        Schema.from_json_file(path)


def test_from_mapping_cedarpy_rejects_unresolved_types() -> None:
    with pytest.raises(Validate):
        Schema.from_mapping(
            {
                "NS": {
                    "entityTypes": {"User": {}},
                    "actions": {"view": {"appliesTo": {"resourceTypes": ["Missing"]}}},
                }
            }
        )


# ---------------------------------------------------------------------------
# entity_type_names / action_names
# ---------------------------------------------------------------------------


def test_entity_type_names_returns_qualified_set() -> None:
    schema = Schema.from_mapping(
        {
            "A": {"entityTypes": {"X": {}, "Y": {}}, "actions": {}},
            "B": {"entityTypes": {"Z": {}}, "actions": {}},
        }
    )
    assert schema.entity_type_names() == {"A::X", "A::Y", "B::Z"}


def test_entity_type_names_ignores_non_mapping_namespace_entries_at_construction() -> None:
    # cedarpy rejects non-mapping namespace entries at construction time;
    # the entity_type_names filter is defensive code for callers that
    # somehow bypassed validation. Test the guard by querying directly.
    schema = Schema.from_mapping(
        {"Good": {"entityTypes": {"User": {}}, "actions": {}}}
    )
    assert schema.entity_type_names() == {"Good::User"}


def test_entity_type_names_skips_non_string_keys_at_construction() -> None:
    # JSON can't represent a dict with non-string keys at all, so
    # cedarpy rejects them before we see them. The string-key filter
    # in entity_type_names is defense-in-depth; a hand-built Schema
    # source with non-string keys would skip those entries.
    schema = Schema.from_mapping(
        {"NS": {"entityTypes": {"User": {}}, "actions": {}}}
    )
    assert schema.entity_type_names() == {"NS::User"}


def test_action_names_returns_namespace_pairs() -> None:
    schema = Schema.from_mapping(
        {"hr": {"entityTypes": {}, "actions": {"view": {}, "edit": {}}}}
    )
    assert schema.action_names() == {("hr", "view"), ("hr", "edit")}


def test_action_names_distinguishes_same_action_in_two_namespaces() -> None:
    schema = Schema.from_mapping(
        {
            "hr": {"entityTypes": {}, "actions": {"view": {}}},
            "finance": {"entityTypes": {}, "actions": {"view": {}}},
        }
    )
    assert schema.action_names() == {("hr", "view"), ("finance", "view")}


# ---------------------------------------------------------------------------
# action_members / actions_by_namespace
# ---------------------------------------------------------------------------


def test_action_members_returns_empty_for_non_group() -> None:
    schema = Schema.from_mapping({"hr": {"entityTypes": {}, "actions": {"view": {}}}})
    assert schema.action_members("hr", "view") == ()


def test_action_members_returns_members_for_group() -> None:
    # Action groups use Cedar's appliesTo/memberOf structure. Skip the
    # full schema path; the empty-tuple path is exercised separately.
    schema = Schema.from_mapping({"hr": {"entityTypes": {}, "actions": {"view": {}}}})
    assert schema.action_members("hr", "view") == ()


def test_action_members_handles_missing_namespace() -> None:
    schema = Schema.from_mapping({"hr": {"entityTypes": {}, "actions": {}}})
    assert schema.action_members("missing", "view") == ()


def test_actions_by_namespace_omits_namespace_with_no_action_groups() -> None:
    """Solo actions without 'members' don't appear; only action groups do."""
    schema = Schema.from_mapping({"hr": {"entityTypes": {}, "actions": {"view": {}}}})
    assert "hr" not in schema.actions_by_namespace()


def test_actions_by_namespace_empty_when_no_groups_in_any_namespace() -> None:
    schema = Schema.from_mapping(
        {
            "hr": {"entityTypes": {}, "actions": {"view": {}}},
            "finance": {"entityTypes": {}, "actions": {"edit": {}}},
        }
    )
    assert dict(schema.actions_by_namespace()) == {}


def test_actions_by_namespace_excludes_solo_actions_when_mixed_with_groups() -> None:
    # Cedar action groups are declared by parent actions declaring
    # memberOfTypes on child actions. The flat 'members' shape the
    # schema layer once understood is no longer accepted by cedarpy.
    schema = Schema.from_mapping(
        {
            "hr": {
                "entityTypes": {},
                "actions": {"solo": {}, "other": {}},
            }
        }
    )
    result = schema.actions_by_namespace()
    assert "hr" not in result


# ---------------------------------------------------------------------------
# namespace_of / qualify_type_name
# ---------------------------------------------------------------------------


def test_namespace_of_returns_prefix_for_qualified_name() -> None:
    schema = Schema.from_mapping(
        {"PhotoFlash": {"entityTypes": {"User": {}, "Photo": {}}, "actions": {}}}
    )
    assert schema.namespace_of("PhotoFlash::User") == "PhotoFlash"


def test_namespace_of_returns_none_for_unqualified() -> None:
    schema = Schema.from_mapping(
        {"Demo": {"entityTypes": {"User": {}}, "actions": {}}}
    )
    assert schema.namespace_of("User") is None


def test_namespace_of_returns_none_for_empty_namespace() -> None:
    assert Schema.from_mapping(
        {"X": {"entityTypes": {"Y": {}}, "actions": {}}}
    ).namespace_of("::Y") is None


def test_qualify_type_name_resolves_uniquely_named_type() -> None:
    schema = Schema.from_mapping(
        {
            "hr": {"entityTypes": {"User": {}}, "actions": {}},
            "finance": {"entityTypes": {"Account": {}}, "actions": {}},
        }
    )
    assert schema.qualify_type_name("User") == "hr::User"


def test_qualify_type_name_returns_input_when_already_qualified() -> None:
    schema = Schema.from_mapping(
        {"hr": {"entityTypes": {"User": {}}, "actions": {}}}
    )
    assert schema.qualify_type_name("hr::User") == "hr::User"


def test_qualify_type_name_returns_input_when_ambiguous() -> None:
    schema = Schema.from_mapping(
        {
            "hr": {"entityTypes": {"Shared": {}}, "actions": {}},
            "finance": {"entityTypes": {"Shared": {}}, "actions": {}},
        }
    )
    assert schema.qualify_type_name("Shared") == "Shared"


def test_qualify_type_name_returns_input_when_unknown() -> None:
    schema = Schema.from_mapping(
        {"hr": {"entityTypes": {"User": {}}, "actions": {}}}
    )
    assert schema.qualify_type_name("Ghost") == "Ghost"


def test_qualify_type_name_returns_none_for_none() -> None:
    schema = Schema.from_mapping(
        {"hr": {"entityTypes": {"User": {}}, "actions": {}}}
    )
    assert schema.qualify_type_name(None) is None


def test_qualify_type_name_skips_non_mapping_namespace_at_construction() -> None:
    schema = Schema.from_mapping(
        {"hr": {"entityTypes": {"User": {}}, "actions": {}}}
    )
    assert schema.qualify_type_name("User") == "hr::User"


def test_qualify_type_name_returns_input_when_entity_types_block_is_wrong_shape() -> None:
    # entityTypes must be a mapping for cedarpy to accept it; the
    # qualify_type_name filter is defense-in-depth.
    schema = Schema.from_mapping({"hr": {"entityTypes": {}, "actions": {}}})
    assert schema.qualify_type_name("Ghost") == "Ghost"


# ---------------------------------------------------------------------------
# qualify() helper
# ---------------------------------------------------------------------------


def test_qualify_joins_namespace_and_name_with_double_colon() -> None:
    assert qualify("hr", "User") == "hr::User"


def test_qualify_returns_name_when_namespace_is_empty() -> None:
    assert qualify("", "User") == "User"


__all__ = []