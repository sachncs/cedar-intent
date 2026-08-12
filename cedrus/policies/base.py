"""Abstract :class:`Kind` base class and shared helpers.

The :class:`Kind` base class defines the contract every concrete policy
type must satisfy:

* a stable ``id``,
* a :meth:`kind` discriminator returning one of ``"draft"``,
  ``"existing"``, ``"compiled"``,
* a typed :meth:`to_intent` returning a :class:`Intent`,
* a non-raising :meth:`intent_for_verification` for the verification
  pass (returns a placeholder intent rather than propagating
  :class:`Fault`).

Lifecycle
---------

* :class:`Draft` - the result of a generator proposal; carries
  scope objects and an optional intent.
* :class:`Existing` - imported from raw Cedar source; carries
  the source and an optional parsed intent.
* :class:`Compiled` - the result of a successful :meth:`Workspace.apply`;
  carries the intent that produced the Cedar and the formatted source.

Thread safety
-------------

All policy dataclasses are ``frozen=True, slots=True``. They are
immutable and safe to share across threads.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..case import Case, Suite, run_scenarios
from ..compile import Intent, Source, compile_intent
from ..error import Fault
from ..need import Need
from ..schema import Schema
from ..scope import Action, Principal, Resource
from ..validate import Vreport, validate_cedar


@dataclass(frozen=True, slots=True)
class Kind(ABC):
    """Abstract base for every policy object in cedrus.

    Attributes:
        id: Policy identifier.
        requirement: The originating requirement.
        cedar: Cedar source text (may be empty for uncompiled policies).
        created_at: Timestamp at which the object was constructed.
    """

    id: str
    requirement: Need
    cedar: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @abstractmethod
    def kind(self) -> str:
        """Return the policy kind discriminator.

        Subclasses return ``"draft"``, ``"existing"``, or ``"compiled"``.
        """

    def to_intent(self) -> Intent:
        """Return the :class:`Intent` representation of this policy.

        Subclasses must implement intent materialization. The base method
        raises :class:`Fault` to make the contract explicit; this
        signals to callers that the policy does not yet carry a typed
        intent (for example, an :class:`Existing` whose
        :attr:`Existing.parsed_intent` is ``None``).
        """
        raise Fault(
            f"{type(self).__name__}.to_intent() must be implemented by the subclass"
        )

    def intent_for_verification(self) -> Intent:
        """Return the policy's intent, with a placeholder when unavailable.

        Used by verification routines that must inspect every policy
        without triggering :class:`Fault` for unparsed existing
        policies.

        The fallback intent carries no scopes (``any`` everywhere) and a
        note recording the missing-intent message so verification still
        has a typed object to consume.
        """
        try:
            return self.to_intent()
        except Fault as error:
            return Intent(
                id=self.id,
                requirement_id=self.requirement.id,
                effect="permit",
                principal=Principal(),
                action=Action(),
                resource=Resource(),
                notes={"missing_intent": str(error)},
            )

    def compile(self, schema: Schema) -> Source:
        """Compile this policy to Cedar source text using its intent.

        Args:
            schema: Cedar schema. Accepted for interface symmetry with
                :class:`Compiled`; the compiler itself does not
                consult the schema.

        Returns:
            The compiled :class:`Source`.
        """
        return compile_intent(self.to_intent())

    def validate(self, schema: Schema) -> Vreport:
        """Validate the Cedar source for this policy against ``schema``.

        Args:
            schema: Cedar schema to validate against.

        Returns:
            A :class:`Vreport`.

        Raises:
            Fault: If the policy has no Cedar source yet.
        """
        if not self.cedar:
            raise Fault(f"policy {self.id} has no Cedar source to validate")
        return validate_cedar([self.cedar], schema)

    def test(
        self,
        schema: Schema,
        scenarios: list[Case],
        entities: list[Mapping[str, object]] | None = None,
    ) -> Suite:
        """Run authorization scenarios through the Cedar engine.

        Args:
            schema: Cedar schema for scenario evaluation.
            scenarios: Scenarios to execute.
            entities: Optional entities to expose to the engine.

        Returns:
            A :class:`Suite` summarizing the results.
        """
        return run_scenarios(
            [self.cedar],
            list(entities or []),
            scenarios,
            schema=schema,
        )

    def to_dict(self) -> Mapping[str, object]:
        """Return a JSON-friendly representation of this policy.

        Subclasses extend this with kind-specific fields.
        """
        return {
            "id": self.id,
            "kind": self.kind(),
            "requirement_id": self.requirement.id,
            "domain": self.requirement.domain,
            "cedar": self.cedar,
        }


__all__ = ["Kind"]
