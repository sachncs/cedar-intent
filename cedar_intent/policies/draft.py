"""Draft policies produced by a generator.

A :class:`DraftPolicy` is the in-memory representation of a policy under
authoring. It carries the principal, action, and resource scopes the
caller supplied plus the optional typed intent the generator produced.

Lifecycle
---------

1. :meth:`DraftPolicy.from_requirement` creates an empty draft from a
   :class:`~cedar_intent.requirements.Requirement` and caller scopes.
2. :meth:`DraftPolicy.generate` calls a generator and stores the
   resulting :class:`~cedar_intent.generator.DraftProposal` on the
   draft.
3. :meth:`DraftPolicy.compile` renders the draft (or a freshly built
   :class:`~cedar_intent.compiler.PolicyIntent` if no intent was set)
   to Cedar source.
4. :meth:`DraftPolicy.as_compiled` returns a copy of the draft with the
   compiled Cedar source populated.

Thread safety
-------------

``DraftPolicy`` is ``frozen=True, slots=True`` and therefore immutable
and safe to share across threads.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..compiler import CompiledSource, PolicyIntent, compile_intent
from ..errors import PolicyError
from ..generator import DraftProposal, GenerationContext, GenerationResult, Generator
from ..requirements import Requirement
from ..schema import CedarSchema
from ..scopes import ActionScope, PrincipalScope, ResourceScope
from .base import Policy

DraftStatus = str  # "proposed" | "accepted" | "rejected"


@dataclass(frozen=True, slots=True)
class DraftPolicy(Policy):
    """A draft policy with explicit principal, action, and resource scopes.

    Attributes:
        principal: Principal scope applied to the draft.
        action: Action scope applied to the draft.
        resource: Resource scope applied to the draft.
        intent: Optional typed intent produced by a generator.
        unresolved: Items the generator could not safely resolve.
        status: Lifecycle status (``"proposed"``, ``"accepted"``, ``"rejected"``).
        notes: Free-form metadata recorded for downstream consumers.
        model: Model identifier that produced the draft (if any).
        request_id: Provider-supplied request identifier (if any).
    """

    principal: PrincipalScope = field(default_factory=lambda: PrincipalScope())
    action: ActionScope = field(default_factory=lambda: ActionScope())
    resource: ResourceScope = field(default_factory=lambda: ResourceScope())
    intent: PolicyIntent | None = None
    unresolved: tuple[str, ...] = field(default_factory=tuple)
    status: DraftStatus = "proposed"
    notes: Mapping[str, str] = field(default_factory=dict)
    model: str | None = None
    request_id: str | None = None

    def kind(self) -> str:
        """Return the policy kind discriminator (``"draft"``)."""
        return "draft"

    def to_intent(self) -> PolicyIntent:
        """Return the typed intent for this draft.

        Raises:
            PolicyError: If the draft has no compiled intent yet.
        """
        if self.intent is None:
            raise PolicyError(f"draft {self.id} has no compiled intent yet")
        return self.intent

    def with_status(self, status: DraftStatus) -> DraftPolicy:
        """Return a copy of this draft with the given status.

        Args:
            status: New lifecycle status.

        Returns:
            A new :class:`DraftPolicy` instance; the original is left
            untouched because the dataclass is frozen.
        """
        return DraftPolicy(
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
        schema: CedarSchema,
        generator: Generator,
        *,
        existing: Sequence[Policy] = (),
    ) -> DraftProposal:
        """Call ``generator`` with this draft's scopes and existing context.

        The existing policies are converted to :class:`PolicyIntent` so
        the generator sees a uniform, typed view. Policies whose
        ``to_intent`` raises :class:`PolicyError` (typically unparsed
        :class:`ExistingPolicy`) are silently skipped; they would only
        confuse the generator anyway.

        Args:
            schema: Cedar schema the draft must conform to.
            generator: Generator used to produce the proposal.
            existing: Existing policies the generator should be aware of.

        Returns:
            A :class:`DraftProposal` produced by the generator.
        """
        existing_intents: list[PolicyIntent] = []
        for policy in existing:
            # ExistingPolicy with no parsed intent raises PolicyError from
            # to_intent(); that is the expected case (the generator only
            # sees policies it can reason about). Failing to parse must
            # not block the entire draft.
            try:
                existing_intents.append(policy.to_intent())
            except PolicyError:
                continue
        context = GenerationContext(
            requirement=self.requirement,
            schema=schema,
            principal=self.principal,
            action=self.action,
            resource=self.resource,
            existing=tuple(existing_intents),
        )
        result = generator.generate(context)
        return self.apply_result(result)

    def apply_result(self, result: GenerationResult) -> DraftProposal:
        """Merge a :class:`GenerationResult` into a :class:`DraftProposal`.

        Args:
            result: Generation result from a :class:`Generator`.

        Returns:
            A :class:`DraftProposal` whose intent matches the generator's
            proposal and whose notes merge the draft's own notes with
            the generator's.
        """
        proposal = result.proposal
        return DraftProposal(
            intent=proposal.intent,
            unresolved=proposal.unresolved,
            notes={**self.notes, **proposal.notes},
        )

    def compile(self, schema: CedarSchema | None = None) -> CompiledSource:
        """Compile this draft's intent (or build one from scopes) to Cedar source.

        If the draft already has an intent, the compiler renders that
        intent directly. Otherwise a minimal ``permit(..., any, any)``
        intent is constructed from the current scopes so the user sees
        what the draft would produce.

        Args:
            schema: Optional schema kept for interface compatibility
                with :class:`Policy.compile`. Compilation itself is
                independent of the schema because the
                :class:`PolicyIntent` already encodes the namespace
                resolution.

        Returns:
            A :class:`CompiledSource` containing the rendered Cedar
            text and metadata.
        """
        if self.intent is not None:
            return compile_intent(self.intent)
        intent = PolicyIntent(
            id=self.id,
            requirement_id=self.requirement.id,
            effect="permit",
            principal=self.principal,
            action=self.action,
            resource=self.resource,
            notes={"generator": "manual"},
        )
        return compile_intent(intent)

    def as_compiled(self, schema: CedarSchema | None = None) -> DraftPolicy:
        """Return a copy of this draft with cedar populated from the compiler.

        Args:
            schema: Forwarded to :meth:`compile` for interface symmetry.

        Returns:
            A new :class:`DraftPolicy` instance with ``cedar`` populated
            and ``created_at`` bumped to the current time.
        """
        source = self.compile(schema)
        updated_at = datetime.now(UTC)
        return DraftPolicy(
            id=self.id,
            requirement=self.requirement,
            cedar=source.cedar,
            created_at=updated_at,
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

        Extends :meth:`Policy.to_dict` with the scope kinds, lifecycle
        status, and unresolved items.
        """
        data = dict(Policy.to_dict(self))
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
        requirement: Requirement,
        *,
        principal: PrincipalScope | None = None,
        action: ActionScope | None = None,
        resource: ResourceScope | None = None,
        policy_id: str | None = None,
    ) -> DraftPolicy:
        """Build a :class:`DraftPolicy` for a requirement with the supplied scopes.

        Args:
            requirement: Originating requirement.
            principal: Optional principal scope. Defaults to ``any``.
            action: Optional action scope. Defaults to ``any``.
            resource: Optional resource scope. Defaults to ``any``.
            policy_id: Optional explicit identifier. Defaults to
                ``"draft-<requirement.id>"``.

        Returns:
            An empty :class:`DraftPolicy` with the supplied scopes.
        """
        return cls(
            id=policy_id or f"draft-{requirement.id}",
            requirement=requirement,
            principal=principal or PrincipalScope(),
            action=action or ActionScope(),
            resource=resource or ResourceScope(),
        )


__all__ = ["DraftPolicy", "DraftStatus"]
