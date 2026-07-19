"""Tests for the deterministic compiler."""

from __future__ import annotations

import pytest

from cedar_intent import (
    ActionScope,
    CompilationError,
    ConditionClause,
    PolicyIntent,
    PrincipalScope,
    ResourceScope,
    compile_intent,
)
from cedar_intent.compiler import render_action, render_principal, render_resource


def make_intent(**overrides: object) -> PolicyIntent:
    intent = PolicyIntent(
        id="hr-hr-042",
        requirement_id="HR-042",
        effect="permit",
        principal=PrincipalScope(kind="any"),
        action=ActionScope(kind="any"),
        resource=ResourceScope(kind="any"),
        **overrides,  # type: ignore[arg-type]
    )
    return intent


def test_compile_intent_emits_basic_policy() -> None:
    source = compile_intent(make_intent())
    assert "permit (" in source.cedar
    assert "    principal," in source.cedar
    assert "    action," in source.cedar
    assert "    resource" in source.cedar
    assert source.cedar.rstrip().endswith(";")


def test_compile_intent_includes_when_and_unless_clauses() -> None:
    intent = make_intent(
        when_clauses=(ConditionClause(body="principal.role == \"admin\""),),
        unless_clauses=(ConditionClause(body="resource.private"),),
    )
    source = compile_intent(intent)
    assert 'when { principal.role == "admin" }' in source.cedar
    assert "unless { resource.private }" in source.cedar


def test_compile_intent_rejects_invalid_effect() -> None:
    with pytest.raises(CompilationError):
        PolicyIntent(
            id="x",
            requirement_id="r",
            effect="allow",  # type: ignore[arg-type]
            principal=PrincipalScope(),
            action=ActionScope(),
            resource=ResourceScope(),
        )


def test_compile_intent_requires_id() -> None:
    with pytest.raises(CompilationError):
        PolicyIntent(
            id="   ",
            requirement_id="r",
            effect="permit",
            principal=PrincipalScope(),
            action=ActionScope(),
            resource=ResourceScope(),
        )


def test_render_principal_variants() -> None:
    assert render_principal(PrincipalScope(kind="any")) == "principal"
    assert (
        render_principal(PrincipalScope(kind="type", type_name="User", entity_id="alice"))
        == 'principal == User::"alice"'
    )
    assert render_principal(PrincipalScope(kind="is_type", type_name="User")) == "principal is User"
    assert (
        render_principal(
            PrincipalScope(
                kind="specific", type_name="User", entity_id='evil"id'
            )
        )
        == 'principal == User::"evil\\"id"'
    )
    assert (
        render_principal(
            PrincipalScope(kind="in_group", group_type="Group", group_id="admins")
        )
        == 'principal in Group::"admins"'
    )


def test_render_principal_unsupported_kind() -> None:
    from dataclasses import replace

    scope = PrincipalScope(kind="any")
    bogus = replace(scope, kind="weird")  # type: ignore[arg-type]
    with pytest.raises(CompilationError):
        render_principal(bogus)


def test_render_action_variants() -> None:
    assert render_action(ActionScope(kind="any")) == "action"
    assert render_action(ActionScope(kind="named", name="view")) == 'action == Action::"view"'
    assert (
        render_action(ActionScope(kind="in_group", group="admin"))
        == 'action in Action::"admin"'
    )


def test_render_resource_variants() -> None:
    assert render_resource(ResourceScope(kind="any")) == "resource"
    assert (
        render_resource(ResourceScope(kind="type", type_name="Photo", entity_id="p1"))
        == 'resource == Photo::"p1"'
    )
    assert render_resource(ResourceScope(kind="is_type", type_name="Photo")) == "resource is Photo"
    assert (
        render_resource(
            ResourceScope(
                kind="in_parent",
                type_name="Photo",
                parent_type="Album",
                parent_id="a1",
            )
        )
        == 'resource is Photo in Album::"a1"'
    )


def test_compile_intent_serialises_to_dict() -> None:
    source = compile_intent(make_intent())
    payload = source.to_dict()
    assert payload["intent_id"] == "hr-hr-042"
    assert payload["cedar"].endswith(";")
