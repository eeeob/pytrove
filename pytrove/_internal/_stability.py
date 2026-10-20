"""The default file-stability rule shared by `compress_folder` and `ArchiveJob`."""

from __future__ import annotations as _annotations

import os
from typing import Final

_STABILITY_MIN_SIZE: Final[int] = 1 << 20
"""Bytes below which a file is read straight through, however many retries were asked for.

Reading a smaller file is already too quick for a concurrent edit to
realistically land inside it, so guarding it would cost more than it saves.
"""


def _default_stability_check(st: os.stat_result, path: str) -> bool:
    """Decide whether a file is large enough to be worth guarding against concurrent edits.

    It is what `stability_check` defaults to, and stays an ordinary function
    so a caller can extend it rather than replace it:
    `lambda st, path: _default_stability_check(st, path) or path.endswith(".db")`.

    Args:
        st: The file's `os.stat_result`.
        path: The file's path. It is unused here, but part of the callback signature.

    Returns:
        `True` when the file is at least `_STABILITY_MIN_SIZE` bytes long.
    """
    del path  # The callback signature passes it; size alone decides here.
    return st.st_size >= _STABILITY_MIN_SIZE


__all__ = (
    "_default_stability_check",
    "_STABILITY_MIN_SIZE",
)
