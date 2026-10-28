"""Static checks of the `safe_call` overloads: `make typecheck` runs `ty` on this file.

Each `assert_type` fails `ty` when an overload resolves to another type; the tests
also run under pytest, so every call is valid at runtime too.
"""

from __future__ import annotations as _annotations

import sys

import pytest

from pytrove.callable_tools import safe_call

if sys.version_info >= (3, 11):
    from typing import assert_type
else:
    from typing_extensions import assert_type


def test_safe_call_flag_overloads() -> None:
    assert_type(safe_call(int, "1"), int | None)
    assert_type(safe_call(int, "1", raise_exc=True), int)
    assert_type(safe_call(int, "1", return_exc=True), int | BaseException)
    assert_type(safe_call(int, "1", return_exc=True, include_exc=ValueError), int | ValueError)
    assert_type(
        safe_call(int, "1", return_exc=True, include_exc=(ValueError, KeyError)),
        int | ValueError | KeyError,
    )


def test_overloads_reject_both_flags() -> None:
    # The call below must fail `ty`; an ignore that suppresses nothing is itself reported.
    with pytest.raises(TypeError, match="cannot both be True"):
        safe_call(int, "1", return_exc=True, raise_exc=True)  # ty: ignore[no-matching-overload]  # Both flags.
