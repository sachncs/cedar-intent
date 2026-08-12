"""Shared utility helpers used across cedrus."""

from __future__ import annotations

import binascii
import os
import time


def generate() -> str:
    """Return a unique ``object_id``-style identifier.

    Mirrors the layout used by MongoDB / Stripe / etc.: a hex
    timestamp prefix so the id sorts chronologically, followed by
    eight random bytes for uniqueness across the same tick.

    Returns:
        A 24-character lowercase hex string (8 timestamp chars +
        16 random hex chars).
    """
    timestamp = int(time.time())
    rest = binascii.b2a_hex(os.urandom(8)).decode("ascii")
    return f"{timestamp:x}{rest}"


__all__ = ["generate"]