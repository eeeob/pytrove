from __future__ import annotations as _annotations

from pytrove._internal._exceptions import _HARD_PROPAGATE


def test_hard_propagate_is_exactly_system_exit_and_keyboard_interrupt() -> None:
    assert _HARD_PROPAGATE == (SystemExit, KeyboardInterrupt)
