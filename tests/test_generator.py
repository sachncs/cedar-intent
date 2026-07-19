"""Tests for generators."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cedar_intent import (
    ActionScope,
    CedarSchema,
    GenerationContext,
    GeneratorError,
    LiteLLMGenerator,
    OfflineGenerator,
    PolicyIntent,
    PrincipalScope,
    Requirement,
    ResourceScope,
)
from cedar_intent.generator import DraftProposal, GenerationResult
from cedar_intent.generator.base import merge_unresolved


def make_requirement() -> Requirement:
    return Requirement(
        id="HR-042",
        text="Only admins can delete records when the request comes from the office network.",
        domain="hr",
        source_path=Path("/tmp/HR-042.md"),
        created_at=datetime.now(UTC),
    )


def make_context(schema: CedarSchema) -> GenerationContext:
    return GenerationContext(
        requirement=make_requirement(),
        schema=schema,
        principal=PrincipalScope(kind="is_type", type_name="User"),
        action=ActionScope(kind="named", name="deleteRecord"),
        resource=ResourceScope(kind="any"),
    )


def test_offline_generator_detects_permit_and_forbid(schema: CedarSchema) -> None:
    forbid_req = Requirement(
        id="HR-100",
        text="Deny deletion of records in the finance schema.",
        domain="finance",
        source_path=Path("/tmp/HR-100.md"),
        created_at=datetime.now(UTC),
    )
    forbid_context = GenerationContext(
        requirement=forbid_req,
        schema=schema,
        principal=PrincipalScope(kind="any"),
        action=ActionScope(kind="any"),
        resource=ResourceScope(kind="any"),
    )
    permit_generator = OfflineGenerator()
    forbid_generator = OfflineGenerator()
    permit_result = permit_generator.generate(make_context(schema))
    forbid_result = forbid_generator.generate(forbid_context)
    assert permit_result.proposal.intent.effect == "permit"
    assert forbid_result.proposal.intent.effect == "forbid"


def test_offline_generator_extracts_when_clause(schema: CedarSchema) -> None:
    generator = OfflineGenerator()
    result = generator.generate(make_context(schema))
    when = result.proposal.intent.when_clauses
    assert when
    # The offline generator should at minimum capture the trailing
    # condition after the word "when" in the requirement text.
    assert when[0].body.strip()
    assert "request comes from the office network" in when[0].body


def test_offline_generator_reports_unresolved_for_vague_scopes(schema: CedarSchema) -> None:
    generator = OfflineGenerator()
    context = GenerationContext(
        requirement=Requirement(
            id="HR-200",
            text="Allow access",
            domain="hr",
            source_path=Path("/tmp/HR-200.md"),
            created_at=datetime.now(UTC),
        ),
        schema=schema,
        principal=PrincipalScope(kind="any"),
        action=ActionScope(kind="any"),
        resource=ResourceScope(kind="any"),
    )
    proposal = generator.generate(context).proposal
    assert proposal.unresolved


def test_offline_generator_complete_when_scopes_are_specific(schema: CedarSchema) -> None:
    generator = OfflineGenerator()
    context = GenerationContext(
        requirement=make_requirement(),
        schema=schema,
        principal=PrincipalScope(kind="specific", type_name="User", entity_id="alice"),
        action=ActionScope(kind="named", name="view"),
        resource=ResourceScope(kind="is_type", type_name="Photo"),
    )
    proposal = generator.generate(context).proposal
    assert proposal.complete


def test_merge_unresolved_dedupes() -> None:
    assert merge_unresolved(["a", "b", "a", " c "]) == ("a", "b", "c")


def test_draft_proposal_complete_property() -> None:
    proposal = DraftProposal(
        intent=PolicyIntent(
            id="x",
            requirement_id="r",
            effect="permit",
            principal=PrincipalScope(),
            action=ActionScope(),
            resource=ResourceScope(),
        )
    )
    assert proposal.complete


def test_litellm_generator_validates_inputs() -> None:
    with pytest.raises(GeneratorError):
        LiteLLMGenerator(model="")
    with pytest.raises(GeneratorError):
        LiteLLMGenerator(model="m", timeout=0)
    with pytest.raises(GeneratorError):
        LiteLLMGenerator(model="m", max_tokens=0)
    with pytest.raises(GeneratorError):
        LiteLLMGenerator(model="m", retries=-1)


def test_litellm_generator_propagates_request_errors(schema: CedarSchema) -> None:
    generator = LiteLLMGenerator(model="provider/model")
    with patch("cedar_intent.generator.litellm.litellm.completion") as completion:
        completion.side_effect = RuntimeError("network down")
        with pytest.raises(GeneratorError):
            generator.generate(make_context(schema))


def test_litellm_generator_extracts_proposal(schema: CedarSchema) -> None:
    generator = LiteLLMGenerator(model="provider/model")
    payload = {
        "intent": {
            "effect": "permit",
            "principal": {"kind": "is_type", "type_name": "User"},
            "action": {"kind": "named", "name": "viewPhoto"},
            "resource": {"kind": "is_type", "type_name": "Photo"},
            "when": ['principal.role == "admin"'],
            "unless": [],
        },
        "unresolved": [],
    }
    response = SimpleNamespace(
        id="req-1",
        model="provider/resolved-model",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        choices=[SimpleNamespace(message=SimpleNamespace(content=_json(payload)))],
    )
    with patch("cedar_intent.generator.litellm.litellm.completion") as completion:
        completion.return_value = response
        result = generator.generate(make_context(schema))
    assert isinstance(result, GenerationResult)
    assert result.proposal.intent.effect == "permit"
    assert result.proposal.intent.action.name == "viewPhoto"
    assert result.usage["total_tokens"] == 15


def test_litellm_generator_rejects_invalid_json(schema: CedarSchema) -> None:
    generator = LiteLLMGenerator(model="provider/model")
    response = SimpleNamespace(
        id=None,
        model="provider/model",
        usage={},
        choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))],
    )
    with patch("cedar_intent.generator.litellm.litellm.completion") as completion:
        completion.return_value = response
        with pytest.raises(GeneratorError):
            generator.generate(make_context(schema))


def test_litellm_generator_rejects_missing_intent(schema: CedarSchema) -> None:
    generator = LiteLLMGenerator(model="provider/model")
    response = SimpleNamespace(
        id=None,
        model="provider/model",
        usage={},
        choices=[SimpleNamespace(message=SimpleNamespace(content=_json({"oops": True})))],
    )
    with patch("cedar_intent.generator.litellm.litellm.completion") as completion:
        completion.return_value = response
        with pytest.raises(GeneratorError):
            generator.generate(make_context(schema))


def test_litellm_generator_rejects_non_object_intent(schema: CedarSchema) -> None:
    generator = LiteLLMGenerator(model="provider/model")
    response = SimpleNamespace(
        id=None,
        model="provider/model",
        usage={},
        choices=[SimpleNamespace(message=SimpleNamespace(content=_json({"intent": "oops"})))],
    )
    with patch("cedar_intent.generator.litellm.litellm.completion") as completion:
        completion.return_value = response
        with pytest.raises(GeneratorError):
            generator.generate(make_context(schema))


def test_litellm_generator_rejects_invalid_effect(schema: CedarSchema) -> None:
    generator = LiteLLMGenerator(model="provider/model")
    payload = {
        "intent": {
            "effect": "allow",
            "principal": {"kind": "any"},
            "action": {"kind": "any"},
            "resource": {"kind": "any"},
        }
    }
    response = SimpleNamespace(
        id=None,
        model="provider/model",
        usage={},
        choices=[SimpleNamespace(message=SimpleNamespace(content=_json(payload)))],
    )
    with patch("cedar_intent.generator.litellm.litellm.completion") as completion:
        completion.return_value = response
        with pytest.raises(GeneratorError):
            generator.generate(make_context(schema))


def test_litellm_generator_handles_fallbacks(schema: CedarSchema) -> None:
    generator = LiteLLMGenerator(model="primary", fallbacks=("backup",))
    response = SimpleNamespace(
        id="req-2",
        model="backup",
        usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=_json(
                        {
                            "intent": {
                                "effect": "permit",
                                "principal": {"kind": "any"},
                                "action": {"kind": "any"},
                                "resource": {"kind": "any"},
                            },
                            "unresolved": ["x"],
                        }
                    )
                )
            )
        ],
    )
    with patch("cedar_intent.generator.litellm.litellm.completion") as completion:
        completion.return_value = response
        result = generator.generate(make_context(schema))
    assert completion.call_args.kwargs["fallbacks"] == ["backup"]
    assert not result.proposal.complete
    assert result.proposal.unresolved == ("x",)


def test_litellm_generator_handles_missing_choices(schema: CedarSchema) -> None:
    generator = LiteLLMGenerator(model="primary")
    response = SimpleNamespace(id=None, model=None, usage=None, choices=[])
    with patch("cedar_intent.generator.litellm.litellm.completion") as completion:
        completion.return_value = response
        with pytest.raises(GeneratorError):
            generator.generate(make_context(schema))


def test_litellm_generator_extracts_pydantic_usage(schema: CedarSchema) -> None:
    generator = LiteLLMGenerator(model="primary")
    usage = MagicMock()
    usage.model_dump.return_value = {"total_tokens": 42, "prompt_tokens": 7}
    response = SimpleNamespace(
        id="req-3",
        model="primary",
        usage=usage,
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=_json(
                        {
                            "intent": {
                                "effect": "permit",
                                "principal": {"kind": "any"},
                                "action": {"kind": "any"},
                                "resource": {"kind": "any"},
                            },
                            "unresolved": [],
                        }
                    )
                )
            )
        ],
    )
    with patch("cedar_intent.generator.litellm.litellm.completion") as completion:
        completion.return_value = response
        result = generator.generate(make_context(schema))
    assert result.usage == {"total_tokens": 42, "prompt_tokens": 7}


def test_litellm_generator_ignores_non_text_content(schema: CedarSchema) -> None:
    generator = LiteLLMGenerator(model="primary")
    response = SimpleNamespace(
        id=None,
        model="primary",
        usage={},
        choices=[SimpleNamespace(message=SimpleNamespace(content=None))],
    )
    with patch("cedar_intent.generator.litellm.litellm.completion") as completion:
        completion.return_value = response
        with pytest.raises(GeneratorError):
            generator.generate(make_context(schema))


def test_generator_protocol_runtime_checkable() -> None:
    assert isinstance(OfflineGenerator(), OfflineGenerator)
    offline = OfflineGenerator()
    assert hasattr(offline, "generate")


def _json(payload: dict[str, object]) -> str:
    import json

    return json.dumps(payload)
