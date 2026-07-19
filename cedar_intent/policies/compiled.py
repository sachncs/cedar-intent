"""A policy that has been compiled and validated."""

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
        """Return the policy kind discriminator."""
        return "compiled"

    def to_intent(self) -> PolicyIntent:
        if self.intent is None:
            raise PolicyError(f"compiled policy {self.id} is missing intent metadata")
        return self.intent

    def test(
        self,
        schema: CedarSchema,
        scenarios: list[Scenario],
        entities: list[Mapping[str, Any]] | None = None,
    ) -> TestReport:
        """Run authorization scenarios through the Cedar engine."""
        return run_scenarios(
            [self.cedar],
            list(entities or []),
            scenarios,
            schema=schema,
        )

    def validate(self, schema: CedarSchema) -> ValidationReport:
        """Validate this policy against ``schema``."""
        return validate_cedar([self.cedar], schema)

    def to_dict(self) -> Mapping[str, Any]:
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
        """Build a :class:`CompiledPolicy` from a typed intent and Cedar source."""
        return cls(
            id=policy_id or intent.id,
            requirement=requirement,
            cedar=cedar,
            intent=intent,
        )


__all__ = ["CompiledPolicy"]
