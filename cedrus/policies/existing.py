"""Imported Cedar policies with no LLM involvement.

A :class:`Existing` represents a Cedar policy that was loaded
from disk rather than drafted by a generator. Examples include
policies committed to a repository before cedrus was adopted,
policies imported from another authorization tool, or pre-existing
policies that ship with an application.

The class carries the raw Cedar source plus an optional parsed
intent. The intent is populated when the workspace has been told to
parse existing policies; without it, :meth:`to_intent` raises
:class:`~cedrus.error.Fault` and the verification pass falls back
to a placeholder intent.

Attributes:
    Existing: Imported Cedar policy with an optional parsed intent.

See Also:
    :mod:`cedrus.policies.base`: :class:`Kind` abstract base that
        :class:`Existing` extends.
    :mod:`cedrus.policies.draft`: The :class:`Draft` form policies
        take before they're compiled.
    :mod:`cedrus.policies.compiled`: The :class:`Compiled` form
        policies take after a successful apply.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from cedrus.compile import Intent
from cedrus.error import Fault
from cedrus.need import Need
from cedrus.policies.base import Kind


@dataclass(frozen=True, slots=True)
class Existing(Kind):
    """A policy imported from existing Cedar source.

    Overrides :meth:`to_intent` to return the optional
    :attr:`parsed_intent`, and :meth:`to_dict` to add the
    ``parsed_intent`` key. Inherits :meth:`compile`, :meth:`validate`,
    :meth:`test` and the base :meth:`to_dict` shape from
    :class:`Kind`.

    Attributes:
        parsed_intent: Optional parsed :class:`Intent`. When
            ``None``, :meth:`to_intent` raises :class:`Fault` and
            the verification pass substitutes a placeholder intent.
    """

    parsed_intent: Intent | None = None

    def kind(self) -> str:
        """Return the policy kind discriminator.

        Returns:
            Always ``"existing"``.
        """
        return "existing"

    def to_intent(self) -> Intent:
        """Return the parsed intent for this existing policy.

        Returns:
            The stored :class:`Intent`.

        Raises:
            Fault: If the policy was imported without parsing.
                Callers can re-import with ``parse_existing=True`` to
                populate the intent.
        """
        if self.parsed_intent is None:
            raise Fault(
                f"existing policy {self.id} has no parsed intent; "
                "re-import with parse_existing=True"
            )
        return self.parsed_intent

    def to_dict(self) -> Mapping[str, Any]:
        """Return a JSON-friendly representation of this existing policy.

        Includes the parsed intent id when present, or ``None`` when
        the policy was imported without parsing.

        Returns:
            The base policy dict plus a ``parsed_intent`` key.
        """
        data = dict(Kind.to_dict(self))
        data["parsed_intent"] = None if self.parsed_intent is None else self.parsed_intent.id
        return data

    @classmethod
    def from_requirement(
        cls,
        requirement: Need,
        cedar: str,
        *,
        parsed_intent: Intent | None = None,
        policy_id: str | None = None,
    ) -> Existing:
        """Build an :class:`Existing` for a requirement with raw Cedar source.

        Args:
            requirement: Originating requirement.
            cedar: Raw Cedar source text.
            parsed_intent: Optional pre-parsed intent. When omitted,
                the policy cannot be introspected until the workspace
                re-imports it with parsing enabled.
            policy_id: Optional explicit identifier. Defaults to
                ``"existing-<requirement.id>"``.

        Returns:
            The constructed :class:`Existing`.
        """
        return cls(
            id=policy_id or f"existing-{requirement.id}",
            requirement=requirement,
            cedar=cedar,
            parsed_intent=parsed_intent,
        )


__all__ = ["Existing"]