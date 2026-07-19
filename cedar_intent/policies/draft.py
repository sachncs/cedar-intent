"""Draft policies produced by a generator."""

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
        """Return the policy kind discriminator."""
        return "draft"

    def to_intent(self) -> PolicyIntent:
        if self.intent is None:
            raise PolicyError(f"draft {self.id} has no compiled intent yet")
        return self.intent

    def with_status(self, status: DraftStatus) -> DraftPolicy:
        """Return a copy of this draft with the given status."""
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

        Args:
            schema: Cedar schema the draft must conform to.
            generator: Generator used to produce the proposal.
            existing: Existing policies the generator should be aware of.

        Returns:
            A :class:`DraftProposal` produced by the generator.
        """
        existing_intents = [
            policy.to_intent() for policy in existing if isinstance(policy, Policy)
        ]
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
        """Merge a :class:`GenerationResult` into a :class:`DraftProposal`."""
        proposal = result.proposal
        return DraftProposal(
            intent=proposal.intent,
            unresolved=proposal.unresolved,
            notes={**self.notes, **proposal.notes},
        )

    def compile(self, schema: CedarSchema | None = None) -> CompiledSource:
        """Compile this draft's intent (or build one from scopes) to Cedar source.

        Args:
            schema: Optional schema kept for interface compatibility with
                :class:`Policy.compile`. Compilation itself is independent
                of the schema because the :class:`PolicyIntent` already
                encodes the namespace resolution.
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
        """Build a :class:`DraftPolicy` for a requirement with the supplied scopes."""
        return cls(
            id=policy_id or f"draft-{requirement.id}",
            requirement=requirement,
            principal=principal or PrincipalScope(),
            action=action or ActionScope(),
            resource=resource or ResourceScope(),
        )


__all__ = ["DraftPolicy", "DraftStatus"]
