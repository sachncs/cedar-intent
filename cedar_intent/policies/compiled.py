"""A policy that has been compiled and validated.

A :class:`CompiledPolicy` is the final form produced by
:meth:`Workspace.apply` after the compiler has rendered the intent
and Cedar has accepted the source. The workspace treats a compiled
policy as the authoritative artifact for that requirement and
includes it in subsequent verification, test, and deployment runs.

Compiled policies are immutable. To produce a new version, build a
:class:`DraftPolicy` from the same requirement and run the apply
pipeline again; cedar-intent does not currently version policies
internally.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..compiler import PolicyIntent
from ..errors import PolicyError
from ..requirements import Requirement
from ..scenarios import Scenario, TestReport, run_scenarios
from ..schema import CedarSchema
from ..validation import ValidationReport, validate_cedar
from .base import Policy


@dataclass(frozen=True, slots=True)
class CompiledPolicy(Policy):
    """A policy that has been compiled and successfully validated.

    Attributes:
        intent: Typed intent that produced this policy.
    """

    intent: PolicyIntent | None = None

    def kind(self) -> str:
        """Return the policy kind discriminator (``"compiled"``)."""
        return "compiled"

    def to_intent(self) -> PolicyIntent:
        """Return the typed intent for this compiled policy.

        Raises:
            PolicyError: If the intent metadata is missing. This
                should not happen for policies produced by
                :meth:`Workspace.apply`; the field is optional only
                so that legacy storage rows without intent metadata
                remain readable.
        """
        if self.intent is None:
            raise PolicyError(f"compiled policy {self.id} is missing intent metadata")
        return self.intent

    def test(
        self,
        schema: CedarSchema,
        scenarios: list[Scenario],
        entities: list[Mapping[str, Any]] | None = None,
    ) -> TestReport:
        """Run authorization scenarios through the Cedar engine.

        Args:
            schema: Cedar schema for scenario evaluation.
            scenarios: Scenarios to execute.
            entities: Optional entities to expose to the engine.

        Returns:
            A :class:`TestReport` summarizing the outcomes.
        """
        return run_scenarios(
            [self.cedar],
            list(entities or []),
            scenarios,
            schema=schema,
        )

    def validate(self, schema: CedarSchema) -> ValidationReport:
        """Validate this policy against ``schema``.

        Args:
            schema: Cedar schema to validate against.

        Returns:
            A :class:`ValidationReport` describing the outcome.
        """
        return validate_cedar([self.cedar], schema)

    def to_dict(self) -> Mapping[str, Any]:
        """Return a JSON-friendly representation of this compiled policy.

        Includes the intent id when present, or ``None`` when the policy
        has no stored intent metadata.
        """
        data = dict(Policy.to_dict(self))
        data["intent_id"] = None if self.intent is None else self.intent.id
        return data

    @classmethod
    def from_intent(
        cls,
        intent: PolicyIntent,
        cedar: str,
        requirement: Requirement,
        *,
        policy_id: str | None = None,
    ) -> CompiledPolicy:
        """Build a :class:`CompiledPolicy` from a typed intent and Cedar source.

        Args:
            intent: Typed intent that produced the Cedar.
            cedar: Compiled Cedar source text.
            requirement: Originating requirement.
            policy_id: Optional explicit identifier. Defaults to
                ``intent.id``.

        Returns:
            The constructed :class:`CompiledPolicy`.
        """
        return cls(
            id=policy_id or intent.id,
            requirement=requirement,
            cedar=cedar,
            intent=intent,
        )


__all__ = ["CompiledPolicy"]
