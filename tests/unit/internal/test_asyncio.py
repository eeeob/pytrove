from __future__ import annotations as _annotations

import asyncio

from pytrove._internal._asyncio import _get_running_loop


def test_get_running_loop_is_none_outside_a_loop() -> None:
    assert _get_running_loop() is None


async def test_get_running_loop_returns_the_current_loop_inside_one() -> None:
    assert _get_running_loop() is asyncio.get_running_loop()
