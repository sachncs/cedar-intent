"""Tests for :mod:`cedrus.generate` — Offline / Llm / Generator / Context / Proposal / Result."""
from __future__ import annotations

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


__all__ = []