"""Tests for scope and condition classes."""

from __future__ import annotations

import pytest

from cedrus import Action, Clause, Principal, Resource
from cedrus.error import ScopeFault


def test_principal_any_passes() -> None:
    scope = Principal(kind="any")
    assert scope.kind == "any"


def test_principal_type_requires_type_name() -> None:
    with pytest.raises(ScopeFault):
        Principal(kind="type")


def test_principal_specific_requires_type_and_entity() -> None:
    with pytest.raises(ScopeFault):
        Principal(kind="specific", type_name="User")
    with pytest.raises(ScopeFault):
        Principal(kind="specific", entity_id="alice")


def test_principal_in_group_requires_group_fields() -> None:
    with pytest.raises(ScopeFault):
        Principal(kind="in_group", group_type="Group")
    Principal(kind="in_group", group_type="Group", group_id="admins")  # ok


def test_action_any_and_named() -> None:
    assert Action().kind == "any"
    with pytest.raises(ScopeFault):
        Action(kind="named")
    assert Action(kind="named", name="view").name == "view"


def test_action_in_group_requires_group() -> None:
    with pytest.raises(ScopeFault):
        Action(kind="in_group")
    assert Action(kind="in_group", group="admin").group == "admin"


def test_resource_any_passes() -> None:
    assert Resource().kind == "any"


def test_resource_type_variants() -> None:
    with pytest.raises(ScopeFault):
        Resource(kind="type")
    with pytest.raises(ScopeFault):
        Resource(kind="is_type")
    assert Resource(kind="is_type", type_name="Photo").type_name == "Photo"


def test_resource_specific_requires_pair() -> None:
    with pytest.raises(ScopeFault):
        Resource(kind="specific", type_name="Photo")
    assert Resource(kind="specific", type_name="Photo", entity_id="p1").entity_id == "p1"


def test_resource_in_parent_requires_triple() -> None:
    with pytest.raises(ScopeFault):
        Resource(kind="in_parent", type_name="Photo")
    with pytest.raises(ScopeFault):
        Resource(kind="in_parent", type_name="Photo", parent_type="Album")
    assert (
        Resource(
            kind="in_parent", type_name="Photo", parent_type="Album", parent_id="a1"
        ).parent_id
        == "a1"
    )


def test_condition_clause_rejects_empty_body() -> None:
    with pytest.raises(ScopeFault):
        Clause(body="   ")
