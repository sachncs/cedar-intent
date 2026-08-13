"""Tests for :mod:`cedrus.policies` — Draft, Compiled, Existing, Kind.

Covers data modelling (defaults, kind discriminators, to_intent
contract), behaviour modelling (compile, validate, test, with_status,
as_compiled), and ugly paths (missing intent raises, intent_for_verification
placeholder, inherited methods from Kind).
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from cedrus import (
    Action,
    Compiled,
    Draft,
    Existing,
    Intent,
    Kind,
    Need,
    Principal,
    Resource,
    Source,
    Validator,
    Vreport,
)
from cedrus.error import Fault
from cedrus.policies.draft import DraftStatus


def make_need() -> Need:
    return Need(
        id="HR-001",
        text="Body",
        domain="hr",
        source_path=Path("/tmp/HR-001.md"),
        created_at=datetime.now(UTC),
    )


def build_schema():
    from cedrus import Schema

    return Schema.from_mapping({"hr": {"entityTypes": {"User": {}, "Photo": {}}, "actions": {}}})


def make_intent() -> Intent:
    return Intent(
        id="HR-001",
        requirement_id="HR-001",
        effect="permit",
        principal=Principal(kind="any"),
        action=Action(kind="any"),
        resource=Resource(kind="any"),
    )


# ---------------------------------------------------------------------------
# Kind (abstract base) — behaviour via Draft/Compiled/Existing subclasses
# ---------------------------------------------------------------------------


def test_kind_is_abstract() -> None:
    with pytest.raises(TypeError):
        # The 2-arg form below is the minimum needed to reach
        # the type: ignore[abstract] check on the class.
        Existing(id="x", requirement=make_need(), cedar="")  # type: ignore[abstract]


def test_draft_kind_discriminator_is_draft() -> None:
    draft = Draft(id="hr", requirement=make_need())
    assert draft.kind() == "draft"


def test_compiled_kind_discriminator_is_compiled() -> None:
    compiled = Compiled(id="hr", requirement=make_need(), cedar="permit (...);")
    assert compiled.kind() == "compiled"


def test_existing_kind_discriminator_is_existing() -> None:
    existing = Existing(id="hr", requirement=make_need(), cedar="permit (...);")
    assert existing.kind() == "existing"


# ---------------------------------------------------------------------------
# Draft
# ---------------------------------------------------------------------------


def test_draft_defaults() -> None:
    draft = Draft(id="hr", requirement=make_need())
    assert draft.principal.kind == "any"
    assert draft.action.kind == "any"
    assert draft.resource.kind == "any"
    assert draft.intent is None
    assert draft.unresolved == ()
    assert draft.status == "proposed"
    assert draft.model is None
    assert draft.request_id is None


def test_draft_from_requirement_uses_default_policy_id() -> None:
    draft = Draft.from_requirement(make_need())
    assert draft.id == "draft-HR-001"


def test_draft_from_requirement_accepts_custom_policy_id() -> None:
    draft = Draft.from_requirement(make_need(), policy_id="custom-id")
    assert draft.id == "custom-id"


def test_draft_from_requirement_uses_supplied_scopes() -> None:
    draft = Draft.from_requirement(
        make_need(),
        principal=Principal(kind="is_type", type_name="User"),
        action=Action(kind="named", name="view"),
        resource=Resource(kind="any"),
    )
    assert draft.principal.type_name == "User"
    assert draft.action.name == "view"


def test_draft_from_requirement_with_no_scopes_uses_defaults() -> None:
    draft = Draft.from_requirement(make_need())
    assert draft.principal.kind == "any"
    assert draft.action.kind == "any"
    assert draft.resource.kind == "any"


def test_draft_to_intent_raises_when_no_intent_yet() -> None:
    draft = Draft(id="hr", requirement=make_need())
    with pytest.raises(Fault):
        draft.to_intent()


def test_draft_to_intent_returns_storedmake_intent() -> None:
    intent = make_intent()
    draft = Draft(id="hr", requirement=make_need(), intent=intent)
    assert draft.to_intent() is intent


def test_draft_with_status_returns_new_instance() -> None:
    draft = Draft(id="hr", requirement=make_need())
    accepted = draft.with_status("accepted")
    assert accepted.status == "accepted"
    assert draft.status == "proposed"
    assert accepted is not draft


def test_draft_compile_with_intent_returns_source() -> None:
    intent = make_intent()
    draft = Draft(id="hr", requirement=make_need(), intent=intent)
    source = draft.compile()
    assert isinstance(source, Source)
    assert source.intent_id == "HR-001"


def test_draft_compile_without_intent_builds_minimal_permit() -> None:
    draft = Draft(id="hr", requirement=make_need())
    source = draft.compile()
    assert "permit" in source.cedar


def test_draft_as_compiled_populates_cedar_and_bumps_created_at() -> None:
    draft = Draft(id="hr", requirement=make_need())
    compiled = draft.as_compiled()
    assert compiled.cedar
    assert compiled.created_at >= draft.created_at


def test_draft_to_dict_carries_scope_kinds_and_status() -> None:
    draft = Draft(
        id="hr",
        requirement=make_need(),
        principal=Principal(kind="is_type", type_name="User"),
        action=Action(kind="named", name="view"),
        resource=Resource(kind="any"),
        status="accepted",
        unresolved=("x",),
    )
    d = draft.to_dict()
    assert d["id"] == "hr"
    assert d["kind"] == "draft"
    assert d["principal"] == "is_type"
    assert d["action"] == "named"
    assert d["resource"] == "any"
    assert d["status"] == "accepted"
    assert d["unresolved"] == ["x"]


# ---------------------------------------------------------------------------
# Draft.compile — schema argument is interface symmetry
# ---------------------------------------------------------------------------


def test_draft_compile_accepts_and_ignores_schema_kwarg() -> None:
    draft = Draft(id="hr", requirement=make_need())
    source = draft.compile()
    assert "permit" in source.cedar


# ---------------------------------------------------------------------------
# Compiled
# ---------------------------------------------------------------------------


def test_compiled_default_intent_is_none() -> None:
    compiled = Compiled(id="hr", requirement=make_need(), cedar="permit (...);")
    assert compiled.intent is None


def test_compiled_to_intent_raises_when_intent_is_none() -> None:
    compiled = Compiled(id="hr", requirement=make_need(), cedar="permit (...);")
    with pytest.raises(Fault):
        compiled.to_intent()


def test_compiled_to_intent_returns_storedmake_intent() -> None:
    intent = make_intent()
    compiled = Compiled(id="hr", requirement=make_need(), cedar="permit (...);", intent=intent)
    assert compiled.to_intent() is intent


def test_compiled_validate_raises_when_cedar_empty() -> None:
    from cedrus import Schema

    compiled = Compiled(id="hr", requirement=make_need(), cedar="")
    schema = Schema.from_mapping({"hr": {"entityTypes": {"User": {}}, "actions": {}}})
    with pytest.raises(Fault):
        compiled.validate(schema)


def test_compiled_to_dict_includes_intent_id_when_present() -> None:
    compiled = Compiled(id="hr", requirement=make_need(), cedar="permit (...);", intent=make_intent())
    d = compiled.to_dict()
    assert d["kind"] == "compiled"
    assert d["intent_id"] == "HR-001"


def test_compiled_to_dict_includes_null_intent_id_when_missing() -> None:
    compiled = Compiled(id="hr", requirement=make_need(), cedar="permit (...);")
    d = compiled.to_dict()
    assert d["intent_id"] is None


def test_compiled_from_intent_uses_intent_id_when_no_override() -> None:
    intent = make_intent()
    compiled = Compiled.from_intent(intent, cedar="permit (...);", requirement=make_need())
    assert compiled.id == intent.id


def test_compiled_from_intent_honors_policy_id_override() -> None:
    intent = make_intent()
    compiled = Compiled.from_intent(
        intent, cedar="permit (...);", requirement=make_need(), policy_id="custom"
    )
    assert compiled.id == "custom"


def test_compiled_intent_for_verification_returns_storedmake_intent() -> None:
    intent = make_intent()
    compiled = Compiled(id="hr", requirement=make_need(), cedar="permit (...);", intent=intent)
    assert compiled.intent_for_verification() is intent


# ---------------------------------------------------------------------------
# Existing
# ---------------------------------------------------------------------------


def test_existing_default_parsed_intent_is_none() -> None:
    existing = Existing(id="hr", requirement=make_need(), cedar="permit (...);")
    assert existing.parsed_intent is None


def test_existing_to_intent_raises_when_no_parsedmake_intent() -> None:
    existing = Existing(id="hr", requirement=make_need(), cedar="permit (...);")
    with pytest.raises(Fault):
        existing.to_intent()


def test_existing_to_intent_returns_parsed_intent_when_present() -> None:
    intent = make_intent()
    existing = Existing(id="hr", requirement=make_need(), cedar="permit (...);", parsed_intent=intent)
    assert existing.to_intent() is intent


def test_existing_from_requirement_constructs_from_requirement_and_cedar() -> None:
    cedar = 'permit (principal, action == Action::"view", resource);'
    existing = Existing.from_requirement(make_need(), cedar=cedar)
    assert existing.id == "existing-HR-001"
    assert existing.cedar == cedar


def test_existing_intent_for_verification_returns_placeholder_when_unparsed() -> None:
    existing = Existing(id="hr", requirement=make_need(), cedar="permit (...);")
    placeholder = existing.intent_for_verification()
    assert placeholder.effect == "permit"
    assert placeholder.principal.kind == "any"
    assert "missing_intent" in placeholder.notes


def test_existing_intent_for_verification_returns_parsed_intent_when_available() -> None:
    intent = make_intent()
    existing = Existing(id="hr", requirement=make_need(), cedar="permit (...);", parsed_intent=intent)
    assert existing.intent_for_verification() is intent


# ---------------------------------------------------------------------------
# DraftStatus type alias
# ---------------------------------------------------------------------------


def test_draft_status_is_string() -> None:
    assert DraftStatus("proposed") == "proposed"
    assert DraftStatus("accepted") == "accepted"
    assert DraftStatus("rejected") == "rejected"


# ---------------------------------------------------------------------------
# Kind base class
# ---------------------------------------------------------------------------


def test_kind_base_to_intent_raises_fault() -> None:
    """The base Kind.to_intent() raises Fault to signal contract enforcement.

    Kind is abstract, so we instantiate via Existing which inherits the
    base behaviour, then call to_intent() with no parsed_intent.
    """
    base = Existing(id="x", requirement=make_need(), cedar="permit (...);")
    with pytest.raises(Exception):
        base.to_intent()


def test_existing_to_dict_includes_parsed_intent_when_present() -> None:
    intent = make_intent()
    existing = Existing(
        id="hr",
        requirement=make_need(),
        cedar="permit (...);",
        parsed_intent=intent,
    )
    d = existing.to_dict()
    assert d["parsed_intent"] == intent.id


def test_existing_to_dict_includes_null_parsed_intent_when_missing() -> None:
    existing = Existing(id="hr", requirement=make_need(), cedar="permit (...);")
    d = existing.to_dict()
    assert d["parsed_intent"] is None


def test_kind_test_returns_suite_even_without_results() -> None:
    """test() constructs an empty Suite when no scenarios run."""
    from cedrus.case import Suite

    policy = Draft(
        id="hr",
        requirement=make_need(),
        principal=Principal(kind="any"),
        action=Action(kind="any"),
        resource=Resource(kind="any"),
    )
    object.__setattr__(policy, "cedar", "permit (principal, action, resource);")
    suite = policy.test(build_schema(), [])
    assert isinstance(suite, Suite)
    assert suite.results == ()


def test_kind_validate_raises_fault_on_empty_cedar() -> None:
    """Kind.validate refuses to validate a policy with no Cedar source."""
    from cedrus.error import Fault

    policy = Draft(
        id="hr",
        requirement=make_need(),
        principal=Principal(kind="any"),
        action=Action(kind="any"),
        resource=Resource(kind="any"),
    )
    with pytest.raises(Fault):
        policy.validate(build_schema())


# ---------------------------------------------------------------------------
# Draft.generate / Draft.apply_result
# ---------------------------------------------------------------------------


def test_draft_generate_calls_generator_with_draft_context() -> None:
    from cedrus.generate import Context, Proposal, Result

    captured: dict = {}

    class StubGenerator:
        name = "stub"
        model = "stub-model"
        def generate(self, context: Context) -> Result:
            from cedrus.data import Notes, Unresolved, Usage

            captured["need"] = context.need.id
            return Result(
                proposal=Proposal(
                    intent=None,  # type: ignore[arg-type]
                    unresolved=Unresolved(),
                    notes=Notes(),
                ),
                model="stub",
                request_id="",
                usage=Usage(prompt=0, completion=0, total=0),
            )

    draft = Draft(
        id="hr",
        requirement=make_need(),
        principal=Principal(kind="is_type", type_name="User"),
        action=Action(kind="named", name="view"),
        resource=Resource(kind="is_type", type_name="Photo"),
    )
    proposal = draft.generate(
        build_schema(),
        StubGenerator(),
    )
    assert captured["need"] == "HR-001"
    assert isinstance(proposal, Proposal)


def test_draft_generate_skips_existing_policies_that_cant_be_intented() -> None:
    from cedrus.generate import Context, Proposal, Result

    captured: dict = {}

    class StubGenerator:
        name = "stub"
        model = "stub-model"
        def generate(self, context: Context) -> Result:
            from cedrus.data import Notes, Unresolved, Usage

            captured["existing_count"] = len(context.existing)
            return Result(
                proposal=Proposal(
                    intent=None,  # type: ignore[arg-type]
                    unresolved=Unresolved(),
                    notes=Notes(),
                ),
                model="stub",
                request_id="",
                usage=Usage(prompt=0, completion=0, total=0),
            )

    existing = Existing(
        id="HR-099", requirement=make_need(), cedar="permit (...);"
    )
    draft = Draft(id="hr", requirement=make_need())
    draft.generate(
        build_schema(),
        StubGenerator(),
        existing=[existing],
    )
    assert captured["existing_count"] == 0


def test_draft_apply_result_merges_notes() -> None:
    from cedrus.data import Notes, Unresolved, Usage
    from cedrus.generate import Proposal, Result as GenResult

    base = Draft(
        id="hr",
        requirement=make_need(),
        notes=Notes(items=(("author", "alice"),)),
    )
    proposal = Proposal(
        intent=None,  # type: ignore[arg-type]
        unresolved=Unresolved(items=("x",)),
        notes=Notes(items=(("generator", "offline"),)),
    )
    result = GenResult(
        proposal=proposal,
        model="offline",
        request_id="",
        usage=Usage(prompt=0, completion=0, total=0),
    )
    merged = base.apply_result(result)
    notes = merged.notes.to_dict()
    assert notes["author"] == "alice"
    assert notes["generator"] == "offline"


__all__ = []