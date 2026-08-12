"""Tests for :mod:`cedrus.compile` — Intent, Source, deterministic compile."""
from __future__ import annotations

import pytest

from cedrus.compile import Intent, Source
from cedrus.error import Compile
from cedrus.scope import Action, Clause, Principal, Resource


# ---------------------------------------------------------------------------
# Intent data modelling
# ---------------------------------------------------------------------------


def _intent(**overrides) -> Intent:
    defaults = dict(
        id="hr-hr-001",
        requirement_id="hr-001",
        effect="permit",
        principal=Principal(kind="is_type", type_name="User"),
        action=Action(kind="named", name="view"),
        resource=Resource(kind="is_type", type_name="Photo"),
    )
    defaults.update(overrides)
    return Intent(**defaults)


def test_intent_rejects_invalid_effect() -> None:
    with pytest.raises(Compile):
        _intent(effect="deny")  # type: ignore[arg-type]


def test_intent_rejects_empty_id() -> None:
    with pytest.raises(Compile):
        _intent(id="")


def test_intent_rejects_whitespace_id() -> None:
    with pytest.raises(Compile):
        _intent(id="   ")


def test_intent_accepts_permit_and_forbid() -> None:
    assert _intent(effect="permit").effect == "permit"
    assert _intent(effect="forbid").effect == "forbid"


def test_intent_defaults_when_and_unless_to_empty_tuples() -> None:
    intent = _intent()
    assert intent.when_clauses == ()
    assert intent.unless_clauses == ()


def test_intent_is_frozen() -> None:
    intent = _intent()
    with pytest.raises(Exception):
        intent.effect = "forbid"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Intent.compile — Cedar rendering
# ---------------------------------------------------------------------------


def test_compile_returns_source_with_intent_id_and_cedar() -> None:
    intent = _intent()
    source = intent.compile()
    assert isinstance(source, Source)
    assert source.intent_id == "hr-hr-001"
    assert source.cedar.startswith("permit")
    assert source.cedar.endswith(";")
    assert source.compiled_at is not None


def test_compile_is_deterministic() -> None:
    intent = _intent()
    first = intent.compile().cedar
    second = intent.compile().cedar
    assert first == second


def test_compile_renders_all_three_slots() -> None:
    cedar = _intent().compile().cedar
    assert "principal is User" in cedar
    assert 'action == Action::"view"' in cedar
    assert "resource is Photo" in cedar


def test_compile_renders_forbid() -> None:
    cedar = _intent(effect="forbid").compile().cedar
    assert cedar.startswith("forbid")


def test_compile_renders_when_block_when_present() -> None:
    intent = _intent(when_clauses=(Clause(body='principal.role == "admin"'),))
    cedar = intent.compile().cedar
    assert 'when { principal.role == "admin" }' in cedar


def test_compile_renders_unless_block_when_present() -> None:
    intent = _intent(unless_clauses=(Clause(body='principal.role == "owner"'),))
    cedar = intent.compile().cedar
    assert 'unless { principal.role == "owner" }' in cedar


def test_compile_renders_multiple_when_clauses_joined_with_ampamp() -> None:
    intent = _intent(when_clauses=(
        Clause(body='principal.role == "admin"'),
        Clause(body='principal.id != User::"bob"'),
    ))
    cedar = intent.compile().cedar
    assert 'when { principal.role == "admin" && principal.id != User::"bob" }' in cedar


def test_compile_omits_when_block_when_empty() -> None:
    cedar = _intent(when_clauses=()).compile().cedar
    assert "when {" not in cedar


# ---------------------------------------------------------------------------
# Intent.to_dict / from_dict
# ---------------------------------------------------------------------------


def test_to_dict_carries_id_and_three_scopes() -> None:
    intent = _intent()
    payload = intent.to_dict()
    assert payload["id"] == "hr-hr-001"
    assert payload["requirement_id"] == "hr-001"
    assert payload["effect"] == "permit"
    assert payload["principal"]["kind"] == "is_type"
    assert payload["action"]["kind"] == "named"
    assert payload["resource"]["kind"] == "is_type"
    assert payload["when_clauses"] == []
    assert payload["unless_clauses"] == []
    assert payload["notes"] == {}


def test_to_dict_carries_notes_dict() -> None:
    intent = _intent(notes={"generator": "offline", "model": "offline-deterministic"})
    payload = intent.to_dict()
    assert payload["notes"] == {"generator": "offline", "model": "offline-deterministic"}


def test_to_dict_carries_when_and_unless_clause_bodies() -> None:
    intent = _intent(
        when_clauses=(Clause(body='principal.role == "admin"'),),
        unless_clauses=(Clause(body='principal.role == "owner"'),),
    )
    payload = intent.to_dict()
    assert payload["when_clauses"] == [{"body": 'principal.role == "admin"', "attributes": {}}]
    assert payload["unless_clauses"] == [{"body": 'principal.role == "owner"', "attributes": {}}]


def test_from_dict_round_trips() -> None:
    intent = _intent(
        when_clauses=(Clause(body='principal.role == "admin"'),),
    )
    rebuilt = Intent.from_dict(intent.to_dict())
    assert rebuilt.id == intent.id
    assert rebuilt.requirement_id == intent.requirement_id
    assert rebuilt.effect == intent.effect
    assert rebuilt.principal.kind == intent.principal.kind
    assert rebuilt.principal.type_name == intent.principal.type_name
    assert rebuilt.action.kind == intent.action.kind
    assert rebuilt.action.name == intent.action.name
    assert rebuilt.resource.kind == intent.resource.kind
    assert rebuilt.resource.type_name == intent.resource.type_name
    assert tuple(c.body for c in rebuilt.when_clauses) == tuple(
        c.body for c in intent.when_clauses
    )


def test_from_dict_accepts_legacy_when_unless_keys() -> None:
    """Legacy row shape used the bare 'when'/'unless' keys."""
    payload = {
        "id": "hr-001",
        "requirement_id": "hr-001",
        "effect": "permit",
        "principal": {"kind": "any"},
        "action": {"kind": "any"},
        "resource": {"kind": "any"},
        "when": ['principal.role == "admin"'],
        "unless": ['principal.role == "owner"'],
    }
    rebuilt = Intent.from_dict(payload)
    assert tuple(c.body for c in rebuilt.when_clauses) == ('principal.role == "admin"',)
    assert tuple(c.body for c in rebuilt.unless_clauses) == ('principal.role == "owner"',)


def test_from_dict_defaults_missing_requirement_id() -> None:
    payload = {
        "id": "hr-001",
        "effect": "permit",
        "principal": {"kind": "any"},
        "action": {"kind": "any"},
        "resource": {"kind": "any"},
    }
    rebuilt = Intent.from_dict(payload)
    assert rebuilt.id == "hr-001"
    assert rebuilt.requirement_id == ""


def test_from_dict_raises_on_non_dict() -> None:
    with pytest.raises(Compile):
        Intent.from_dict("not a dict")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Intent.parse — polymorphic LLM / SQL shape
# ---------------------------------------------------------------------------


def test_parse_llm_shape_with_effect_key() -> None:
    payload = {
        "effect": "permit",
        "principal": {"kind": "any"},
        "action": {"kind": "any"},
        "resource": {"kind": "any"},
        "when": [],
        "unless": [],
    }
    intent = Intent.parse(payload, need=None, generator_name="offline")
    assert intent.effect == "permit"
    assert intent.notes == {"generator": "offline"}


def test_parse_sql_shape_with_intent_key() -> None:
    payload = {
        "intent": {
            "id": "hr-001",
            "effect": "forbid",
            "requirement_id": "hr-001",
        },
        "principal": {"id": "p1", "kind": "any", "type_name": None, "entity_id": None, "group_type": None, "group_id": None},
        "action": {"id": "a1", "kind": "any", "name": None, "action_group": None},
        "resource": {"id": "r1", "kind": "any", "type_name": None, "entity_id": None, "parent_type": None, "parent_id": None},
        "when_clauses": [],
        "unless_clauses": [],
        "notes": [],
    }
    intent = Intent.parse(payload)
    assert intent.id == "hr-001"
    assert intent.effect == "forbid"


def test_parse_raises_on_unrecognised_shape() -> None:
    with pytest.raises(Compile):
        Intent.parse({"id": "x"})


def test_parse_raises_on_non_dict() -> None:
    with pytest.raises(Compile):
        Intent.parse(42, generator_name="offline")  # type: ignore[arg-type]


def test_parse_sql_shape_carries_note_records() -> None:
    payload = {
        "intent": {
            "id": "hr-001",
            "effect": "permit",
            "requirement_id": "hr-001",
        },
        "principal": {"id": "p1", "kind": "any", "type_name": None, "entity_id": None, "group_type": None, "group_id": None},
        "action": {"id": "a1", "kind": "any", "name": None, "action_group": None},
        "resource": {"id": "r1", "kind": "any", "type_name": None, "entity_id": None, "parent_type": None, "parent_id": None},
        "when_clauses": [],
        "unless_clauses": [],
        "notes": [{"key": "generator", "value": "offline"}],
    }
    intent = Intent.parse(payload)
    assert intent.notes == {"generator": "offline"}


# ---------------------------------------------------------------------------
# Source.to_dict
# ---------------------------------------------------------------------------


def test_source_to_dict_includes_intent_id_cedar_and_timestamp() -> None:
    intent = _intent()
    source = intent.compile()
    payload = source.to_dict()
    assert payload["intent_id"] == intent.id
    assert payload["cedar"] == source.cedar
    assert isinstance(payload["compiled_at"], str)


# ---------------------------------------------------------------------------
# Intent.to_data — multi-row SQL shape
# ---------------------------------------------------------------------------


def test_to_data_emits_intents_principals_actions_resources_keys() -> None:
    intent = _intent()
    rows = intent.to_data()
    assert "intents" in rows
    assert rows["intents"]["id"] == intent.id
    assert rows["intents"]["effect"] == "permit"
    assert "principals" in rows
    assert "actions" in rows
    assert "resources" in rows


__all__ = []