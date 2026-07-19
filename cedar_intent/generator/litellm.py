"""LiteLLM-backed generator.

Calls :func:`litellm.completion` with a structured JSON response format. The
JSON shape is enforced strictly: any deviation raises
:class:`GeneratorError`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import litellm

from ..compiler import PolicyIntent
from ..errors import GeneratorError, ScopeError
from ..requirements import slugify
from ..scopes import ActionScope, ConditionClause, PrincipalScope, ResourceScope
from .base import (
    DraftProposal,
    GenerationContext,
    GenerationResult,
)

SYSTEM_PROMPT = """You are an authorization engineer producing a typed Cedar policy proposal.
Use only entity types, actions, attributes, and namespaces from the supplied Cedar JSON schema.
Return JSON only with exactly this shape:
{
  "intent": {
    "effect": "permit" or "forbid",
    "principal": {
      "kind": "any|type|specific|in_group|is_type",
      "type_name": "...",
      "entity_id": "..."
    },
    "action": {"kind": "any|named|in_group", "name": "...", "group": "..."},
    "resource": {
      "kind": "any|type|specific|in_parent|is_type",
      "type_name": "...",
      "entity_id": "..."
    },
    "when": ["body expressions, each fully self-contained"],
    "unless": ["body expressions, each fully self-contained"]
  },
  "unresolved": ["items the model could not determine safely"]
}
Never invent attributes, entity types, or actions. Items that cannot be safely derived must
appear in unresolved instead of being guessed.
"""


@dataclass(frozen=True, slots=True)
class LiteLLMGenerator:
    """Generator backed by LiteLLM.

    Attributes:
        model: LiteLLM model identifier (for example ``"provider/model"``).
        name: Generator identifier surfaced in provenance metadata.
        timeout: HTTP timeout in seconds for the LiteLLM call.
        retries: Number of LiteLLM-managed retries.
        max_tokens: Maximum tokens the model may generate.
        fallbacks: Optional fallback model identifiers.
    """

    model: str
    name: str = "litellm"
    timeout: float = 60
    retries: int = 2
    max_tokens: int = 4096
    fallbacks: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.model or not self.model.strip():
            raise GeneratorError("LiteLLMGenerator requires a non-empty model name")
        if self.timeout <= 0 or self.max_tokens <= 0:
            raise GeneratorError("LiteLLMGenerator timeouts and max_tokens must be positive")
        if self.retries < 0:
            raise GeneratorError("LiteLLMGenerator retries cannot be negative")

    def generate(self, context: GenerationContext) -> GenerationResult:
        """Call LiteLLM with the structured prompt and parse the response."""
        options: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": self.build_user_prompt(context)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "timeout": self.timeout,
            "num_retries": self.retries,
            "max_tokens": self.max_tokens,
        }
        if self.fallbacks:
            options["fallbacks"] = list(self.fallbacks)
        try:
            response = litellm.completion(**options)
        except Exception as error:
            raise GeneratorError(f"LiteLLM request failed: {error}") from error

        content = self.extract_content(response)
        payload = self.parse_payload(content)
        intent = self.build_intent(payload["intent"], context)
        unresolved = tuple(
            str(item).strip() for item in payload.get("unresolved", []) if item
        )
        proposal = DraftProposal(
            intent=intent,
            unresolved=tuple(item for item in unresolved if item),
            notes={"generator": self.name, "model": self.model},
        )
        return GenerationResult(
            proposal=proposal,
            model=getattr(response, "model", self.model) or self.model,
            request_id=getattr(response, "id", None),
            usage=self.extract_usage(response),
        )

    def build_user_prompt(self, context: GenerationContext) -> str:
        """Build the user-message prompt sent to the model."""
        schema_dump = json.dumps(context.schema.source, sort_keys=True, separators=(",", ":"))
        existing_dump = (
            "\nExisting policies:\n"
            + "\n".join(self.format_existing(intent) for intent in context.existing)
            if context.existing
            else ""
        )
        return (
            f"Cedar JSON schema:\n{schema_dump}\n\n"
            f"Requirement id: {context.requirement.id}\n"
            f"Requirement domain: {context.requirement.domain}\n"
            f"Requirement text: {context.requirement.text}\n"
            f"User-supplied principal: {self.format_principal(context.principal)}\n"
            f"User-supplied action: {self.format_action(context.action)}\n"
            f"User-supplied resource: {self.format_resource(context.resource)}\n"
            f"{existing_dump}"
        )

    def format_existing(self, intent: PolicyIntent) -> str:
        """Render an existing intent as a one-line summary."""
        return (
            f"- id={intent.id} effect={intent.effect} "
            f"principal={intent.principal.kind} action={intent.action.kind} "
            f"resource={intent.resource.kind}"
        )

    def format_principal(self, scope: PrincipalScope) -> str:
        """Render a :class:`PrincipalScope` as a JSON object."""
        return json.dumps(
            {
                "kind": scope.kind,
                "type_name": scope.type_name,
                "entity_id": scope.entity_id,
                "group_type": scope.group_type,
                "group_id": scope.group_id,
            },
            sort_keys=True,
        )

    def format_action(self, scope: ActionScope) -> str:
        """Render an :class:`ActionScope` as a JSON object."""
        return json.dumps(
            {"kind": scope.kind, "name": scope.name, "group": scope.group},
            sort_keys=True,
        )

    def format_resource(self, scope: ResourceScope) -> str:
        """Render a :class:`ResourceScope` as a JSON object."""
        return json.dumps(
            {
                "kind": scope.kind,
                "type_name": scope.type_name,
                "entity_id": scope.entity_id,
                "parent_type": scope.parent_type,
                "parent_id": scope.parent_id,
            },
            sort_keys=True,
        )

    def extract_content(self, response: Any) -> str:
        """Extract the message content from a LiteLLM response."""
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as error:
            raise GeneratorError("LiteLLM returned no message content") from error
        if not isinstance(content, str):
            raise GeneratorError("LiteLLM returned non-text message content")
        return content

    def parse_payload(self, content: str) -> dict[str, Any]:
        """Parse the model's JSON content into a structured payload."""
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as error:
            raise GeneratorError(f"LiteLLM returned invalid JSON: {error}") from error
        if not isinstance(payload, dict) or "intent" not in payload:
            raise GeneratorError("LiteLLM response must contain an 'intent' object")
        intent = payload["intent"]
        if not isinstance(intent, dict):
            raise GeneratorError("LiteLLM 'intent' must be a JSON object")
        return payload

    def build_intent(self, intent_data: dict[str, Any], context: GenerationContext) -> PolicyIntent:
        """Translate the parsed payload into a typed :class:`PolicyIntent`."""
        effect = intent_data.get("effect")
        if effect not in {"permit", "forbid"}:
            raise GeneratorError(f"intent has invalid effect {effect!r}")
        principal = build_principal(intent_data.get("principal") or {})
        action = build_action(intent_data.get("action") or {})
        resource = build_resource(intent_data.get("resource") or {})
        when_clauses = build_clauses(intent_data.get("when") or [])
        unless_clauses = build_clauses(intent_data.get("unless") or [])
        intent_id = f"{context.requirement.domain}-{slugify(context.requirement.id)}"
        return PolicyIntent(
            id=intent_id,
            requirement_id=context.requirement.id,
            effect=effect,
            principal=principal or context.principal,
            action=action or context.action,
            resource=resource or context.resource,
            when_clauses=when_clauses,
            unless_clauses=unless_clauses,
            notes={"generator": self.name},
        )

    def extract_usage(self, response: Any) -> dict[str, int]:
        """Extract integer usage counts from a LiteLLM response."""
        usage = getattr(response, "usage", None)
        if usage is not None and hasattr(usage, "model_dump"):
            usage = usage.model_dump()
        if not isinstance(usage, dict):
            return {}
        result: dict[str, int] = {}
        for key, value in usage.items():
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                result[str(key)] = value
        return result


def build_principal(data: dict[str, Any]) -> PrincipalScope | None:
    """Build a :class:`PrincipalScope` from a parsed JSON object.

    Returns ``None`` when the JSON object is missing required fields or the
    fields cannot construct a valid scope.
    """
    kind = data.get("kind")
    if not isinstance(kind, str):
        return None
    try:
        return PrincipalScope(
            kind=kind,  # type: ignore[arg-type]
            type_name=optional_string(data.get("type_name")),
            entity_id=optional_string(data.get("entity_id")),
            group_type=optional_string(data.get("group_type")),
            group_id=optional_string(data.get("group_id")),
        )
    except ScopeError:
        return None


def build_action(data: dict[str, Any]) -> ActionScope | None:
    """Build an :class:`ActionScope` from a parsed JSON object.

    Returns ``None`` when the JSON object is missing required fields or the
    fields cannot construct a valid scope.
    """
    kind = data.get("kind")
    if not isinstance(kind, str):
        return None
    try:
        return ActionScope(
            kind=kind,  # type: ignore[arg-type]
            name=optional_string(data.get("name")),
            group=optional_string(data.get("group")),
        )
    except ScopeError:
        return None


def build_resource(data: dict[str, Any]) -> ResourceScope | None:
    """Build a :class:`ResourceScope` from a parsed JSON object.

    Returns ``None`` when the JSON object is missing required fields or the
    fields cannot construct a valid scope.
    """
    kind = data.get("kind")
    if not isinstance(kind, str):
        return None
    try:
        return ResourceScope(
            kind=kind,  # type: ignore[arg-type]
            type_name=optional_string(data.get("type_name")),
            entity_id=optional_string(data.get("entity_id")),
            parent_type=optional_string(data.get("parent_type")),
            parent_id=optional_string(data.get("parent_id")),
        )
    except ScopeError:
        return None


def build_clauses(values: Any) -> tuple[ConditionClause, ...]:
    """Build a tuple of :class:`ConditionClause` from a JSON-friendly value."""
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return ()
    clauses: list[ConditionClause] = []
    for value in values:
        if isinstance(value, str) and value.strip():
            clauses.append(ConditionClause(body=value.strip()))
    return tuple(clauses)


def optional_string(value: Any) -> str | None:
    """Return ``None`` for missing or blank string values."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = ["LiteLLMGenerator", "SYSTEM_PROMPT"]
