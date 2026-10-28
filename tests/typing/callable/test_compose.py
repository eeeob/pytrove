"""Static checks of the `call_all`, `juxt` and `return_constant` overloads.

`make typecheck` runs `ty` on this file. Each `assert_type` fails `ty` when an
overload resolves to another type; the tests also run under pytest, so every call
is valid at runtime too.
"""

from __future__ import annotations as _annotations

import asyncio
import sys

from pytrove.callable_tools import call_all, juxt, return_constant

if sys.version_info >= (3, 11):
    from typing import assert_type
else:
    from typing_extensions import assert_type


def _one(x: int) -> int:
    """Return `x`."""
    return x


async def _aone(x: int) -> int:
    """Return `x`, asynchronously."""
    return x


def _int() -> int:
    """Return an `int`."""
    return 1


def _text() -> str:
    """Return a `str`."""
    return "x"


def test_call_all_and_its_lazy_chain() -> None:
    assert_type(call_all(_int, _int), tuple[int, ...])
    lazy = call_all(_int, lazy=True)
    assert_type(lazy(_text), tuple[int | str, ...])
    assert_type(lazy(_text, lazy=True)(_int), tuple[int | str, ...])


def test_juxt_takes_functions_with_different_signatures() -> None:
    assert_type(juxt(str.upper, len)("ab"), tuple[str | int, ...])


def test_return_constant_overloads() -> None:
    assert_type(return_constant(_one)(1), None)
    assert_type(return_constant(_one, value=_text())(1), str)
    assert_type(asyncio.run(return_constant(_aone)(1)), None)
    assert_type(asyncio.run(return_constant(_aone, value=_text())(1)), str)
    assert_type(return_constant()(_one)(1), None)
    assert_type(return_constant(value=_text())(_one)(1), str)
    assert_type(asyncio.run(return_constant(value=_text())(_aone)(1)), str)
