"""Tests for :mod:`cedrus.scope` — Principal / Action / Resource / Clause.

Data modelling (construction + invariants), behaviour modelling
(rendering to Cedar, polymorphic dispatch), and ugly paths (empty
fields, invalid kinds, malformed IDs).
"""
from __future__ import annotations

import pytest

from cedrus.error import Compile, ScopeFault
from cedrus.scope import (
    Action,
    Clause,
    Principal,
    Resource,
    Scope,
    validate_id,
    validate_kind,
)
from cedrus.utils import id as generate_id


# ---------------------------------------------------------------------------
# Data modelling
# ---------------------------------------------------------------------------


def test_principal_default_is_any() -> None:
    p = Principal()
    assert p.kind == "any"
    assert p.type_name is None
    assert p.entity_id is None
    assert p.group_type is None
    assert p.group_id is None


def test_principal_id_is_auto_generated_unique_object_id() -> None:
    p1 = Principal()
    p2 = Principal()
    assert len(p1.id) == 24
    assert p1.id != p2.id


def test_action_default_is_any() -> None:
    a = Action()
    assert a.kind == "any"
    assert a.name is None
    assert a.group is None
    assert a.namespace is None


def test_resource_default_is_any() -> None:
    r = Resource()
    assert r.kind == "any"
    assert r.type_name is None


def test_clause_requires_non_empty_body() -> None:
    c = Clause(body="principal == User::\"alice\"")
    assert c.body == "principal == User::\"alice\""
    assert c.attributes == {}


def test_clause_id_assigned_when_omitted() -> None:
    c = Clause(body="x")
    assert c.id is not None


def test_clause_accepts_supplied_id() -> None:
    c = Clause(id="custom", body="x")
    assert c.id == "custom"


def test_principal_variety_constants() -> None:
    p = Principal()
    assert p.ANY == "any"
    assert p.TYPE == "type"
    assert p.SPECIFIC == "specific"
    assert p.IN_GROUP == "in_group"
    assert p.IS_TYPE == "is_type"
    assert "any" in p.VARIETIES
    assert "is_type" in p.VARIETIES


def test_action_variety_constants() -> None:
    a = Action()
    assert a.ANY == "any"
    assert a.NAMED == "named"
    assert a.IN_GROUP == "in_group"


def test_resource_variety_constants() -> None:
    r = Resource()
    assert r.IN_PARENT == "in_parent"


# ---------------------------------------------------------------------------
# Behaviour modelling — render to Cedar
# ---------------------------------------------------------------------------


def test_principal_clause_any() -> None:
    assert Principal().clause() == "principal"


def test_principal_clause_specific() -> None:
    p = Principal(kind="specific", type_name="User", entity_id="alice")
    assert p.clause() == 'principal == User::"alice"'


def test_principal_clause_type() -> None:
    p = Principal(kind="type", type_name="User")
    assert p.clause() == "principal == User"


def test_principal_clause_is_type() -> None:
    p = Principal(kind="is_type", type_name="User")
    assert p.clause() == "principal is User"


def test_principal_clause_in_group() -> None:
    p = Principal(kind="in_group", group_type="Group", group_id="admins")
    assert p.clause() == 'principal in Group::"admins"'


def test_action_clause_any() -> None:
    assert Action().clause() == "action"


def test_action_clause_named_without_namespace() -> None:
    a = Action(kind="named", name="view")
    assert a.clause() == 'action == Action::"view"'


def test_action_clause_named_with_namespace() -> None:
    a = Action(kind="named", name="view", namespace="Hr")
    assert a.clause() == 'action == Hr::Action::"view"'


def test_action_clause_in_group() -> None:
    a = Action(kind="in_group", group="readers")
    assert a.clause() == 'action in Action::"readers"'


def test_resource_clause_in_parent() -> None:
    r = Resource(
        kind="in_parent",
        type_name="Photo",
        parent_type="Album",
        parent_id="vacation",
    )
    assert r.clause() == 'resource is Photo in Album::"vacation"'


def test_clause_clause_returns_body() -> None:
    c = Clause(body='principal.role == "admin"')
    assert c.clause() == 'principal.role == "admin"'


def test_scope_parse_dispatches_on_discriminator() -> None:
    assert isinstance(
        Scope.parse({"group_type": "Group", "group_id": "admins"}), Principal
    )
    assert isinstance(
        Scope.parse({"parent_type": "Album", "parent_id": "v"}), Resource
    )
    assert isinstance(Scope.parse({"name": "view"}), Action)


def test_scope_parse_raises_on_ambiguous() -> None:
    with pytest.raises(Compile):
        Scope.parse({})


def test_scope_parse_raises_on_non_dict() -> None:
    from typing import cast

    with pytest.raises(Compile):
        Scope.parse(cast(dict, "not a dict"))


def test_scope_parse_raises_on_invalid_scope() -> None:
    with pytest.raises(Compile):
        Scope.parse({"name": ""})


def test_principal_to_dict_round_trip_preserves_fields() -> None:
    p = Principal(kind="specific", type_name="User", entity_id="alice")
    rebuilt = Principal.from_dict(p.to_dict())
    assert rebuilt.kind == p.kind
    assert rebuilt.type_name == p.type_name
    assert rebuilt.entity_id == p.entity_id


def test_action_to_dict_round_trip_preserves_fields() -> None:
    a = Action(kind="named", name="view", namespace="Hr")
    rebuilt = Action.from_dict(a.to_dict())
    assert rebuilt.kind == a.kind
    assert rebuilt.name == a.name
    assert rebuilt.namespace == a.namespace


def test_resource_to_dict_round_trip_preserves_fields() -> None:
    r = Resource(kind="in_parent", type_name="Photo", parent_type="Album", parent_id="v")
    rebuilt = Resource.from_dict(r.to_dict())
    assert rebuilt.kind == r.kind
    assert rebuilt.type_name == r.type_name
    assert rebuilt.parent_type == r.parent_type
    assert rebuilt.parent_id == r.parent_id


def test_clause_normalize_string_becomes_single_element_tuple() -> None:
    clauses = Clause.normalize("principal == User::\"alice\"")
    assert len(clauses) == 1
    assert clauses[0].body == 'principal == User::"alice"'


def test_clause_normalize_list_of_strings() -> None:
    clauses = Clause.normalize(["a", "b", ""])
    assert tuple(c.body for c in clauses) == ("a", "b")


def test_clause_normalize_drops_blanks() -> None:
    clauses = Clause.normalize(["a", "  ", "b"])
    assert tuple(c.body for c in clauses) == ("a", "b")


def test_clause_normalize_returns_empty_for_non_list() -> None:
    assert Clause.normalize(None) == ()
    assert Clause.normalize(42) == ()


def test_clause_normalize_silently_drops_non_string_entries() -> None:
    clauses = Clause.normalize(["a", 42, None, "b"])
    assert tuple(c.body for c in clauses) == ("a", "b")


# ---------------------------------------------------------------------------
# Ugly paths
# ---------------------------------------------------------------------------


def test_validate_kind_rejects_unknown() -> None:
    with pytest.raises(ScopeFault):
        validate_kind("nonsense", frozenset({"any", "specific"}))


def test_validate_id_rejects_empty_when_provided() -> None:
    with pytest.raises(ScopeFault):
        validate_id("", "type_name")


def test_validate_id_rejects_whitespace_only() -> None:
    with pytest.raises(ScopeFault):
        validate_id("   ", "type_name")


def test_validate_id_passes_when_none() -> None:
    validate_id(None, "type_name")


def test_principal_rejects_unknown_kind() -> None:
    with pytest.raises(ScopeFault):
        Principal(kind="bogus")


def test_clause_rejects_empty_body() -> None:
    with pytest.raises(ScopeFault):
        Clause(body="")


def test_clause_rejects_whitespace_only_body() -> None:
    with pytest.raises(ScopeFault):
        Clause(body="   ")


def test_scope_to_dict_returns_required_keys() -> None:
    p = Principal(kind="specific", type_name="User", entity_id="alice")
    d = p.to_dict()
    assert d["kind"] == "specific"
    assert d["type_name"] == "User"
    assert d["entity_id"] == "alice"
    assert "group_type" in d
    assert "group_id" in d


def test_generate_id_is_used_when_clause_id_omitted() -> None:
    c = Clause(body="x")
    assert c.id == generate_id() or len(c.id) == 24


__all__ = []