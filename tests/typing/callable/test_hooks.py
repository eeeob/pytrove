"""Static checks of the `middleware` overloads: `make typecheck` runs `ty` on this file.

Each `assert_type` fails `ty` when an overload resolves to another type; the tests
also run under pytest, so every call is valid at runtime too.
"""

from __future__ import annotations as _annotations

import asyncio
import sys
from typing import Any

import pytest

from pytrove.callable_tools import middleware

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


def _before(x: int) -> None:
    """Accept `x` and do nothing."""


def _on_error(exc: BaseException, x: int) -> str:
    """Recover with the exception's name."""
    return type(exc).__name__


async def _aon_error(exc: BaseException, x: int) -> str:
    """Recover with the exception's name, asynchronously."""
    return type(exc).__name__


def _after(result: int | str, x: int) -> bytes:
    """Encode the result."""
    return str(result).encode()


async def _aafter(result: int | str, x: int) -> bytes:
    """Encode the result, asynchronously."""
    return str(result).encode()


def test_middleware_direct_sync_overloads() -> None:
    assert_type(middleware(_one)(1), int)
    assert_type(middleware(_one, before=_before)(1), int)
    assert_type(middleware(_one, on_error=_on_error)(1), int | str)
    assert_type(middleware(_one, after=_after)(1), bytes)
    assert_type(middleware(_one, on_error=_on_error, after=_after)(1), bytes)


def test_middleware_direct_async_overloads() -> None:
    assert_type(asyncio.run(middleware(_aone)(1)), int)
    assert_type(asyncio.run(middleware(_aone, before=_before)(1)), int)
    assert_type(asyncio.run(middleware(_aone, on_error=_on_error)(1)), int | str)
    assert_type(asyncio.run(middleware(_aone, on_error=_aon_error)(1)), int | str)
    assert_type(asyncio.run(middleware(_aone, after=_after)(1)), bytes)
    assert_type(asyncio.run(middleware(_aone, after=_aafter)(1)), bytes)
    assert_type(asyncio.run(middleware(_aone, on_error=_aon_error, after=_aafter)(1)), bytes)


def test_middleware_decorator_overloads() -> None:
    assert_type(middleware(before=_before)(_one)(1), int)
    assert_type(middleware(on_error=_on_error)(_one)(1), int | str)
    assert_type(asyncio.run(middleware(on_error=_on_error)(_aone)(1)), int | str)
    assert_type(asyncio.run(middleware(on_error=_aon_error)(_aone)(1)), int | str)
    assert_type(middleware(after=_after)(_one)(1), bytes)
    assert_type(asyncio.run(middleware(after=_after)(_aone)(1)), bytes)
    assert_type(asyncio.run(middleware(after=_aafter)(_aone)(1)), bytes)


def test_middleware_decorator_overloads_with_on_error_and_after() -> None:
    assert_type(middleware(on_error=_on_error, after=_after)(_one)(1), bytes)
    assert_type(asyncio.run(middleware(on_error=_on_error, after=_after)(_aone)(1)), bytes)
    assert_type(asyncio.run(middleware(on_error=_aon_error, after=_after)(_aone)(1)), bytes)
    assert_type(asyncio.run(middleware(on_error=_on_error, after=_aafter)(_aone)(1)), bytes)
    assert_type(asyncio.run(middleware(on_error=_aon_error, after=_aafter)(_aone)(1)), bytes)


def test_type_test_helpers_are_valid_at_runtime() -> None:
    hooks: tuple[Any, ...] = (_before(1), _on_error(KeyError(), 1), _after(1, 1))
    assert hooks == (None, "KeyError", b"1")
    assert asyncio.run(_aon_error(KeyError(), 1)) == "KeyError"
    assert asyncio.run(_aafter("a", 1)) == b"a"


def test_overloads_reject_an_async_hook_on_a_sync_function() -> None:
    # Each call below must fail `ty`; an ignore that suppresses nothing is itself reported.
    with pytest.raises(TypeError, match="is async"):
        middleware(on_error=_aon_error)(_one)  # ty: ignore[invalid-argument-type]  # Async hook, sync function.

    with pytest.raises(TypeError, match="is async"):
        middleware(after=_aafter)(_one)  # ty: ignore[invalid-argument-type]  # Async hook, sync function.
