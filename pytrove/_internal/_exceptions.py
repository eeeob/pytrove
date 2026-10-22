"""Exception constants shared by the sync and async call wrappers."""

from __future__ import annotations as _annotations

from typing import Final

_HARD_PROPAGATE: Final[tuple[type[SystemExit], type[KeyboardInterrupt]]] = (
    SystemExit,
    KeyboardInterrupt,
)
"""Exceptions that `safe_call`, `asafe_call` and `middleware` always let propagate.

There is no way to opt back in, so `exclude_exc` can never usefully name them.
"""

__all__ = ("_HARD_PROPAGATE",)
