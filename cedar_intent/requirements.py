"""Requirement model and Markdown loader.

A :class:`Requirement` is the source-of-truth unit that ties a natural
language description to a stable identifier. Identifiers are read from
YAML-style front matter at the top of a Markdown file, with the filename
stem as a fallback.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .errors import RequirementError


@dataclass(frozen=True, slots=True)
class Requirement:
    """An atomic authorization requirement loaded from disk.

    Attributes:
        id: Stable identifier for the requirement (for example ``HR-042``).
        text: Full body text of the requirement.
        domain: Logical authorization domain the requirement belongs to.
        source_path: Path of the Markdown file the requirement was loaded from.
        created_at: Timestamp at which the requirement object was constructed.
    """

    id: str
    text: str
    domain: str
    source_path: Path
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise RequirementError("requirement id must be non-empty")
        if not self.text or not self.text.strip():
            raise RequirementError(f"requirement {self.id} has no body text")
        if not self.domain or not self.domain.strip():
            raise RequirementError(f"requirement {self.id} has no domain")


def parse_front_matter(source: str) -> tuple[Mapping[str, str], str]:
    """Split a Markdown document into ``(front_matter, body)``.

    The front matter is a YAML-like block delimited by ``---`` lines at the
    top of the file. Only ``key: value`` pairs are supported; nested YAML and
    JSON blocks are not interpreted.

    Args:
        source: Full Markdown document text.

    Returns:
        A tuple of ``(front_matter, body)``. ``front_matter`` is a mapping of
        string keys to string values; ``body`` is the trimmed remainder of
        the document after the front matter.
    """
    body = source.strip()
    if not body.startswith("---"):
        return {}, body
    lines = body.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, body
    end_index: int | None = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index is None:
        return {}, body
    front_matter: dict[str, str] = {}
    for line in lines[1:end_index]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise RequirementError(f"malformed front matter line: {line!r}")
        key, _, value = stripped.partition(":")
        front_matter[key.strip()] = value.strip().strip('"').strip("'")
    rest = "\n".join(lines[end_index + 1 :]).strip()
    return front_matter, rest


def slugify(text: str) -> str:
    """Return a deterministic kebab-case slug for ``text``.

    Non-alphanumeric characters are replaced with single hyphens and the
    result is stripped of leading and trailing hyphens.
    """
    lowered = "".join(character.lower() if character.isalnum() else "-" for character in text)
    while "--" in lowered:
        lowered = lowered.replace("--", "-")
    return lowered.strip("-")


def derive_domain(source_path: Path, workspace_root: Path) -> str:
    """Return the domain for a requirement file based on its directory layout.

    The first directory below ``workspace_root`` is treated as the domain
    name. Files placed directly under the workspace root fall back to
    ``"default"``.
    """
    relative = source_path.resolve().relative_to(workspace_root.resolve())
    parts = relative.parts
    if len(parts) <= 1:
        return "default"
    return parts[0]


def load_requirement(path: Path, workspace_root: Path | None = None) -> Requirement:
    """Load a single requirement from a Markdown file.

    Args:
        path: Path to the Markdown file.
        workspace_root: Optional workspace root used to derive the domain
            when the front matter does not provide one.

    Returns:
        The parsed :class:`Requirement`.

    Raises:
        RequirementError: If the file is missing, empty, or malformed.
    """
    if not path.exists() or not path.is_file():
        raise RequirementError(f"requirement file not found: {path}")
    raw = path.read_text(encoding="utf-8")
    front_matter, body = parse_front_matter(raw)
    if not body:
        raise RequirementError(f"requirement file has empty body: {path}")
    requirement_id = front_matter.get("id") or path.stem
    domain = front_matter.get("domain")
    if not domain and workspace_root is not None:
        domain = derive_domain(path, workspace_root)
    if not domain:
        raise RequirementError(f"requirement {requirement_id} has no domain")
    return Requirement(
        id=requirement_id,
        text=body,
        domain=domain,
        source_path=path,
        created_at=datetime.now(UTC),
    )


def load_requirements(directory: Path, workspace_root: Path | None = None) -> list[Requirement]:
    """Load every ``*.md`` requirement in ``directory`` non-recursively.

    Args:
        directory: Directory to scan for requirement files.
        workspace_root: Optional workspace root forwarded to
            :func:`load_requirement` for domain derivation.

    Returns:
        A sorted list of :class:`Requirement` objects.

    Raises:
        RequirementError: If ``directory`` does not exist.
    """
    if not directory.exists() or not directory.is_dir():
        raise RequirementError(f"requirement directory not found: {directory}")
    requirements: list[Requirement] = []
    for path in sorted(directory.glob("*.md")):
        requirements.append(load_requirement(path, workspace_root))
    return requirements


def render_requirement(requirement: Requirement) -> str:
    """Render a requirement back to Markdown form with front matter."""
    return (
        "---\n"
        f"id: {requirement.id}\n"
        f"domain: {requirement.domain}\n"
        "---\n\n"
        f"{requirement.text.strip()}\n"
    )


__all__ = [
    "Requirement",
    "derive_domain",
    "load_requirement",
    "load_requirements",
    "parse_front_matter",
    "render_requirement",
    "slugify",
]
