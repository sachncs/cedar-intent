"""A policy that has been compiled and validated.

A :class:`Compiled` is the final form produced by
:meth:`~cedrus.space.Space.apply` after the compiler has rendered the
intent and Cedar has accepted the source. The workspace treats a
compiled policy as the authoritative artifact for that requirement
and includes it in subsequent verification, test, and deployment
runs.

Compiled policies are immutable. To produce a new version, build a
:class:`~cedrus.policies.draft.Draft` from the same requirement and
run the apply pipeline again; cedrus does not currently version
policies internally.

Attributes:
    Compiled: Final-form policy carrying both the typed intent and
        the rendered Cedar.

See Also:
    :mod:`cedrus.policies.base`: :class:`Kind` abstract base that
        :class:`Compiled` extends.
    :mod:`cedrus.policies.draft`: The :class:`Draft` form this policy
        started life as before compilation.
    :mod:`cedrus.policies.existing`: The :class:`Existing` form for
        policies imported from raw Cedar source.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from cedrus.compile import Intent
from cedrus.error import Fault
from cedrus.need import Need
from cedrus.schema import Schema
from cedrus.validate import Validator, Vreport
from cedrus.policies.base import Kind


@dataclass(frozen=True, slots=True)
class Compiled(Kind):
    """A policy that has been compiled and successfully validated.

    Overrides :meth:`to_intent` to return the stored typed intent, and
    :meth:`to_dict` to add ``intent_id``. Inherits :meth:`compile`,
    :meth:`validate`, :meth:`test` and :meth:`to_dict` (base form) from
    :class:`Kind`.

    Attributes:
        intent: Typed intent that produced this policy; ``None`` only
            on legacy storage rows that lack intent metadata.
    """

    intent: Intent | None = None

    def kind(self) -> str:
        """Return the policy kind discriminator.

        Returns:
            Always ``"compiled"``.
        """
        return "compiled"

    def to_intent(self) -> Intent:
        """Return the typed intent for this compiled policy.

        Returns:
            The stored :class:`Intent`.

        Raises:
            Fault: If ``intent`` is ``None`` (legacy rows only;
                policies produced by
                :meth:`~cedrus.space.Space.apply` always carry one).
        """
        if self.intent is None:
            raise Fault(f"compiled policy {self.id} is missing intent metadata")
        return self.intent

    def validate(self, schema: Schema) -> Vreport:
        """Validate this policy's Cedar source against ``schema``.

        Polymorphic route: defers to :class:`Validator` (the typed
        validator wrapper around the Cedar engine).

        Args:
            schema: Cedar schema to validate against.

        Returns:
            A :class:`Vreport` describing the outcome.

        Raises:
            Fault: If the policy has no Cedar source.
        """
        if not self.cedar:
            raise Fault(f"compiled policy {self.id} has no Cedar source to validate")
        return Validator(schema).validate([self.cedar])

    def to_dict(self) -> Mapping[str, Any]:
        """Return a JSON-friendly representation of this compiled policy.

        Includes the intent id when present, or ``None`` when the
        policy has no stored intent metadata.

        Returns:
            The base policy dict plus an ``intent_id`` key.
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