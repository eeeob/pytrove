from __future__ import annotations as _annotations

import pytest

from pytrove._internal._exceptions import _HARD_PROPAGATE, _check_swallow_options, _is_swallowed


def test_hard_propagate_is_exactly_system_exit_and_keyboard_interrupt() -> None:
    assert _HARD_PROPAGATE == (SystemExit, KeyboardInterrupt)


def test_check_swallow_options_accepts_the_valid_combinations() -> None:
    _check_swallow_options("who", True, False, None)
    _check_swallow_options("who", False, True, (ValueError, KeyError))
    _check_swallow_options("who", False, False, OSError)


def test_check_swallow_options_refuses_both_flags_naming_the_caller() -> None:
    with pytest.raises(TypeError, match=r"^who: return_exc and raise_exc cannot both be True"):
        _check_swallow_options("who", True, True, None)


@pytest.mark.parametrize(
    "exclude_exc", [SystemExit, KeyboardInterrupt, (ValueError, KeyboardInterrupt)]
)
def test_check_swallow_options_refuses_a_hard_propagating_exclusion(
    exclude_exc: type[BaseException] | tuple[type[BaseException], ...],
) -> None:
    with pytest.raises(TypeError, match="always propagates already"):
        _check_swallow_options("who", False, False, exclude_exc)


@pytest.mark.parametrize(
    ("include_exc", "exclude_exc", "swallowed"),
    [
        (None, None, True),
        (ValueError, None, True),
        (KeyError, None, False),
        ((KeyError, ValueError), None, True),
        (None, ValueError, False),
        (None, KeyError, True),
        (ValueError, ValueError, False),  # `exclude_exc` wins
        (Exception, (KeyError, ValueError), False),
    ],
)
def test_is_swallowed_applies_include_then_lets_exclude_win(
    include_exc: type[BaseException] | tuple[type[BaseException], ...] | None,
    exclude_exc: type[BaseException] | tuple[type[BaseException], ...] | None,
    swallowed: bool,
) -> None:
    assert _is_swallowed(ValueError("x"), include_exc, exclude_exc) is swallowed
