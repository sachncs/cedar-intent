"""Need model and Markdown loader.

A :class:`Need` is the source-of-truth unit that ties a natural
language description to a stable identifier. Identifiers are read from
YAML-style front matter at the top of a Markdown file, with the
filename stem as a fallback.

Why a custom loader instead of PyYAML:
    Front matter is intentionally limited to ``key: value`` pairs. This
    keeps the parser dependency-free, makes Markdown requirements diff-
    friendly in pull requests, and forces the schema to be flat. Nested
    structures (lists, maps) belong in the Cedar schema, not in the
    requirement front matter.

Attributes:
    Need: An atomic authorization requirement loaded from disk.
    parse_front_matter: Split a Markdown document into front matter + body.
    slugify: Build a deterministic kebab-case slug from ``text``.
    derive_domain: Derive the domain name from a requirement file path.
    load_requirement: Load a single requirement from a Markdown file.
    load_requirements: Load every ``*.md`` requirement in a directory.
    render_requirement: Render a :class:`Need` back to Markdown form.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cedrus.error import Require

if TYPE_CHECKING:
    from cedrus.store.sqlite import Backend


@dataclass(frozen=True, slots=True)
class Need:
    """An atomic authorization requirement loaded from disk.

    Attributes:
        id: Stable identifier for the requirement (for example
            ``HR-042``).
        text: Full body text of the requirement.
        domain: Logical authorization domain the requirement belongs to.
        source_path: Path of the Markdown file the requirement was
            loaded from.
        created_at: Timestamp at which the requirement object was
            constructed.
    """

    id: str
    text: str
    domain: str
    source_path: Path
    created_at: datetime

    def __post_init__(self) -> None:
        """Validate the typed fields.

        Raises:
            Require: When ``id``, ``text`` or ``domain`` is empty.
        """
        if not self.id or not self.id.strip():
            raise Require("requirement id must be non-empty")
        if not self.text or not self.text.strip():
            raise Require(f"requirement {self.id} has no body text")
        if not self.domain or not self.domain.strip():
            raise Require(f"requirement {self.id} has no domain")

    @classmethod
    def parse(cls, row: dict[str, Any]) -> Need:
        """Build a :class:`Need` from a SQLite ``requirements`` row dict.

        Args:
            row: Dict produced by ``SELECT * FROM requirements``.

        Returns:
            The reconstructed :class:`Need`.
        """
        return cls(
            id=row["id"],
            text=row["text"],
            domain=row["domain"],
            source_path=Path(row["source_path"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def to_data(self) -> dict[str, Any]:
        """Return the ``requirements`` row dict for this :class:`Need`.

        Returns:
            A dict keyed by ``requirements`` column name.
        """
        return {
            "id": self.id,
            "domain": self.domain,
            "text": self.text,
            "source_path": str(self.source_path),
            "created_at": self.created_at.isoformat(),
        }

    def save(self, repo: Backend) -> None:
        """Persist this :class:`Need` (insert or replace by ``id``).

        Args:
            repo: Storage backend to write through.
        """
        with repo.transaction():
            repo.execute(
                """
                INSERT OR REPLACE INTO requirements
                    (id, domain, text, source_path, created_at)
                VALUES (:id, :domain, :text, :source_path, :created_at)
                """,
                self.to_data(),
            )

    @classmethod
    def get(cls, repo: Backend, requirement_id: str) -> Need:
        """Load the requirement with ``requirement_id``.

        Args:
            repo: Storage backend to read from.
            requirement_id: Identifier of the requirement to fetch.

        Returns:
            The stored :class:`Need`.

        Raises:
            Require: If no requirement exists with that id.
        """
        rows = repo.fetch(
            "SELECT * FROM requirements WHERE id = ?",
            (requirement_id,),
        )
        if not rows:
            raise Require(f"requirement {requirement_id!r} not found")
        return cls.parse(rows[0])

    @classmethod
    def list(
        cls,
        repo: Backend,
        *,
        domain: str | None = None,
    ) -> Sequence[Need]:
        """Load all requirements, optionally filtered by ``domain``.

        Args:
            repo: Storage backend to read from.
            domain: When provided, only requirements whose ``domain``
                attribute matches are returned.

        Returns:
            A sequence of :class:`Need` objects in id order.
        """
        if domain is None:
            rows = repo.fetch("SELECT * FROM requirements ORDER BY id")
        else:
            rows = repo.fetch(
                "SELECT * FROM requirements WHERE domain = ? ORDER BY id",
                (domain,),
            )
        return [cls.parse(row) for row in rows]


def parse_front_matter(source: str) -> tuple[Mapping[str, str], str]:
    """Split a Markdown document into ``(front_matter, body)``.

    The front matter is a YAML-like block delimited by ``---`` lines at
    the top of the file. Only ``key: value`` pairs are supported;
    nested YAML and JSON blocks are not interpreted.

    Args:
        source: Full Markdown document text.

    Returns:
        A tuple of ``(front_matter, body)``. ``front_matter`` is a
        mapping of string keys to string values; ``body`` is the
        trimmed remainder of the document after the front matter.
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
            raise Require(f"malformed front matter line: {line!r}")
        key, _, value = stripped.partition(":")
        front_matter[key.strip()] = value.strip().strip('"').strip("'")
    rest = "\n".join(lines[end_index + 1 :]).strip()
    return front_matter, rest


def slugify(text: str) -> str:
    """Return a deterministic kebab-case slug for ``text``.

    Non-alphanumeric characters are replaced with single hyphens and
    the result is stripped of leading and trailing hyphens.

    Args:
        text: Arbitrary text to slugify.

    Returns:
        A kebab-case slug string.
    """
    lowered = "".join(
        character.lower() if character.isalnum() else "-" for character in text
    )
    while "--" in lowered:
        lowered = lowered.replace("--", "-")
    return lowered.strip("-")


def derive_domain(source_path: Path, workspace_root: Path) -> str:
    """Return the domain for a requirement file based on its directory layout.

    The first directory below ``workspace_root`` is treated as the
    domain name. Files placed directly under the workspace root fall
    back to ``"default"``.

    Args:
        source_path: Path to the requirement file.
        workspace_root: Workspace root path.

    Returns:
        The domain name, or ``"default"`` when the file is at the
        workspace root.
    """
    relative = source_path.resolve().relative_to(workspace_root.resolve())
    parts = relative.parts
    if len(parts) <= 1:
        return "default"
    return parts[0]


def load_requirement(path: Path, workspace_root: Path | None = None) -> Need:
    """Load a single requirement from a Markdown file.

    Args:
        path: Path to the Markdown file.
        workspace_root: Optional workspace root used to derive the
            domain when the front matter does not provide one.

    Returns:
        The parsed :class:`Need`.

    Raises:
        Require: If the file is missing, empty, or malformed.
    """
    if not path.exists() or not path.is_file():
        raise Require(f"requirement file not found: {path}")
    raw = path.read_text(encoding="utf-8")
    front_matter, body = parse_front_matter(raw)
    if not body:
        raise Require(f"requirement file has empty body: {path}")
    requirement_id = front_matter.get("id") or path.stem
    domain = front_matter.get("domain")
    if not domain and workspace_root is not None:
        domain = derive_domain(path, workspace_root)
    if not domain:
        raise Require(f"requirement {requirement_id} has no domain")
    return Need(
        id=requirement_id,
        text=body,
        domain=domain,
        source_path=path,
        created_at=datetime.now(UTC),
    )


def load_requirements(
    directory: Path, workspace_root: Path | None = None
) -> list[Need]:
    """Load every ``*.md`` requirement in ``directory`` non-recursively.

    Args:
        directory: Directory to scan for requirement files.
        workspace_root: Optional workspace root forwarded to
            :func:`load_requirement` for domain derivation.

    Returns:
        A sorted list of :class:`Need` objects.

    Raises:
        Require: If ``directory`` does not exist.
    """
    if not directory.exists() or not directory.is_dir():
        raise Require(f"requirement directory not found: {directory}")
    requirements: list[Need] = []
    for path in sorted(directory.glob("*.md")):
        requirements.append(load_requirement(path, workspace_root))
    return requirements


def render_requirement(requirement: Need) -> str:
    """Render a requirement back to Markdown form with front matter.

    Args:
        requirement: The :class:`Need` to render.

    Returns:
        A Markdown document string with ``id`` / ``domain`` front
        matter and the requirement body.
    """
    return (
        "---\n"
        f"id: {requirement.id}\n"
        f"domain: {requirement.domain}\n"
        "---\n\n"
        f"{requirement.text.strip()}\n"
    )


__all__ = [
    "Need",
    "derive_domain",
    "load_requirement",
    "load_requirements",
    "parse_front_matter",
    "render_requirement",
    "slugify",
]
