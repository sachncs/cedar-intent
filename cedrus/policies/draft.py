"""Draft policies produced by a generator.

A :class:`Draft` is the in-memory representation of a policy under
authoring. It carries the principal, action, and resource scopes the
caller supplied plus the optional typed intent the generator produced.

Lifecycle:
    1. :meth:`Draft.from_requirement` creates an empty draft from a
       :class:`~cedrus.need.Need` and caller scopes.
    2. :meth:`Draft.generate` calls a generator and stores the
       resulting :class:`~cedrus.generate.Proposal` on the draft.
    3. :meth:`Draft.compile` renders the draft (or a freshly built
       :class:`~cedrus.compile.Intent` if no intent was set) to Cedar
       source.
    4. :meth:`Draft.as_compiled` returns a copy of the draft with the
       compiled Cedar source populated.

Thread safety:
    ``Draft`` is ``frozen=True, slots=True`` and therefore immutable
    and safe to share across threads.

Attributes:
    Draft: A draft policy carrying explicit scopes and an optional
        typed intent.
    DraftStatus: Lifecycle status string for a draft.

See Also:
    :mod:`cedrus.policies.base`: :class:`Kind` abstract base that
        :class:`Draft` extends.
    :mod:`cedrus.policies.compiled`: The :class:`Compiled` form this
        draft becomes after a successful apply.
    :mod:`cedrus.policies.existing`: The :class:`Existing` form for
        policies imported from raw Cedar source.
    :mod:`cedrus.generate`: :class:`Generator` Protocol used by
        :meth:`Draft.generate`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from cedrus.compile import Intent, Source
from cedrus.data import Notes
from cedrus.error import Fault
from cedrus.generate import Context, Generator, Proposal, Result
from cedrus.need import Need
from cedrus.schema import Schema
from cedrus.scope import Action, Principal, Resource
from cedrus.policies.base import Kind

DraftStatus = str  # "proposed" | "accepted" | "rejected"


@dataclass(frozen=True, slots=True)
class Draft(Kind):
    """A draft policy with explicit principal, action, and resource scopes.

    Overrides :meth:`to_intent` to return the stored typed intent and
    :meth:`to_dict` to expose the scope kinds, status and unresolved
    items. Inherits :meth:`validate`, :meth:`test` and the base
    :meth:`to_dict` shape from :class:`Kind`.

    Attributes:
        principal: Principal scope applied to the draft.
        action: Action scope applied to the draft.
        resource: Resource scope applied to the draft.
        intent: Optional typed intent produced by a generator.
        unresolved: Items the generator could not safely resolve.
        status: Lifecycle status (``"proposed"``, ``"accepted"``,
            ``"rejected"``).
        notes: Free-form metadata recorded for downstream consumers.
        model: Model identifier that produced the draft (if any).
        request_id: Provider-supplied request identifier (if any).
    """

    principal: Principal = field(default_factory=lambda: Principal())
    action: Action = field(default_factory=lambda: Action())
    resource: Resource = field(default_factory=lambda: Resource())
    intent: Intent | None = None
    unresolved: tuple[str, ...] = field(default_factory=tuple)
    status: DraftStatus = "proposed"
    notes: Notes = field(default_factory=Notes)
    model: str | None = None
    request_id: str | None = None

    def kind(self) -> str:
        """Return the policy kind discriminator.

        Returns:
            Always ``"draft"``.
        """
        return "draft"

    def to_intent(self) -> Intent:
        """Return the typed intent for this draft.

        Returns:
            The stored :class:`Intent`.

        Raises:
            Fault: If the draft has no compiled intent yet.
        """
        if self.intent is None:
            raise Fault(f"draft {self.id} has no compiled intent yet")
        return self.intent

    def with_status(self, status: DraftStatus) -> Draft:
        """Return a copy of this draft with the given status.

        Args:
            status: New lifecycle status.

        Returns:
            A new :class:`Draft` instance; the original is left
            untouched because the dataclass is frozen.
        """
        return Draft(
            id=self.id,
            requirement=self.requirement,
            cedar=self.cedar,
            created_at=self.created_at,
            principal=self.principal,
            action=self.action,
            resource=self.resource,
            intent=self.intent,
            unresolved=self.unresolved,
            status=status,
            notes=self.notes,
            model=self.model,
            request_id=self.request_id,
        )

    def generate(
        self,
        schema: Schema,
        generator: Generator,
        *,
        existing: Sequence[Kind] = (),
    ) -> Proposal:
        """Call ``generator`` with this draft's scopes and existing context.

        The existing policies are converted to :class:`Intent` so the
        generator sees a uniform, typed view. Policies whose
        ``to_intent`` raises :class:`Fault` (typically unparsed
        :class:`~cedrus.policies.existing.Existing`) are silently
        skipped; they would only confuse the generator anyway.

        Args:
            schema: Cedar schema the draft must conform to.
            generator: Generator used to produce the proposal.
            existing: Existing policies the generator should be aware
                of.

        Returns:
            A :class:`Proposal` produced by the generator.
        """
        existing_intents: list[Intent] = []
        for policy in existing:
            # Existing with no parsed intent raises Fault from
            # to_intent(); that is the expected case (the generator only
            # sees policies it can reason about). Failing to parse must
            # not block the entire draft.
            try:
                existing_intents.append(policy.to_intent())
            except Fault:
                continue
        context = Context(
            need=self.requirement,
            schema=schema,
            principal=self.principal,
            action=self.action,
            resource=self.resource,
            existing=tuple(existing_intents),
        )
        return self.apply_result(generator.generate(context))

    def apply_result(self, result: Result) -> Proposal:
        """Merge a :class:`Result` into a :class:`Proposal`.

        Args:
            result: Generation result from a :class:`Generator`.

        Returns:
            A :class:`Proposal` whose intent matches the generator's
            proposal and whose notes merge the draft's own notes with
            the generator's.
        """
        proposal = result.proposal
        merged = dict(self.notes.to_dict())
        if proposal.notes is not None:
            merged.update(proposal.notes.to_dict())
        return Proposal(
            intent=proposal.intent,
            unresolved=proposal.unresolved,
            notes=Notes.from_dict(merged),
        )

    def compile(self, schema: Schema | None = None) -> Source:
        """Compile this draft's intent (or build one from scopes) to Cedar source.

        If the draft already has an intent, the compiler renders that
        intent directly. Otherwise a minimal ``permit(..., any, any)``
        intent is constructed from the current scopes so the user
        sees what the draft would produce. Polymorphic route: defer
        to :meth:`Intent.compile` on the intent object.

        Args:
            schema: Optional schema kept for interface compatibility
                with :class:`Fault.compile`. Compilation itself is
                independent of the schema because the
                :class:`Intent` already encodes the namespace
                resolution.

        Returns:
            A :class:`Source` containing the rendered Cedar text and
            metadata.

        Raises:
            Fault: If the stored intent fails to compile (propagated
                from :meth:`Intent.compile`).
        """
        if self.intent is not None:
            return self.intent.compile()
        return Intent(
            id=self.id,
            requirement_id=self.requirement.id,
            effect="permit",
            principal=self.principal,
            action=self.action,
            resource=self.resource,
            notes={"generator": "manual"},
        ).compile()

    def as_compiled(self, schema: Schema | None = None) -> Draft:
        """Return a copy of this draft with cedar populated from the compiler.

        Args:
            schema: Forwarded to :meth:`compile` for interface symmetry.

        Returns:
            A new :class:`Draft` instance with ``cedar`` populated
            and ``created_at`` bumped to the current time.
        """
        source = self.compile(schema)
        return Draft(
            id=self.id,
            requirement=self.requirement,
            cedar=source.cedar,
            created_at=datetime.now(UTC),
            principal=self.principal,
            action=self.action,
            resource=self.resource,
            intent=self.intent,
            unresolved=self.unresolved,
            status=self.status,
            notes=self.notes,
            model=self.model,
            request_id=self.request_id,
        )

    def to_dict(self) -> Mapping[str, Any]:
        """Return a JSON-friendly representation of this draft.

        Extends :meth:`Kind.to_dict` with the scope kinds, lifecycle
        status, and unresolved items.

        Returns:
            The base policy dict plus ``principal``, ``action``,
            ``resource``, ``status`` and ``unresolved`` keys.
        """
        data = dict(Kind.to_dict(self))
        data.update(
            {
                "principal": self.principal.kind,
                "action": self.action.kind,
                "resource": self.resource.kind,
                "status": self.status,
                "unresolved": list(self.unresolved),
            }
        )
        return data

    @classmethod
    def from_requirement(
        cls,
        requirement: Need,
        *,
        principal: Principal | None = None,
        action: Action | None = None,
        resource: Resource | None = None,
        policy_id: str | None = None,
    ) -> Draft:
        """Build a :class:`Draft` for a requirement with the supplied scopes.

        Args:
            requirement: Originating requirement.
            principal: Optional principal scope. Defaults to ``any``.
            action: Optional action scope. Defaults to ``any``.
            resource: Optional resource scope. Defaults to ``any``.
            policy_id: Optional explicit identifier. Defaults to
                ``"draft-<requirement.id>"``.

        Returns:
            An empty :class:`Draft` with the supplied scopes.
        """
        return cls(
            id=policy_id or f"draft-{requirement.id}",
            requirement=requirement,
            principal=principal or Principal(),
            action=action or Action(),
            resource=resource or Resource(),
        )


__all__ = ["Draft", "DraftStatus"]