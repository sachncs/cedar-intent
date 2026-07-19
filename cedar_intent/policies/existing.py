"""Imported Cedar policies with no LLM involvement.

A :class:`ExistingPolicy` represents a Cedar policy that was loaded
from disk rather than drafted by a generator. Examples include
policies committed to a repository before cedar-intent was adopted,
policies imported from another authorization tool, or pre-existing
policies that ship with an application.

The class carries the raw Cedar source plus an optional parsed
intent. The intent is populated when the workspace has been told to
parse existing policies; without it, :meth:`to_intent` raises
:class:`PolicyError` and the verification pass falls back to a
placeholder intent.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..compiler import PolicyIntent
from ..errors import PolicyError
from ..requirements import Requirement
from .base import Policy


@dataclass(frozen=True, slots=True)
class ExistingPolicy(Policy):
    """A policy imported from existing Cedar source.

    Attributes:
        parsed_intent: Optional parsed :class:`PolicyIntent`. When
            ``None``, :meth:`to_intent` raises :class:`PolicyError`
            and the workspace records the policy as
            ``intent=None`` in the repository.
    """

    parsed_intent: PolicyIntent | None = None

    def kind(self) -> str:
        """Return the policy kind discriminator (``"existing"``)."""
        return "existing"

    def to_intent(self) -> PolicyIntent:
        """Return the parsed intent for this existing policy.

        Raises:
            PolicyError: If the policy was imported without parsing.
                Callers can re-import with ``parse_existing=True`` to
                populate the intent.
        """
        if self.parsed_intent is None:
            raise PolicyError(
                f"existing policy {self.id} has no parsed intent; "
                "re-import with parse_existing=True"
            )
        return self.parsed_intent

    def to_dict(self) -> Mapping[str, Any]:
        """Return a JSON-friendly representation of this existing policy.

        Includes the parsed intent id when present, or ``None`` when
        the policy was imported without parsing.
        """
        data = dict(Policy.to_dict(self))
        data["parsed_intent"] = None if self.parsed_intent is None else self.parsed_intent.id
        return data

    @classmethod
    def from_requirement(
        cls,
        requirement: Requirement,
        cedar: str,
        *,
        parsed_intent: PolicyIntent | None = None,
        policy_id: str | None = None,
    ) -> ExistingPolicy:
        """Build an :class:`ExistingPolicy` for a requirement with raw Cedar source.

        Args:
            requirement: Originating requirement.
            cedar: Raw Cedar source text.
            parsed_intent: Optional pre-parsed intent. When omitted, the
                policy cannot be introspected until the workspace
                re-imports it with parsing enabled.
            policy_id: Optional explicit identifier. Defaults to
                ``"existing-<requirement.id>"``.

        Returns:
            The constructed :class:`ExistingPolicy`.
        """
        return cls(
            id=policy_id or f"existing-{requirement.id}",
            requirement=requirement,
            cedar=cedar,
            parsed_intent=parsed_intent,
        )


__all__ = ["ExistingPolicy"]


__all__ = ["ExistingPolicy"]
