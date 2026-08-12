"""Tests for the Policy class hierarchy."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cedrus import (
    Action,
    Compiled,
    Context,
    Draft,
    Existing,
    Fault,
    Kind,
    Need,
    Principal,
    Resource,
    Result,
    Schema,
)
from cedrus.compile import Intent
from cedrus.generate import Proposal


def make_requirement(identifier: str = "HR-042") -> Need:
    return Need(
        id=identifier,
        text="Only owners can view private photos.",
        domain="hr",
        source_path=Path(f"/tmp/{identifier}.md"),
        created_at=datetime.now(UTC),
    )


def make_intent(requirement_id: str = "HR-042") -> Intent:
    return Intent(
        id=f"hr-{requirement_id.lower()}",
        requirement_id=requirement_id,
        effect="permit",
        principal=Principal(kind="is_type", type_name="User"),
        action=Action(kind="named", name="viewPhoto"),
        resource=Resource(kind="is_type", type_name="Photo"),
    )


def test_policy_kind_for_each_subclass(requirement: Need) -> None:
    draft = Draft.from_requirement(requirement)
    existing = Existing.from_requirement(
        requirement, cedar="permit (principal, action, resource);"
    )
    compiled = Compiled(id="hr", requirement=requirement, cedar="permit (...) ;")
    assert draft.kind() == "draft"
    assert existing.kind() == "existing"
    assert compiled.kind() == "compiled"


def test_existing_policy_without_intent_raises(requirement: Need) -> None:
    policy = Existing.from_requirement(
        requirement, cedar="permit (principal, action, resource);"
    )
    with pytest.raises(Fault):
        policy.to_intent()


def test_existing_policy_with_intent_returns_it(requirement: Need) -> None:
    intent = make_intent()
    policy = Existing.from_requirement(
        requirement, cedar="permit (...) ;", parsed_intent=intent
    )
    assert policy.to_intent() is intent


def test_draft_policy_without_intent_raises(requirement: Need) -> None:
    draft = Draft.from_requirement(requirement)
    with pytest.raises(Fault):
        draft.to_intent()


def test_draft_policy_with_intent_returns_it(requirement: Need) -> None:
    intent = make_intent()
    draft = Draft(
        id="hr",
        requirement=requirement,
        intent=intent,
    )
    assert draft.to_intent() is intent


def test_draft_generate_uses_supplied_scopes_and_existing(
    requirement: Need, schema: Schema
) -> None:
    draft = Draft(
        id="hr-hr-042",
        requirement=requirement,
        principal=Principal(kind="specific", type_name="User", entity_id="alice"),
        action=Action(kind="named", name="viewPhoto"),
        resource=Resource(kind="is_type", type_name="Photo"),
    )
    existing_intent = make_intent("HR-001")
    existing = Existing.from_requirement(
        requirement, cedar="permit (...) ;", parsed_intent=existing_intent
    )
    result = Proposal(intent=existing_intent, unresolved=())
    generator = SimpleNamespace(
        name="fake",
        model="fake-model",
        generate=MagicMock(
            return_value=Result(
                proposal=result,
                model="fake-model",
                request_id=None,
                usage={},
            )
        ),
    )
    proposal = draft.generate(schema, generator, existing=[existing])
    assert proposal.intent is existing_intent
    assert generator.generate.call_count == 1
    context: Context = generator.generate.call_args.args[0]
    assert context.principal.kind == "specific"
    assert context.action.name == "viewPhoto"
    assert context.resource.type_name == "Photo"
    assert context.existing == (existing_intent,)


def test_draft_apply_result_merges_notes(requirement: Need) -> None:
    from cedrus.data import Notes, Usage

    draft = Draft(
        id="hr-hr-042",
        requirement=requirement,
        notes=Notes.from_dict({"author": "alice"}),
    )
    intent = make_intent()
    result = Result(
        proposal=Proposal(
            intent=intent,
            unresolved=(),
            notes=Notes.from_dict({"generator": "fake"}),
        ),
        model="fake-model",
        request_id=None,
        usage=Usage(prompt=0, completion=0, total=0),
    )
    proposal = draft.apply_result(result)
    assert proposal.notes.to_dict() == {"author": "alice", "generator": "fake"}


def test_draft_compile_uses_intent(requirement: Need, schema: Schema) -> None:
    intent = make_intent()
    draft = Draft(id="hr", requirement=requirement, intent=intent)
    source = draft.compile(schema)
    assert "permit" in source.cedar


def test_draft_compile_falls_back_to_scopes(requirement: Need, schema: Schema) -> None:
    draft = Draft(
        id="hr",
        requirement=requirement,
        principal=Principal(kind="is_type", type_name="User"),
        action=Action(kind="named", name="viewPhoto"),
        resource=Resource(kind="is_type", type_name="Photo"),
    )
    source = draft.compile(schema)
    assert "permit" in source.cedar
    assert "principal is User" in source.cedar


def test_draft_as_compiled_populates_cedar(requirement: Need, schema: Schema) -> None:
    intent = make_intent()
    draft = Draft(id="hr", requirement=requirement, intent=intent)
    compiled = draft.as_compiled(schema)
    assert compiled.cedar
    assert "permit" in compiled.cedar


def test_draft_with_status_returns_new_instance(requirement: Need) -> None:
    draft = Draft.from_requirement(requirement)
    accepted = draft.with_status("accepted")
    assert accepted.status == "accepted"
    assert draft.status == "proposed"


def test_draft_to_dict_contains_scope_kinds(requirement: Need) -> None:
    draft = Draft.from_requirement(requirement)
    data = draft.to_dict()
    assert data["principal"] == "any"
    assert data["action"] == "any"
    assert data["resource"] == "any"
    assert data["status"] == "proposed"


def test_compiled_policy_validate(schema: Schema) -> None:
    cedar = (
        'permit (principal == PhotoFlash::User::"alice", '
        'action == PhotoFlash::Action::"viewPhoto", '
        'resource == PhotoFlash::Photo::"p1");'
    )
    compiled = Compiled(id="hr", requirement=make_requirement(), cedar=cedar)
    assert compiled.validate(schema).passed


def test_compiled_policy_without_intent_raises(requirement: Need) -> None:
    compiled = Compiled(id="hr", requirement=requirement, cedar="permit (...) ;")
    with pytest.raises(Fault):
        compiled.to_intent()


def test_compiled_policy_with_intent_returns_it(requirement: Need) -> None:
    intent = make_intent()
    compiled = Compiled(
        id="hr", requirement=requirement, cedar="permit (...) ;", intent=intent
    )
    assert compiled.to_intent() is intent


def test_compiled_policy_test_runs_scenarios(schema: Schema) -> None:
    cedar = (
        'permit (principal == PhotoFlash::User::"alice", '
        'action == PhotoFlash::Action::"viewPhoto", '
        'resource == PhotoFlash::Photo::"p1");'
    )
    compiled = Compiled(id="hr", requirement=make_requirement(), cedar=cedar)
    report = compiled.test(
        schema,
        [
            SimpleNamespace(
                name="ok",
                principal='PhotoFlash::User::"alice"',
                action='PhotoFlash::Action::"viewPhoto"',
                resource='PhotoFlash::Photo::"p1"',
                context={},
                expected="Allow",
            )
        ],
    )
    assert report.passed


def test_base_policy_requires_subclass_implementation(requirement: Need) -> None:
    class Bare(Kind):
        def kind(self) -> str:
            return "bare"

    bare = Bare(id="x", requirement=requirement)
    with pytest.raises(Fault):
        bare.to_intent()


def test_base_policy_validate_requires_cedar(requirement: Need) -> None:
    class Bare(Kind):
        def kind(self) -> str:
            return "bare"

    bare = Bare(id="x", requirement=requirement, cedar="")
    with pytest.raises(Fault):
        bare.validate(Schema.from_mapping({"Demo": {"entityTypes": {}, "actions": {}}}))


def test_policy_from_requirement_helpers(requirement: Need) -> None:
    draft = Draft.from_requirement(
        requirement,
        principal=Principal(kind="any"),
        action=Action(kind="any"),
        resource=Resource(kind="any"),
        policy_id="custom-id",
    )
    assert draft.id == "custom-id"
    existing = Existing.from_requirement(
        requirement, cedar="permit (principal, action, resource);", policy_id="existing-id"
    )
    assert existing.id == "existing-id"


def test_compiled_policy_from_intent_helper(requirement: Need) -> None:
    intent = make_intent()
    compiled = Compiled.from_intent(
        intent, "permit (principal, action, resource);", requirement, policy_id="custom"
    )
    assert compiled.id == "custom"
    assert compiled.to_intent() is intent


def test_offline_generator_fills_draft_cedar(requirement: Need, schema: Schema) -> None:
    draft = Draft(
        id="hr-hr-042",
        requirement=requirement,
        principal=Principal(kind="specific", type_name="User", entity_id="alice"),
        action=Action(kind="named", name="viewPhoto"),
        resource=Resource(kind="is_type", type_name="Photo"),
    )
    updated = draft.as_compiled(schema)
    assert "permit" in updated.cedar
