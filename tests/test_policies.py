"""Tests for the Policy class hierarchy."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cedar_intent import (
    ActionScope,
    CedarSchema,
    CompiledPolicy,
    DraftPolicy,
    ExistingPolicy,
    GenerationContext,
    GenerationResult,
    Policy,
    PolicyError,
    PrincipalScope,
    Requirement,
    ResourceScope,
)
from cedar_intent.compiler import PolicyIntent
from cedar_intent.generator import DraftProposal


def make_requirement(identifier: str = "HR-042") -> Requirement:
    return Requirement(
        id=identifier,
        text="Only owners can view private photos.",
        domain="hr",
        source_path=Path(f"/tmp/{identifier}.md"),
        created_at=datetime.now(UTC),
    )


def make_intent(requirement_id: str = "HR-042") -> PolicyIntent:
    return PolicyIntent(
        id=f"hr-{requirement_id.lower()}",
        requirement_id=requirement_id,
        effect="permit",
        principal=PrincipalScope(kind="is_type", type_name="User"),
        action=ActionScope(kind="named", name="viewPhoto"),
        resource=ResourceScope(kind="is_type", type_name="Photo"),
    )


def test_policy_kind_for_each_subclass(requirement: Requirement) -> None:
    draft = DraftPolicy.from_requirement(requirement)
    existing = ExistingPolicy.from_requirement(
        requirement, cedar="permit (principal, action, resource);"
    )
    compiled = CompiledPolicy(id="hr", requirement=requirement, cedar="permit (...) ;")
    assert draft.kind() == "draft"
    assert existing.kind() == "existing"
    assert compiled.kind() == "compiled"


def test_existing_policy_without_intent_raises(requirement: Requirement) -> None:
    policy = ExistingPolicy.from_requirement(
        requirement, cedar="permit (principal, action, resource);"
    )
    with pytest.raises(PolicyError):
        policy.to_intent()


def test_existing_policy_with_intent_returns_it(requirement: Requirement) -> None:
    intent = make_intent()
    policy = ExistingPolicy.from_requirement(
        requirement, cedar="permit (...) ;", parsed_intent=intent
    )
    assert policy.to_intent() is intent


def test_draft_policy_without_intent_raises(requirement: Requirement) -> None:
    draft = DraftPolicy.from_requirement(requirement)
    with pytest.raises(PolicyError):
        draft.to_intent()


def test_draft_policy_with_intent_returns_it(requirement: Requirement) -> None:
    intent = make_intent()
    draft = DraftPolicy(
        id="hr",
        requirement=requirement,
        intent=intent,
    )
    assert draft.to_intent() is intent


def test_draft_generate_uses_supplied_scopes_and_existing(
    requirement: Requirement, schema: CedarSchema
) -> None:
    draft = DraftPolicy(
        id="hr-hr-042",
        requirement=requirement,
        principal=PrincipalScope(kind="specific", type_name="User", entity_id="alice"),
        action=ActionScope(kind="named", name="viewPhoto"),
        resource=ResourceScope(kind="is_type", type_name="Photo"),
    )
    existing_intent = make_intent("HR-001")
    existing = ExistingPolicy.from_requirement(
        requirement, cedar="permit (...) ;", parsed_intent=existing_intent
    )
    result = DraftProposal(intent=existing_intent, unresolved=())
    generator = SimpleNamespace(
        name="fake",
        model="fake-model",
        generate=MagicMock(
            return_value=GenerationResult(
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
    context: GenerationContext = generator.generate.call_args.args[0]
    assert context.principal.kind == "specific"
    assert context.action.name == "viewPhoto"
    assert context.resource.type_name == "Photo"
    assert context.existing == (existing_intent,)


def test_draft_apply_result_merges_notes(requirement: Requirement) -> None:
    draft = DraftPolicy(
        id="hr-hr-042",
        requirement=requirement,
        notes={"author": "alice"},
    )
    intent = make_intent()
    result = GenerationResult(
        proposal=DraftProposal(intent=intent, unresolved=(), notes={"generator": "fake"}),
        model="fake-model",
        request_id=None,
        usage={},
    )
    proposal = draft.apply_result(result)
    assert proposal.notes == {"author": "alice", "generator": "fake"}


def test_draft_compile_uses_intent(requirement: Requirement, schema: CedarSchema) -> None:
    intent = make_intent()
    draft = DraftPolicy(id="hr", requirement=requirement, intent=intent)
    source = draft.compile(schema)
    assert "permit" in source.cedar


def test_draft_compile_falls_back_to_scopes(requirement: Requirement, schema: CedarSchema) -> None:
    draft = DraftPolicy(
        id="hr",
        requirement=requirement,
        principal=PrincipalScope(kind="is_type", type_name="User"),
        action=ActionScope(kind="named", name="viewPhoto"),
        resource=ResourceScope(kind="is_type", type_name="Photo"),
    )
    source = draft.compile(schema)
    assert "permit" in source.cedar
    assert "principal is User" in source.cedar


def test_draft_as_compiled_populates_cedar(requirement: Requirement, schema: CedarSchema) -> None:
    intent = make_intent()
    draft = DraftPolicy(id="hr", requirement=requirement, intent=intent)
    compiled = draft.as_compiled(schema)
    assert compiled.cedar
    assert "permit" in compiled.cedar


def test_draft_with_status_returns_new_instance(requirement: Requirement) -> None:
    draft = DraftPolicy.from_requirement(requirement)
    accepted = draft.with_status("accepted")
    assert accepted.status == "accepted"
    assert draft.status == "proposed"


def test_draft_to_dict_contains_scope_kinds(requirement: Requirement) -> None:
    draft = DraftPolicy.from_requirement(requirement)
    data = draft.to_dict()
    assert data["principal"] == "any"
    assert data["action"] == "any"
    assert data["resource"] == "any"
    assert data["status"] == "proposed"


def test_compiled_policy_validate(schema: CedarSchema) -> None:
    cedar = (
        'permit (principal == PhotoFlash::User::"alice", '
        'action == PhotoFlash::Action::"viewPhoto", '
        'resource == PhotoFlash::Photo::"p1");'
    )
    compiled = CompiledPolicy(id="hr", requirement=make_requirement(), cedar=cedar)
    assert compiled.validate(schema).passed


def test_compiled_policy_without_intent_raises(requirement: Requirement) -> None:
    compiled = CompiledPolicy(id="hr", requirement=requirement, cedar="permit (...) ;")
    with pytest.raises(PolicyError):
        compiled.to_intent()


def test_compiled_policy_with_intent_returns_it(requirement: Requirement) -> None:
    intent = make_intent()
    compiled = CompiledPolicy(
        id="hr", requirement=requirement, cedar="permit (...) ;", intent=intent
    )
    assert compiled.to_intent() is intent


def test_compiled_policy_test_runs_scenarios(schema: CedarSchema) -> None:
    cedar = (
        'permit (principal == PhotoFlash::User::"alice", '
        'action == PhotoFlash::Action::"viewPhoto", '
        'resource == PhotoFlash::Photo::"p1");'
    )
    compiled = CompiledPolicy(id="hr", requirement=make_requirement(), cedar=cedar)
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


def test_base_policy_requires_subclass_implementation(requirement: Requirement) -> None:
    class Bare(Policy):
        def kind(self) -> str:
            return "bare"

    bare = Bare(id="x", requirement=requirement)
    with pytest.raises(PolicyError):
        bare.to_intent()


def test_base_policy_validate_requires_cedar(requirement: Requirement) -> None:
    class Bare(Policy):
        def kind(self) -> str:
            return "bare"

    bare = Bare(id="x", requirement=requirement, cedar="")
    with pytest.raises(PolicyError):
        bare.validate(CedarSchema.from_mapping({"Demo": {"entityTypes": {}, "actions": {}}}))


def test_policy_from_requirement_helpers(requirement: Requirement) -> None:
    draft = DraftPolicy.from_requirement(
        requirement,
        principal=PrincipalScope(kind="any"),
        action=ActionScope(kind="any"),
        resource=ResourceScope(kind="any"),
        policy_id="custom-id",
    )
    assert draft.id == "custom-id"
    existing = ExistingPolicy.from_requirement(
        requirement, cedar="permit (principal, action, resource);", policy_id="existing-id"
    )
    assert existing.id == "existing-id"


def test_compiled_policy_from_intent_helper(requirement: Requirement) -> None:
    intent = make_intent()
    compiled = CompiledPolicy.from_intent(
        intent, "permit (principal, action, resource);", requirement, policy_id="custom"
    )
    assert compiled.id == "custom"
    assert compiled.to_intent() is intent


def test_offline_generator_fills_draft_cedar(requirement: Requirement, schema: CedarSchema) -> None:
    draft = DraftPolicy(
        id="hr-hr-042",
        requirement=requirement,
        principal=PrincipalScope(kind="specific", type_name="User", entity_id="alice"),
        action=ActionScope(kind="named", name="viewPhoto"),
        resource=ResourceScope(kind="is_type", type_name="Photo"),
    )
    updated = draft.as_compiled(schema)
    assert "permit" in updated.cedar
