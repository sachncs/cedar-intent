"""Tests for scope and condition classes."""

from __future__ import annotations

import pytest

from cedar_intent import ActionScope, ConditionClause, PrincipalScope, ResourceScope
from cedar_intent.errors import ScopeError


def test_principal_any_passes() -> None:
    scope = PrincipalScope(kind="any")
    assert scope.kind == "any"


def test_principal_type_requires_type_name() -> None:
    with pytest.raises(ScopeError):
        PrincipalScope(kind="type")


def test_principal_specific_requires_type_and_entity() -> None:
    with pytest.raises(ScopeError):
        PrincipalScope(kind="specific", type_name="User")
    with pytest.raises(ScopeError):
        PrincipalScope(kind="specific", entity_id="alice")


def test_principal_in_group_requires_group_fields() -> None:
    with pytest.raises(ScopeError):
        PrincipalScope(kind="in_group", group_type="Group")
    PrincipalScope(kind="in_group", group_type="Group", group_id="admins")  # ok


def test_action_any_and_named() -> None:
    assert ActionScope().kind == "any"
    with pytest.raises(ScopeError):
        ActionScope(kind="named")
    assert ActionScope(kind="named", name="view").name == "view"


def test_action_in_group_requires_group() -> None:
    with pytest.raises(ScopeError):
        ActionScope(kind="in_group")
    assert ActionScope(kind="in_group", group="admin").group == "admin"


def test_resource_any_passes() -> None:
    assert ResourceScope().kind == "any"


def test_resource_type_variants() -> None:
    with pytest.raises(ScopeError):
        ResourceScope(kind="type")
    with pytest.raises(ScopeError):
        ResourceScope(kind="is_type")
    assert ResourceScope(kind="is_type", type_name="Photo").type_name == "Photo"


def test_resource_specific_requires_pair() -> None:
    with pytest.raises(ScopeError):
        ResourceScope(kind="specific", type_name="Photo")
    assert ResourceScope(kind="specific", type_name="Photo", entity_id="p1").entity_id == "p1"


def test_resource_in_parent_requires_triple() -> None:
    with pytest.raises(ScopeError):
        ResourceScope(kind="in_parent", type_name="Photo")
    with pytest.raises(ScopeError):
        ResourceScope(kind="in_parent", type_name="Photo", parent_type="Album")
    assert (
        ResourceScope(
            kind="in_parent", type_name="Photo", parent_type="Album", parent_id="a1"
        ).parent_id
        == "a1"
    )


def test_condition_clause_rejects_empty_body() -> None:
    with pytest.raises(ScopeError):
        ConditionClause(body="   ")
