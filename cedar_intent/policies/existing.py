"""Imported Cedar policies with no LLM involvement."""

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
        parsed_intent: Optional parsed :class:`PolicyIntent`. When ``None``,
            :meth:`to_intent` raises :class:`PolicyError`.
    """

    parsed_intent: PolicyIntent | None = None

    def kind(self) -> str:
        """Return the policy kind discriminator."""
        return "existing"

    def to_intent(self) -> PolicyIntent:
        if self.parsed_intent is None:
            raise PolicyError(
                f"existing policy {self.id} has no parsed intent; "
                "re-import with parse_existing=True"
            )
        return self.parsed_intent

    def to_dict(self) -> Mapping[str, Any]:
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
        """Build an :class:`ExistingPolicy` for a requirement with raw Cedar source."""
        return cls(
            id=policy_id or f"existing-{requirement.id}",
            requirement=requirement,
            cedar=cedar,
            parsed_intent=parsed_intent,
        )


__all__ = ["ExistingPolicy"]
