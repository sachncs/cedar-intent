"""Offline generator that returns deterministic proposals without network calls.

Useful for tests, CI without credentials, and reproducible local
development. The proposal is built from the requirement text and the
supplied scopes, so it is stable across runs.

Heuristics
----------

The offline generator applies three lightweight heuristics:

1. **Effect** - if the requirement text contains ``forbid``, ``deny``,
   ``never``, ``prohibit``, or ``disallow``, the proposal is
   ``"forbid"``; otherwise it is ``"permit"``.
2. **When clause** - the substring after the word ``when`` until the
   next sentence boundary is captured as a single :class:`ConditionClause`.
3. **Unresolved flags** - if both action and resource are ``any`` and
   the requirement does not mention ``public``, the generator flags
   that the requirement does not specify an action or resource.
   If principal is ``any``, it flags that the principal scope should
   be tightened.

These heuristics are intentionally simple: the offline generator
exists for fast iteration and offline development, not for nuanced
policy authoring. Use :class:`LiteLLMGenerator` for production
drafting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ..compiler import PolicyIntent
from ..requirements import slugify
from ..scopes import ActionScope, ConditionClause, PrincipalScope, ResourceScope
from .base import DraftProposal, GenerationContext, GenerationResult

Effect = Literal["permit", "forbid"]

PROHIBIT_KEYWORDS = re.compile(r"\b(forbid|deny|never|prohibit|disallow)\b")
WHEN_PATTERN = re.compile(r"\bwhen\s+(.+?)(?:\.|$)", flags=re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True, slots=True)
class OfflineGenerator:
    """A deterministic generator for offline and test use.

    Attributes:
        name: Generator identifier surfaced in provenance metadata.
        model: Model identifier surfaced in provenance metadata.
    """

    name: str = "offline"
    model: str = "offline-deterministic"

    def generate(self, context: GenerationContext) -> GenerationResult:
        """Produce a :class:`GenerationResult` for ``context``.

        Args:
            context: The generation context supplied by the workspace.

        Returns:
            A :class:`GenerationResult` carrying the typed proposal and
            deterministic provenance.
        """
        intent_id = f"{context.requirement.domain}-{slugify(context.requirement.id)}"
        when_clause = self.detect_when_clause(context.requirement.text)
        intent = PolicyIntent(
            id=intent_id,
            requirement_id=context.requirement.id,
            effect=self.detect_effect(context.requirement.text),
            principal=context.principal,
            action=context.action,
            resource=context.resource,
            when_clauses=(when_clause,) if when_clause else (),
            notes={"generator": self.name},
        )
        unresolved = self.detect_unresolved(context)
        proposal = DraftProposal(
            intent=intent,
            unresolved=unresolved,
            notes={"generator": self.name},
        )
        return GenerationResult(
            proposal=proposal,
            model=self.model,
            request_id=None,
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )

    @staticmethod
    def detect_effect(text: str) -> Effect:
        """Infer ``permit`` vs ``forbid`` from simple keyword cues in ``text``.

        Args:
            text: The requirement body.

        Returns:
            ``"forbid"`` if a prohibit keyword is present, otherwise
            ``"permit"``.
        """
        if PROHIBIT_KEYWORDS.search(text.lower()):
            return "forbid"
        return "permit"

    @staticmethod
    def detect_when_clause(text: str) -> ConditionClause | None:
        """Extract a single ``when`` clause body from the requirement text.

        Args:
            text: The requirement body.

        Returns:
            A :class:`ConditionClause` wrapping the substring after the
            first ``when`` keyword, or ``None`` when no such clause is
            present.
        """
        match = WHEN_PATTERN.search(text)
        if not match:
            return None
        body = match.group(1).strip().rstrip(".")
        if not body:
            return None
        return ConditionClause(body=body)

    @staticmethod
    def detect_unresolved(context: GenerationContext) -> tuple[str, ...]:
        """Surface the kinds of issues an offline generator can identify.

        Flags two situations:

        * Both action and resource are ``any`` and the requirement does
          not mention ``public``. The generator cannot pick a sensible
          action or resource, so it tells the caller to refine.
        * Principal is ``any``. The generator encourages tightening the
          principal scope to a specific type or id.

        Args:
            context: The generation context.

        Returns:
            A tuple of human-readable unresolved item strings.
        """
        issues: list[str] = []
        if (
            context.action == ActionScope(kind="any")
            and context.resource == ResourceScope(kind="any")
            and "public" not in context.requirement.text.lower()
        ):
            issues.append(
                "Requirement does not specify an action or resource; "
                "manual refinement required."
            )
        if context.principal == PrincipalScope(kind="any"):
            issues.append(
                "Principal scope is 'any'; tighten to a specific principal type or id."
            )
        return tuple(issues)


__all__ = ["Effect", "OfflineGenerator"]
