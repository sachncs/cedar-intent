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

Lifecycle:
    * :class:`~cedrus.policies.draft.Draft` - the result of a
      generator proposal; carries scope objects and an optional intent.
    * :class:`~cedrus.policies.existing.Existing` - imported from raw
      Cedar source; carries the source and an optional parsed intent.
    * :class:`~cedrus.policies.compiled.Compiled` - the result of a
      successful :meth:`~cedrus.space.Space.apply`; carries the
      intent that produced the Cedar and the formatted source.

Thread safety:
    All policy dataclasses are ``frozen=True, slots=True``. They are
    immutable and safe to share across threads.

Attributes:
    Kind: Abstract base for every policy object in cedrus.

See Also:
    :mod:`cedrus.policies.draft`: :class:`Draft` policy subclass.
    :mod:`cedrus.policies.existing`: :class:`Existing` policy
        subclass.
    :mod:`cedrus.policies.compiled`: :class:`Compiled` policy
        subclass.
    :mod:`cedrus.compile`: :class:`Intent` and the polymorphic
        :meth:`Intent.compile` route this module defers to.
    :mod:`cedrus.validate`: :class:`Validator` and :class:`Vreport`
        this module defers to.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from cedrus.case import Case, Run, Suite
from cedrus.compile import Intent
from cedrus.error import Fault
from cedrus.need import Need
from cedrus.schema import Schema
from cedrus.scope import Action, Principal, Resource
from cedrus.validate import Validator, Vreport


@dataclass(frozen=True, slots=True)
class Kind(ABC):
    """Abstract base for every policy object in cedrus.

    Every policy is one of three kinds — :class:`Draft`,
    :class:`Existing`, :class:`Compiled` — and inherits the four
    stable fields (``id``, :attr:`requirement`, :attr:`cedar`,
    :attr:`created_at`) plus the lifecycle hooks
    (:meth:`kind`, :meth:`to_intent`, :meth:`compile`, :meth:`validate`,
    :meth:`test`, :meth:`to_dict`).

    Attributes:
        id: Policy identifier.
        requirement: The originating requirement.
        cedar: Cedar source text (may be empty for uncompiled policies).
        created_at: Timestamp at which the object was constructed;
            defaults to ``datetime.now(UTC)`` when not provided.
    """

    id: str
    requirement: Need
    cedar: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @abstractmethod
    def kind(self) -> str:
        """Return the policy kind discriminator.

        Subclasses return ``"draft"``, ``"existing"``, or ``"compiled"``.

        Returns:
            One of the three kind discriminator strings.
        """

    def to_intent(self) -> Intent:
        """Return the :class:`Intent` representation of this policy.

        Subclasses must implement intent materialization. The base method
        raises :class:`Fault` to make the contract explicit; this
        signals to callers that the policy does not yet carry a typed
        intent (for example, an :class:`Existing` whose
        :attr:`Existing.parsed_intent` is ``None`).
        """
        raise Fault(
            f"{type(self).__name__}.to_intent() must be implemented by the subclass"
        )

    def intent_for_verification(self) -> Intent:
        """Return the policy's intent, with a placeholder when unavailable.

        Used by verification routines that must inspect every policy
        without triggering :class:`Fault` for unparsed existing
        policies. The placeholder carries no scopes (``any``
        everywhere) and records the missing-intent message in
        ``notes`` so verification still has a typed object to consume.

        Returns:
            The policy's :class:`Intent`, or a placeholder when
            :meth:`to_intent` raises :class:`Fault`.
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

    def validate(self, schema: Schema) -> Vreport:
        """Validate the Cedar source for this policy against ``schema``.

        Polymorphic route: defers to :class:`Validator` (the typed
        validator wrapper around the Cedar engine). Subclass
        :class:`Validator` to swap the underlying engine.

        Args:
            schema: Cedar schema to validate against.

        Returns:
            A :class:`Vreport`.

        Raises:
            Fault: If the policy has no Cedar source yet.
        """
        if not self.cedar:
            raise Fault(f"policy {self.id} has no Cedar source to validate")
        return Validator(schema).validate([self.cedar])

    def test(
        self,
        schema: Schema,
        scenarios: Sequence[Case],
        entities: list[Mapping[str, object]] | None = None,
    ) -> Suite:
        """Run authorization scenarios through the Cedar engine.

        Args:
            schema: Cedar schema for scenario evaluation.
            scenarios: Scenarios to execute against this policy's Cedar.
            entities: Optional entities to expose to the engine.

        Returns:
            A :class:`Suite` summarizing the results.
        """
        return Run(scenarios).evaluate(schema, [self.cedar]).result or Suite(
            passed=True, results=()
        )

    def to_dict(self) -> Mapping[str, object]:
        """Return a JSON-friendly representation of this policy.

        Subclasses extend this with kind-specific fields.

        Returns:
            A dict with the shared ``id``, ``kind``,
            ``requirement_id``, ``domain`` and ``cedar`` keys.
        """
        return {
            "id": self.id,
            "kind": self.kind(),
            "requirement_id": self.requirement.id,
            "domain": self.requirement.domain,
            "cedar": self.cedar,
        }


__all__ = ["Kind"]