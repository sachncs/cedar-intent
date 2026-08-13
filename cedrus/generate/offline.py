"""Offline generator that returns deterministic proposals without network calls.

Useful for tests, CI without credentials, and reproducible local
development. The proposal is built from the requirement text and the
supplied scopes, so it is stable across runs.

Heuristics:
    The offline generator applies three lightweight heuristics:

    1. **Effect** - if the requirement text contains ``forbid``, ``deny``,
       ``never``, ``prohibit``, or ``disallow``, the proposal is
       ``"forbid"``; otherwise it is ``"permit"``.
    2. **When clause** - the substring after the word ``when`` until the
       next sentence boundary is captured as a single :class:`Clause`.
    3. **Unresolved flags** - if both action and resource are ``any`` and
       the requirement does not mention ``public``, the generator flags
       that the requirement does not specify an action or resource.
       If principal is ``any``, it flags that the principal scope should
       be tightened.

    These heuristics are intentionally simple: the offline generator
    exists for fast iteration and offline development, not for nuanced
    policy authoring. Use :class:`Llm` for production drafting.

Attributes:
    Offline: Deterministic generator that requires no network calls.

See Also:
    :mod:`cedrus.generate.base`: :class:`Generator` Protocol that
        :class:`Offline` implements.
    :mod:`cedrus.generate.litellm`: LLM-backed generator for
        production drafting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cedrus.compile import Intent
from cedrus.data import Notes, Unresolved, Usage
from cedrus.generate.base import Context, Proposal, Result
from cedrus.scope import Action, Clause, Principal, Resource

PROHIBIT_KEYWORDS = re.compile(r"\b(forbid|deny|never|prohibit|disallow)\b")
WHEN_PATTERN = re.compile(r"\bwhen\s+(.+?)(?:\.|$)", flags=re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True, slots=True)
class Offline:
    """A deterministic generator for offline and test use.

    Builds an :class:`Intent` by feeding the inlined heuristic outputs
    through :meth:`Intent.parse` so the typed-object parser is the
    single place that constructs an intent. The generator never
    touches the network, so it is safe to use in CI without provider
    credentials.

    Attributes:
        name: Generator identifier surfaced in provenance metadata.
        model: Model identifier surfaced in provenance metadata.
    """

    name: str = "offline"
    model: str = "offline-deterministic"

    def generate(self, context: Context) -> Result:
        """Produce a :class:`Result` for ``context``.

        Runs the three heuristics (effect, when clauses, unresolved
        flags) inline, assembles a payload dict, and routes it through
        :meth:`Intent.parse` for typed construction. The unresolved
        flags from the heuristic block are layered on top of whatever
        the when-clause heuristic already captured.

        Args:
            context: The generation context supplied by the workspace.

        Returns:
            A :class:`Result` carrying the typed proposal and
            deterministic provenance.
        """
        # --- Effect heuristic ----------------------------------------
        text_lower = context.need.text.lower()
        effect = "forbid" if PROHIBIT_KEYWORDS.search(text_lower) else "permit"

        # --- When-clause heuristic -----------------------------------
        when_clauses: tuple[Clause, ...] = ()
        match = WHEN_PATTERN.search(context.need.text)
        if match:
            body = match.group(1).strip().rstrip(".")
            if body:
                when_clauses = Clause.normalize(body)

        # --- Intent construction via the polymorphic parser ----------
        payload = {
            "effect": effect,
            "principal": context.principal.to_dict(),
            "action": context.action.to_dict(),
            "resource": context.resource.to_dict(),
            "when": [c.body for c in when_clauses],
            "unless": [],
        }
        intent = Intent.parse(
            payload,
            need=context.need,
            principal=context.principal,
            action=context.action,
            resource=context.resource,
            generator_name=self.name,
        )

        # --- Unresolved flags heuristic ------------------------------
        issues: list[str] = []
        if (
            context.action == Action(kind="any")
            and context.resource == Resource(kind="any")
            and "public" not in text_lower
        ):
            issues.append(
                "Need does not specify an action or resource; "
                "manual refinement required."
            )
        if context.principal == Principal(kind="any"):
            issues.append(
                "Principal scope is 'any'; tighten to a specific principal type or id."
            )

        proposal = Proposal(
            intent=intent,
            unresolved=Unresolved(items=tuple(issues)),
            notes=Notes.from_dict({"generator": self.name, "model": self.model}),
        )
        return Result(
            proposal=proposal,
            model=self.model,
            request_id="",
            usage=Usage(prompt=0, completion=0, total=0),
        )


__all__ = ["Offline"]