import asyncio
import inspect
import pytest
from pytrove._internal._optional import _optional_import


def test_optional_import_keeps_coroutine_functions_as_coroutines():
    @_optional_import(("json", "json"))
    async def coro():
        return 1

    assert inspect.iscoroutinefunction(coro)


def test_optional_import_raises_on_await_when_the_package_is_missing():
    @_optional_import(("no_such_package_for_pytrove", "nope"))
    async def coro():
        return 1

    async def run():
        with pytest.raises(ImportError):
            await coro()

    asyncio.run(run())
