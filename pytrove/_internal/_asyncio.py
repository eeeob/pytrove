"""Event-loop lookups shared by the async and callable tools."""

from __future__ import annotations as _annotations

import asyncio


def _get_running_loop() -> asyncio.AbstractEventLoop | None:
    """Return the event loop running in the current thread, if there is one.

    Unlike `asyncio.get_running_loop`, this does not raise outside a loop,
    which lets a caller tell "no loop here" apart from a real error.

    Returns:
        The running loop, or `None` when the current thread runs none.
    """
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


__all__ = ("_get_running_loop",)
