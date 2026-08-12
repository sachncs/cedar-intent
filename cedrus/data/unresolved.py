"""Typed wrapper for the items a generator could not safely resolve.

Encapsulates the tuple shape and provides merging / appending
operations. Replaces the ``tuple[str, ...]`` previously passed
through the generator pipeline.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Unresolved:
    """Items the generator could not safely resolve.

    Empty by default. Use :meth:`add` to append a single item and
    :meth:`merge` to combine several sources.
    """

    items: tuple[str, ...] = field(default_factory=tuple)

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self) -> Iterator[str]:
        return iter(self.items)

    def __bool__(self) -> bool:
        return bool(self.items)

    def add(self, item: str) -> Unresolved:
        """Return a new :class:`Unresolved` with ``item`` appended."""
        return Unresolved(items=(*self.items, item))

    @classmethod
    def merge(cls, *sources: Sequence[str]) -> Unresolved:
        """Combine several sequences, dropping empties and duplicates."""
        seen: dict[str, None] = {}
        for source in sources:
            for item in source:
                stripped = item.strip()
                if stripped and stripped not in seen:
                    seen[stripped] = None
        return cls(items=tuple(seen.keys()))


__all__ = ["Unresolved"]
