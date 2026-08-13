"""Tests for :mod:`cedrus.compile` — Intent, Source, deterministic compile.

Covers data modelling (constructor validation, frozen semantics, kind
constants), behaviour modelling (compile determinism, every slot
rendering, when/unless block assembly), JSON round-trip
(to_dict / from_dict / parse_llm_shape / parse_sql_shape with
both legacy 'when'/'unless' and canonical 'when_clauses'/'unless_clauses'
shapes), and ugly paths (non-dict input, unknown shape, empty
clauses, missing requirement_id).
"""
from __future__ import annotations

from typing import cast

import pytest

from cedrus.compile import Intent, Source
from cedrus.error import Compile
from cedrus.scope import Action, Clause, Principal, Resource


# ---------------------------------------------------------------------------
# Intent data modelling
# ---------------------------------------------------------------------------


def make_intent(**overrides) -> Intent:
    """Build an Intent, with overrides applied on top of sensible defaults.

    Uses Intent(...) directly with the right typed kwargs (rather
    than a dict-spread) so mypy can verify the call against
    Intent's typed signature.
    """
    kwargs: dict = {
        "id": "hr-hr-001",
        "requirement_id": "hr-001",
        "effect": "permit",
        "principal": Principal(kind="is_type", type_name="User"),
        "action": Action(kind="named", name="view"),
        "resource": Resource(kind="is_type", type_name="Photo"),
    }
    kwargs.update(overrides)
    if "effect" in overrides:
        from cedrus.compile import Effect
        kwargs["effect"] = cast(Effect, kwargs["effect"])
    if "principal" in overrides:
        kwargs["principal"] = cast(Principal, kwargs["principal"])
    if "action" in overrides:
        kwargs["action"] = cast(Action, kwargs["action"])
    if "resource" in overrides:
        kwargs["resource"] = cast(Resource, kwargs["resource"])
    return Intent(**kwargs)


def test_intent_rejects_invalid_effect() -> None:
    from typing import cast

    from cedrus.compile import Effect

    with pytest.raises(Compile):
        make_intent(effect=cast(Effect, "deny"))


def test_intent_rejects_empty_id() -> None:
    with pytest.raises(Compile):
        make_intent(id="")


def test_intent_rejects_whitespace_id() -> None:
    with pytest.raises(Compile):
        make_intent(id="   ")


def test_intent_accepts_permit_and_forbid() -> None:
    assert make_intent(effect="permit").effect == "permit"
    assert make_intent(effect="forbid").effect == "forbid"


def test_intent_defaults_when_and_unless_to_empty_tuples() -> None:
    intent = make_intent()
    assert intent.when_clauses == ()
    assert intent.unless_clauses == ()


def test_intent_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    intent = make_intent()
    with pytest.raises(FrozenInstanceError):
        # Plain setattr triggers the frozen __setattr__ guard.
        # The mypy type checker considers the field read-only, so
        # we use a try/except at the attribute level that mypy
        # doesn't flag because it sees a runtime expression.
        setattr(intent, "effect", "forbid")


# ---------------------------------------------------------------------------
# Intent.compile — Cedar rendering
# ---------------------------------------------------------------------------


def test_compile_returns_source_with_intent_id_and_cedar() -> None:
    intent = make_intent()
    source = intent.compile()
    assert isinstance(source, Source)
    assert source.intent_id == "hr-hr-001"
    assert source.cedar.startswith("permit")
    assert source.cedar.endswith(";")
    assert source.compiled_at is not None


def test_compile_is_deterministic() -> None:
    intent = make_intent()
    first = intent.compile().cedar
    second = intent.compile().cedar
    assert first == second


def test_compile_renders_all_three_slots() -> None:
    cedar = make_intent().compile().cedar
    assert "principal is User" in cedar
    assert 'action == Action::"view"' in cedar
    assert "resource is Photo" in cedar


def test_compile_renders_forbid() -> None:
    cedar = make_intent(effect="forbid").compile().cedar
    assert cedar.startswith("forbid")


def test_compile_renders_when_block_when_present() -> None:
    intent = make_intent(when_clauses=(Clause(body='principal.role == "admin"'),))
    cedar = intent.compile().cedar
    assert 'when { principal.role == "admin" }' in cedar


def test_compile_renders_unless_block_when_present() -> None:
    intent = make_intent(unless_clauses=(Clause(body='principal.role == "owner"'),))
    cedar = intent.compile().cedar
    assert 'unless { principal.role == "owner" }' in cedar


def test_compile_renders_multiple_when_clauses_joined_with_ampamp() -> None:
    intent = make_intent(when_clauses=(
        Clause(body='principal.role == "admin"'),
        Clause(body='principal.id != User::"bob"'),
    ))
    cedar = intent.compile().cedar
    assert 'when { principal.role == "admin" && principal.id != User::"bob" }' in cedar


def test_compile_omits_when_block_when_empty() -> None:
    cedar = make_intent(when_clauses=()).compile().cedar
    assert "when {" not in cedar


# ---------------------------------------------------------------------------
# Intent.to_dict / from_dict
# ---------------------------------------------------------------------------


def test_to_dict_carries_id_and_three_scopes() -> None:
    intent = make_intent()
    payload = intent.to_dict()
    principal_dict = cast(dict, payload["principal"])
    action_dict = cast(dict, payload["action"])
    resource_dict = cast(dict, payload["resource"])
    assert payload["id"] == "hr-hr-001"
    assert payload["requirement_id"] == "hr-001"
    assert payload["effect"] == "permit"
    assert principal_dict["kind"] == "is_type"
    assert action_dict["kind"] == "named"
    assert resource_dict["kind"] == "is_type"
    assert payload["when_clauses"] == []
    assert payload["unless_clauses"] == []
    assert payload["notes"] == {}


def test_to_dict_carries_notes_dict() -> None:
    intent = make_intent(notes={"generator": "offline", "model": "offline-deterministic"})
    payload = intent.to_dict()
    assert payload["notes"] == {"generator": "offline", "model": "offline-deterministic"}


def test_to_dict_carries_when_and_unless_clause_bodies() -> None:
    intent = make_intent(
        when_clauses=(Clause(body='principal.role == "admin"'),),
        unless_clauses=(Clause(body='principal.role == "owner"'),),
    )
    payload = intent.to_dict()
    assert payload["when_clauses"] == [{"body": 'principal.role == "admin"', "attributes": {}}]
    assert payload["unless_clauses"] == [{"body": 'principal.role == "owner"', "attributes": {}}]


def test_from_dict_round_trips() -> None:
    intent = make_intent(
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
    from typing import cast

    with pytest.raises(Compile):
        Intent.from_dict(cast(dict, "not a dict"))


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
        "id": "hr-001",
        "effect": "forbid",
        "requirement_id": "hr-001",
        "principals": {"id": "p1", "kind": "any", "type_name": None, "entity_id": None, "group_type": None, "group_id": None},
        "actions": {"id": "a1", "kind": "any", "name": None, "action_group": None},
        "resources": {"id": "r1", "kind": "any", "type_name": None, "entity_id": None, "parent_type": None, "parent_id": None},
        "when_clauses": [],
        "unless_clauses": [],
        "notes": [],
    }
    intent = Intent.parse_sql_shape(payload)
    assert intent.id == "hr-001"
    assert intent.effect == "forbid"


def test_parse_raises_on_unrecognised_shape() -> None:
    with pytest.raises(Compile):
        Intent.parse({"id": "x"})


def test_parse_raises_on_non_dict() -> None:
    from typing import cast

    with pytest.raises(Compile):
        Intent.parse(cast(dict, 42), generator_name="offline")


def test_parse_sql_shape_carries_note_records() -> None:
    payload = {
        "id": "hr-001",
        "effect": "permit",
        "requirement_id": "hr-001",
        "principals": {"id": "p1", "kind": "any", "type_name": None, "entity_id": None, "group_type": None, "group_id": None},
        "actions": {"id": "a1", "kind": "any", "name": None, "action_group": None},
        "resources": {"id": "r1", "kind": "any", "type_name": None, "entity_id": None, "parent_type": None, "parent_id": None},
        "when_clauses": [],
        "unless_clauses": [],
        "notes": [{"key": "generator", "value": "offline"}],
    }
    intent = Intent.parse_sql_shape(payload)
    assert intent.notes == {"generator": "offline"}


# ---------------------------------------------------------------------------
# Source.to_dict
# ---------------------------------------------------------------------------


def test_source_to_dict_includes_intent_id_cedar_and_timestamp() -> None:
    intent = make_intent()
    source = intent.compile()
    payload = source.to_dict()
    assert payload["intent_id"] == intent.id
    assert payload["cedar"] == source.cedar
    assert isinstance(payload["compiled_at"], str)


# ---------------------------------------------------------------------------
# Intent.to_data — multi-row SQL shape
# ---------------------------------------------------------------------------


def test_to_data_emits_intents_principals_actions_resources_keys() -> None:
    intent = make_intent()
    rows = intent.to_data()
    assert "intents" in rows
    assert rows["intents"]["id"] == intent.id
    assert rows["intents"]["effect"] == "permit"
    assert "principals" in rows
    assert "actions" in rows
    assert "resources" in rows


def test_to_data_includes_when_unless_clause_rows() -> None:
    intent = make_intent(
        when_clauses=(Clause(body='principal.role == "admin"'),),
        unless_clauses=(Clause(body='principal.role == "owner"'),),
    )
    rows = intent.to_data()
    assert len(rows["when_clause_rows"]) == 1
    assert len(rows["unless_clause_rows"]) == 1


def test_to_data_includes_intent_notes_rows() -> None:
    intent = make_intent(notes={"generator": "offline", "model": "m"})
    rows = intent.to_data()
    assert len(rows["intent_notes"]) == 2
    keys = {row["key"] for row in rows["intent_notes"]}
    assert keys == {"generator", "model"}


# ---------------------------------------------------------------------------
# Intent.parse_llm_shape with need parameter
# ---------------------------------------------------------------------------


def test_parse_llm_shape_with_need_uses_need_domain_in_id() -> None:
    from cedrus.need import Need
    from datetime import UTC, datetime
    from pathlib import Path

    need = Need(
        id="HR-042",
        text="body",
        domain="hr",
        source_path=Path("/tmp/x.md"),
        created_at=datetime.now(UTC),
    )
    payload = {
        "effect": "permit",
        "principal": {"kind": "any"},
        "action": {"kind": "any"},
        "resource": {"kind": "any"},
        "when": [],
        "unless": [],
    }
    intent = Intent.parse(payload, need=need, generator_name="offline")
    assert intent.id == "hr-hr-042"
    assert intent.requirement_id == "HR-042"


# ---------------------------------------------------------------------------
# Intent.from_dict with empty clauses
# ---------------------------------------------------------------------------


def test_from_dict_with_empty_when_clauses() -> None:
    payload = {
        "id": "hr-001",
        "requirement_id": "hr-001",
        "effect": "permit",
        "principal": {"kind": "any"},
        "action": {"kind": "any"},
        "resource": {"kind": "any"},
        "when": [],
        "unless": [],
    }
    rebuilt = Intent.from_dict(payload)
    assert rebuilt.when_clauses == ()
    assert rebuilt.unless_clauses == ()


__all__ = []