"""Abstract :class:`Policy` base class and shared helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..compiler import CompiledSource, PolicyIntent, compile_intent
from ..errors import PolicyError
from ..requirements import Requirement
from ..scenarios import Scenario, TestReport, run_scenarios
from ..schema import CedarSchema
from ..validation import ValidationReport, validate_cedar


@dataclass(frozen=True, slots=True)
class Policy(ABC):
    """Abstract base for every policy object in cedar-intent.

    Attributes:
        id: Policy identifier.
        requirement: The originating requirement.
        cedar: Cedar source text (may be empty for uncompiled policies).
        created_at: Timestamp at which the object was constructed.
    """

    id: str
    requirement: Requirement
    cedar: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @abstractmethod
    def kind(self) -> str: ...

    def to_intent(self) -> PolicyIntent:
        """Return the :class:`PolicyIntent` representation of this policy.

        Subclasses must implement intent materialization. The base method
        raises :class:`PolicyError` to make the contract explicit.
        """
        raise PolicyError(
            f"{type(self).__name__}.to_intent() must be implemented by the subclass"
        )

    def intent_for_verification(self) -> PolicyIntent:
        """Return the policy's intent, with a placeholder when unavailable.

        Used by verification routines that must inspect every policy
        without triggering :class:`PolicyError` for unparsed existing
        policies.
        """
        try:
            return self.to_intent()
        except PolicyError as error:
            from ..compiler import PolicyIntent
            from ..scopes import ActionScope, PrincipalScope, ResourceScope

            return PolicyIntent(
                id=self.id,
                requirement_id=self.requirement.id,
                effect="permit",
                principal=PrincipalScope(),
                action=ActionScope(),
                resource=ResourceScope(),
                notes={"missing_intent": str(error)},
            )

    def compile(self, schema: CedarSchema) -> CompiledSource:
        """Compile this policy to Cedar source text using its intent."""
        return compile_intent(self.to_intent())

    def validate(self, schema: CedarSchema) -> ValidationReport:
        """Validate the Cedar source for this policy against ``schema``."""
        if not self.cedar:
            raise PolicyError(f"policy {self.id} has no Cedar source to validate")
        return validate_cedar([self.cedar], schema)

    def test(
        self,
        schema: CedarSchema,
        scenarios: list[Scenario],
        entities: list[Mapping[str, object]] | None = None,
    ) -> TestReport:
        """Run authorization scenarios through the Cedar engine."""
        return run_scenarios(
            [self.cedar],
            list(entities or []),
            scenarios,
            schema=schema,
        )

    def to_dict(self) -> Mapping[str, object]:
        """Return a JSON-friendly representation of this policy."""
        return {
            "id": self.id,
            "kind": self.kind(),
            "requirement_id": self.requirement.id,
            "domain": self.requirement.domain,
            "cedar": self.cedar,
        }


__all__ = ["Policy"]
