"""Tests for cedrus.utils.id (the project-wide identifier generator)."""
from __future__ import annotations

from cedrus.utils import id


def test_id_returns_unique_value_per_call() -> None:
    assert id() != id()


def test_id_returns_24_char_lowercase_hex() -> None:
    value = id()
    assert len(value) == 24
    assert all(character in "0123456789abcdef" for character in value)


def test_id_has_chronological_prefix() -> None:
    """First 8 chars are a hex unix timestamp; later calls sort >= earlier ones."""
    earlier = id()
    later = id()
    assert int(earlier[:8], 16) <= int(later[:8], 16)


def test_id_distinguishes_rapid_calls() -> None:
    """Multiple calls in the same tick must still differ in the random suffix."""
    seen = {id() for _ in range(50)}
    assert len(seen) == 50


__all__ = []