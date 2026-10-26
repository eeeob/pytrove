"""The seeded generator behind every device draw."""

from __future__ import annotations as _annotations

import hashlib
import os as _os
import random
from typing import Any


def _rng(unique_id: Any = None) -> random.Random:
    """Build a generator seeded from `unique_id`, or from system entropy.

    Args:
        unique_id: Any value; the same value always gives the same stream.

    Returns:
        The generator.
    """
    if unique_id is None:
        return random.Random(_os.urandom(32))

    if isinstance(unique_id, (bytes, bytearray)):
        seed = unique_id
    else:
        text = unique_id if isinstance(unique_id, str) else str(unique_id)
        seed = text.encode("utf-8")

    return random.Random(int(hashlib.sha256(seed).hexdigest(), 16))


__all__ = ("_rng",)
