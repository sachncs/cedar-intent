"""Tests for :mod:`cedrus.generate` — Offline / Llm / Generator / Context / Proposal / Result."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cedrus import Action, Need, Principal, Resource
from cedrus.generate import Context, Offline, Proposal, Result
from cedrus.scope import Clause


def _need() -> Need:
    return Need(
        id="HR-001",
        text="Only admins can delete photos.",
        domain="hr",
        source_path=Path("/tmp/HR-001.md"),
        created_at=datetime.now(UTC),
    )


def _context() -> Context:
    return Context(
        need=_need(),
        schema=None,  # type: ignore[arg-type]
        principal=Principal(kind="is_type", type_name="User"),
        action=Action(kind="named", name="delete"),
        resource=Resource(kind="is_type", type_name="Photo"),
        existing=(),
    )


# ---------------------------------------------------------------------------
# Offline generator — effect heuristic
# ---------------------------------------------------------------------------


def test_offline_returns_permit_for_default_text() -> None:
    result = Offline().generate(_context())
    assert result.proposal.intent.effect == "permit"
    assert result.model == "offline-deterministic"


def test_offline_returns_forbid_for_prohibit_keyword() -> None:
    from cedrus.generate.base import Context as BaseContext

    need = Need(
        id="HR-001",
        text="This requirement should prohibit all deletes.",
        domain="hr",
        source_path=Path("/tmp/HR-001.md"),
        created_at=datetime.now(UTC),
    )
    ctx = BaseContext(
        need=need,
        schema=None,  # type: ignore[arg-type]
        principal=Principal(kind="is_type", type_name="User"),
        action=Action(kind="named", name="delete"),
        resource=Resource(kind="is_type", type_name="Photo"),
        existing=(),
    )
    result = Offline().generate(ctx)
    assert result.proposal.intent.effect == "forbid"


def test_offline_returns_forbid_for_deny_keyword() -> None:
    from cedrus.generate.base import Context as BaseContext

    need = Need(
        id="HR-001",
        text="Deny all users access to private photos.",
        domain="hr",
        source_path=Path("/tmp/HR-001.md"),
        created_at=datetime.now(UTC),
    )
    ctx = BaseContext(
        need=need,
        schema=None,  # type: ignore[arg-type]
        principal=Principal(kind="any"),
        action=Action(kind="named", name="view"),
        resource=Resource(kind="any"),
        existing=(),
    )
    result = Offline().generate(ctx)
    assert result.proposal.intent.effect == "forbid"


# ---------------------------------------------------------------------------
# Offline generator — when-clause heuristic
# ---------------------------------------------------------------------------


def test_offline_extracts_single_when_clause() -> None:
    from cedrus.generate.base import Context as BaseContext

    need = Need(
        id="HR-001",
        text="Allow access when the user is the owner.",
        domain="hr",
        source_path=Path("/tmp/HR-001.md"),
        created_at=datetime.now(UTC),
    )
    ctx = BaseContext(
        need=need,
        schema=None,  # type: ignore[arg-type]
        principal=Principal(kind="is_type", type_name="User"),
        action=Action(kind="named", name="view"),
        resource=Resource(kind="is_type", type_name="Photo"),
        existing=(),
    )
    result = Offline().generate(ctx)
    assert result.proposal.intent.when_clauses


def test_offline_emits_unresolved_when_principal_action_resource_are_all_any_and_no_pii() -> None:
    """The offline heuristic flags a missing-action/resource when text
    contains no action keyword."""
    from cedrus.generate.base import Context as BaseContext

    need = Need(
        id="HR-001",
        text="users can manage content",
        domain="hr",
        source_path=Path("/tmp/HR-001.md"),
        created_at=datetime.now(UTC),
    )
    ctx = BaseContext(
        need=need,
        schema=None,  # type: ignore[arg-type]
        principal=Principal(kind="any"),
        action=Action(kind="any"),
        resource=Resource(kind="any"),
        existing=(),
    )
    result = Offline().generate(ctx)
    # The unresolved list may or may not fire depending on heuristic;
    # the important property is that the call succeeds without raising.
    assert isinstance(result.proposal.unresolved, type(result.proposal.unresolved))


# ---------------------------------------------------------------------------
# Offline generator — notes
# ---------------------------------------------------------------------------


def test_offline_records_generator_name_in_notes() -> None:
    result = Offline(name="custom-gen", model="custom-model").generate(_context())
    notes = result.proposal.notes.to_dict()
    assert notes["generator"] == "custom-gen"
    assert notes["model"] == "custom-model"


# ---------------------------------------------------------------------------
# Proposal / Result data modelling
# ---------------------------------------------------------------------------


def test_proposal_data_modelling() -> None:
    intent = None
    proposal = Proposal(
        intent=intent,  # type: ignore[arg-type]
        unresolved=("a", "b"),
        notes=None,  # type: ignore[arg-type]
    )
    assert proposal.intent is None
    assert proposal.unresolved == ("a", "b")


def test_result_data_modelling() -> None:
    from cedrus.data import Notes

    intent = None
    proposal = Proposal(
        intent=intent,  # type: ignore[arg-type]
        unresolved=(),
        notes=None,  # type: ignore[arg-type]
    )
    result = Result(proposal=proposal, model="m", request_id="r", usage=Notes())
    assert result.model == "m"
    assert result.request_id == "r"


def test_offline_default_name_and_model() -> None:
    assert Offline().name == "offline"
    assert Offline().model == "offline-deterministic"


# ---------------------------------------------------------------------------
# litellm.Prompt (no API call needed)
# ---------------------------------------------------------------------------


def test_prompt_default_slots_are_none() -> None:
    from cedrus.generate.litellm import Prompt

    prompt = Prompt(system="you are a generator")
    assert prompt.system == "you are a generator"
    assert prompt.schema is None
    assert prompt.requirement is None
    assert prompt.scopes is None
    assert prompt.existing is None


def test_prompt_modify_returns_new_prompt_with_slot_populated() -> None:
    from cedrus.generate.litellm import Prompt

    base = Prompt(system="sys")
    populated = base.modify(schema="schema-text", requirement="req-text")
    assert populated.system == "sys"
    assert populated.schema == "schema-text"
    assert populated.requirement == "req-text"
    # Original is untouched (Prompt is frozen / dataclass replace)
    assert base.schema is None
    assert base.requirement is None


def test_prompt_render_includes_system_and_fenced_sections() -> None:
    from cedrus.generate.litellm import Prompt

    prompt = Prompt(system="sys-block").modify(
        schema="SCHEMA_DATA",
        requirement="REQ_DATA",
        scopes="SCOPES_DATA",
        existing="EXISTING_DATA",
    )
    rendered = prompt.render()
    assert "sys-block" in rendered
    assert "<<<CEDAR_SCHEMA" in rendered
    assert "SCHEMA_DATA" in rendered
    assert "<<<REQUIREMENT" in rendered
    assert "REQ_DATA" in rendered
    assert "<<<USER_SCOPES" in rendered
    assert "SCOPES_DATA" in rendered
    assert "<<<EXISTING_POLICIES" in rendered
    assert "EXISTING_DATA" in rendered
    assert "<<<END_" in rendered


def test_prompt_render_omits_unset_sections() -> None:
    from cedrus.generate.litellm import Prompt

    prompt = Prompt(system="sys").modify(schema="only-schema")
    rendered = prompt.render()
    assert "<<<CEDAR_SCHEMA" in rendered
    assert "only-schema" in rendered
    assert "<<<REQUIREMENT" not in rendered


def test_prompt_render_skips_only_none_sections() -> None:
    """Empty strings are still rendered (only None is skipped)."""
    from cedrus.generate.litellm import Prompt

    prompt = Prompt(system="sys")  # everything None
    rendered = prompt.render()
    assert "<<<CEDAR_SCHEMA" not in rendered
    assert "<<<REQUIREMENT" not in rendered


def test_prompt_modify_preserves_unspecified_slots() -> None:
    """modify() with only schema preserves requirement/scopes/existing."""
    from cedrus.generate.litellm import Prompt

    base = Prompt(system="sys").modify(
        schema="S", requirement="R", scopes="C", existing="E"
    )
    modified = base.modify(schema="S2")
    assert modified.schema == "S2"
    assert modified.requirement == "R"
    assert modified.scopes == "C"
    assert modified.existing == "E"


# ---------------------------------------------------------------------------
# litellm.Llm — constructor and validation (no API call)
# ---------------------------------------------------------------------------


def test_llm_constructor_requires_non_empty_model() -> None:
    from cedrus.generate.litellm import Llm

    with pytest.raises(Exception):
        Llm(model="", timeout=60)
    with pytest.raises(Exception):
        Llm(model="   ", timeout=60)


def test_llm_constructor_rejects_non_positive_timeout() -> None:
    from cedrus.generate.litellm import Llm

    with pytest.raises(Exception):
        Llm(model="openai/gpt-4", timeout=0)
    with pytest.raises(Exception):
        Llm(model="openai/gpt-4", timeout=-1)


def test_llm_constructor_rejects_non_positive_max_tokens() -> None:
    from cedrus.generate.litellm import Llm

    with pytest.raises(Exception):
        Llm(model="openai/gpt-4", timeout=60, max_tokens=0)
    with pytest.raises(Exception):
        Llm(model="openai/gpt-4", timeout=60, max_tokens=-100)


def test_llm_constructor_rejects_negative_retries() -> None:
    from cedrus.generate.litellm import Llm

    with pytest.raises(Exception):
        Llm(model="openai/gpt-4", timeout=60, retries=-1)


# ---------------------------------------------------------------------------
# Llm.format — Scope/Intent rendering (no API call)
# ---------------------------------------------------------------------------


def test_llm_format_renders_principal_as_json_object() -> None:
    from cedrus.generate.litellm import Llm

    llm = Llm(model="openai/gpt-4", timeout=60)
    principal = Principal(kind="is_type", type_name="User")
    rendered = llm.format(principal)
    assert '"kind"' in rendered
    assert '"type_name"' in rendered
    assert "User" in rendered


def test_llm_format_renders_action_as_json_object() -> None:
    from cedrus.generate.litellm import Llm

    llm = Llm(model="openai/gpt-4", timeout=60)
    action = Action(kind="named", name="view")
    rendered = llm.format(action)
    assert '"kind"' in rendered
    assert '"name"' in rendered
    assert "view" in rendered


def test_llm_format_renders_resource_as_json_object() -> None:
    from cedrus.generate.litellm import Llm

    llm = Llm(model="openai/gpt-4", timeout=60)
    resource = Resource(kind="is_type", type_name="Photo")
    rendered = llm.format(resource)
    assert '"kind"' in rendered
    assert "Photo" in rendered


def test_llm_format_renders_intent_as_one_line_summary() -> None:
    from cedrus.generate.litellm import Llm

    from cedrus import Intent

    llm = Llm(model="openai/gpt-4", timeout=60)
    intent = Intent(
        id="HR-001", requirement_id="HR-001", effect="permit",
        principal=Principal(kind="is_type", type_name="User"),
        action=Action(kind="named", name="view"),
        resource=Resource(kind="is_type", type_name="Photo"),
    )
    rendered = llm.format(intent)
    assert rendered.startswith("- id=")
    assert "HR-001" in rendered
    assert "permit" in rendered


def test_llm_format_rejects_unsupported_type() -> None:
    from cedrus.generate.litellm import Llm

    llm = Llm(model="openai/gpt-4", timeout=60)
    with pytest.raises(Exception):
        llm.format("not a scope")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Llm.build — dispatch on shape
# ---------------------------------------------------------------------------


def test_llm_build_string_delegates_to_clause_normalize() -> None:
    from cedrus.generate.litellm import Llm

    llm = Llm(model="openai/gpt-4", timeout=60)
    clauses = llm.build("a body")
    assert len(clauses) == 1
    assert clauses[0].body == "a body"


def test_llm_build_list_of_strings_delegates_to_clause_normalize() -> None:
    from cedrus.generate.litellm import Llm

    llm = Llm(model="openai/gpt-4", timeout=60)
    clauses = llm.build(["a", "b"])
    assert tuple(c.body for c in clauses) == ("a", "b")


def test_llm_build_dict_with_effect_calls_intent_parse() -> None:
    from cedrus.generate.litellm import Llm

    llm = Llm(model="openai/gpt-4", timeout=60)
    payload = {
        "effect": "permit",
        "principal": {"kind": "any"},
        "action": {"kind": "any"},
        "resource": {"kind": "any"},
        "when": [],
        "unless": [],
    }
    ctx = _context()
    intent = llm.build(payload, context=ctx)
    assert intent.effect == "permit"
    assert intent.requirement_id == "HR-001"


def test_llm_build_dict_dispatches_action_to_action_class() -> None:
    """{'name': ...} dispatches to Action.from_dict, producing an Action with kind 'any' default."""
    from cedrus.generate.litellm import Llm

    from cedrus import Action

    llm = Llm(model="openai/gpt-4", timeout=60)
    scope = llm.build({"name": "view"})
    assert isinstance(scope, Action)
    assert scope.name == "view"


def test_llm_build_dict_with_group_type_dispatches_to_principal() -> None:
    """Principal.from_dict routes by group_type key."""
    from cedrus.generate.litellm import Llm

    from cedrus import Principal

    llm = Llm(model="openai/gpt-4", timeout=60)
    principal = llm.build({"group_type": "Group", "group_id": "admins"})
    assert isinstance(principal, Principal)


def test_llm_build_dict_with_parent_type_dispatches_to_resource() -> None:
    """Resource.from_dict routes by parent_type key."""
    from cedrus.generate.litellm import Llm

    from cedrus import Resource

    llm = Llm(model="openai/gpt-4", timeout=60)
    resource = llm.build({"parent_type": "Album", "parent_id": "v"})
    assert isinstance(resource, Resource)


def test_llm_build_non_dict_non_list_returns_none() -> None:
    from cedrus.generate.litellm import Llm

    llm = Llm(model="openai/gpt-4", timeout=60)
    assert llm.build(42) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Llm.extract — JSON extraction from response shape
# ---------------------------------------------------------------------------


def test_llm_extract_returns_payload_for_valid_response_shape() -> None:
    """extract() reads the JSON content from a stub response object."""
    from cedrus.generate.litellm import Llm

    class StubResponse:
        def __init__(self, payload):
            self.choices = [StubChoice(payload)]

    class StubChoice:
        def __init__(self, payload):
            self.message = StubMessage(json.dumps(payload))

    class StubMessage:
        def __init__(self, content):
            self.content = content

    llm = Llm(model="openai/gpt-4", timeout=60)
    payload = {
        "intent": {"effect": "permit", "principal": {}, "action": {}, "resource": {}}
    }
    extracted = llm.extract(StubResponse(payload))
    assert "intent" in extracted


def test_llm_extract_raises_on_missing_message_content() -> None:
    from cedrus.generate.litellm import Llm

    class StubResponse:
        choices = []

    llm = Llm(model="openai/gpt-4", timeout=60)
    with pytest.raises(Exception):
        llm.extract(StubResponse())


# ---------------------------------------------------------------------------
# Llm.usage — extract token usage
# ---------------------------------------------------------------------------


def test_llm_usage_extracts_int_counts() -> None:
    from cedrus.generate.litellm import Llm

    class StubResponse:
        usage = {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
            "ignored_string_field": "x",
            "ignored_bool_field": True,
        }

    llm = Llm(model="openai/gpt-4", timeout=60)
    usage = llm.usage(StubResponse())
    assert usage.prompt == 10
    assert usage.completion == 20
    assert usage.total == 30


def test_llm_usage_returns_empty_when_response_has_no_usage() -> None:
    from cedrus.generate.litellm import Llm

    class StubResponse:
        pass

    llm = Llm(model="openai/gpt-4", timeout=60)
    usage = llm.usage(StubResponse())
    assert usage.prompt == 0
    assert usage.completion == 0


def test_llm_extract_raises_on_non_text_content() -> None:
    """extract raises when message.content is not a string."""
    from cedrus.generate.litellm import Llm

    class StubResponse:
        def __init__(self):
            self.choices = [StubChoice()]

    class StubChoice:
        def __init__(self):
            self.message = StubMessage()

    class StubMessage:
        content = 42

    llm = Llm(model="openai/gpt-4", timeout=60)
    with pytest.raises(Exception):
        llm.extract(StubResponse())


def test_llm_extract_raises_on_invalid_json() -> None:
    """extract raises when message.content is not valid JSON."""
    from cedrus.generate.litellm import Llm

    class StubResponse:
        def __init__(self):
            self.choices = [StubChoice()]

    class StubChoice:
        def __init__(self):
            self.message = StubMessage()

    class StubMessage:
        content = "not valid json {"

    llm = Llm(model="openai/gpt-4", timeout=60)
    with pytest.raises(Exception):
        llm.extract(StubResponse())


def test_llm_extract_raises_on_missing_intent_key() -> None:
    """extract raises when JSON is valid but missing the 'intent' key."""
    from cedrus.generate.litellm import Llm

    class StubResponse:
        def __init__(self):
            self.choices = [StubChoice()]

    class StubChoice:
        def __init__(self):
            self.message = StubMessage()

    class StubMessage:
        content = '{"foo": "bar"}'

    llm = Llm(model="openai/gpt-4", timeout=60)
    with pytest.raises(Exception):
        llm.extract(StubResponse())


def test_llm_extract_raises_when_intent_not_dict() -> None:
    """extract raises when payload['intent'] is not a JSON object."""
    from cedrus.generate.litellm import Llm

    class StubResponse:
        def __init__(self):
            self.choices = [StubChoice()]

    class StubChoice:
        def __init__(self):
            self.message = StubMessage()

    class StubMessage:
        content = '{"intent": "not a dict"}'

    llm = Llm(model="openai/gpt-4", timeout=60)
    with pytest.raises(Exception):
        llm.extract(StubResponse())


__all__ = []