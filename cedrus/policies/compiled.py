"""A policy that has been compiled and validated.

A :class:`Compiled` is the final form produced by
:meth:`Workspace.apply` after the compiler has rendered the intent
and Cedar has accepted the source. The workspace treats a compiled
policy as the authoritative artifact for that requirement and
includes it in subsequent verification, test, and deployment runs.

Compiled policies are immutable. To produce a new version, build a
:class:`Draft` from the same requirement and run the apply
pipeline again; cedrus does not currently version policies
internally.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..case import Case, Suite, run_scenarios
from ..compile import Intent
from ..error import Fault
from ..need import Need
from ..schema import Schema
from ..validate import Vreport, validate_cedar
from .base import Kind


@dataclass(frozen=True, slots=True)
class Compiled(Kind):
    """A policy that has been compiled and successfully validated.

    Attributes:
        intent: Typed intent that produced this policy.
    """

    intent: Intent | None = None

    def kind(self) -> str:
        """Return the policy kind discriminator (``"compiled"``)."""
        return "compiled"

    def to_intent(self) -> Intent:
        """Return the typed intent for this compiled policy.

        Raises:
            Policy: If the intent metadata is missing. This
                should not happen for policies produced by
                :meth:`Workspace.apply`; the field is optional only
                so that legacy storage rows without intent metadata
                remain readable.
        """
        if self.intent is None:
            raise Fault(f"compiled policy {self.id} is missing intent metadata")
        return self.intent

    def test(
        self,
        schema: Schema,
        scenarios: list[Case],
        entities: list[Mapping[str, Any]] | None = None,
    ) -> Suite:
        """Run authorization scenarios through the Cedar engine.

        Args:
            schema: Cedar schema for scenario evaluation.
            scenarios: Scenarios to execute.
            entities: Optional entities to expose to the engine.

        Returns:
            A :class:`Suite` summarizing the outcomes.
        """
        return run_scenarios(
            [self.cedar],
            list(entities or []),
            scenarios,
            schema=schema,
        )

    def validate(self, schema: Schema) -> Vreport:
        """Validate this policy against ``schema``.

        Args:
            schema: Cedar schema to validate against.

        Returns:
            A :class:`Vreport` describing the outcome.
        """
        return validate_cedar([self.cedar], schema)

    def to_dict(self) -> Mapping[str, Any]:
        """Return a JSON-friendly representation of this compiled policy.

        Includes the intent id when present, or ``None`` when the policy
        has no stored intent metadata.
        """
        data = dict(Kind.to_dict(self))
        data["intent_id"] = None if self.intent is None else self.intent.id
        return data

    @classmethod
    def from_intent(
        cls,
        intent: Intent,
        cedar: str,
        requirement: Need,
        *,
        policy_id: str | None = None,
    ) -> Compiled:
        """Build a :class:`Compiled` from a typed intent and Cedar source.

        Args:
            intent: Typed intent that produced the Cedar.
            cedar: Compiled Cedar source text.
            requirement: Originating requirement.
            policy_id: Optional explicit identifier. Defaults to
                ``intent.id``.

        Returns:
            The constructed :class:`Compiled`.
        """
        return cls(
            id=policy_id or intent.id,
            requirement=requirement,
            cedar=cedar,
            intent=intent,
        )


__all__ = ["Compiled"]
