"""Typed wrapper for the items a generator could not safely resolve.

Encapsulates the tuple shape and provides merging / appending
operations. Replaces the ``tuple[str, ...]`` previously passed
through the generator pipeline.

All classes are ``@dataclass(frozen=True, slots=True)``.

Attributes:
    Unresolved: Items the generator could not safely resolve.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Unresolved:
    """Items the generator could not safely resolve.

    Behaves like a tuple of strings: supports ``len()``, iteration, and
    truthiness from the underlying items. Empty by default. Use
    :meth:`add` to append a single item and :meth:`merge` to combine
    several sources.

    Attributes:
        items: Tuple of unresolved reference keys; defaults to empty.
    """

    items: tuple[str, ...] = field(default_factory=tuple)

    def __len__(self) -> int:
        """Return the number of unresolved items."""
        return len(self.items)

    def __iter__(self) -> Iterator[str]:
        """Iterate over unresolved items in order."""
        return iter(self.items)

    def __bool__(self) -> bool:
        """Return ``True`` when at least one unresolved item is present."""
        return bool(self.items)

    def add(self, item: str) -> Unresolved:
        """Return a new :class:`Unresolved` with ``item`` appended.

        Args:
            item: Unresolved reference key to append.

        Returns:
            A new :class:`Unresolved` containing all existing items
            followed by ``item``.
        """
        return Unresolved(items=(*self.items, item))

    @classmethod
    def merge(cls, *sources: Sequence[str]) -> Unresolved:
        """Combine several sequences, dropping empties and duplicates.

        Each item is stripped of surrounding whitespace before
        de-duplication; empty strings are ignored.

        Args:
            *sources: Sequences of unresolved reference keys to merge.

        Returns:
            A new :class:`Unresolved` containing the unique,
            non-empty items in first-seen order.
        """
        seen: dict[str, None] = dict.fromkeys(
            stripped
            for source in sources
            for item in source
            if (stripped := item.strip())
        )
        return cls(items=tuple(seen))


__all__ = ["Unresolved"]
