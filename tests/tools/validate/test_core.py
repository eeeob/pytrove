from __future__ import annotations as _annotations

import functools
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, Union

import pytest

from pytrove.errors import ValidationError
from pytrove.validate_tools import core
from pytrove.validate_tools.core import (
    all_deep,
    all_of,
    any_deep,
    any_of,
    is_container,
    is_instance,
    is_mapping,
    is_sub_container,
    is_sub_mapping,
    is_subclass,
    iscoroutinefunction_wrapped,
    validation,
)


@pytest.mark.parametrize(("obj", "class_info", "expected"), [
    (1, int, True),
    (1, str, False),
    (1, int | str, True),
    (1, Union[str, int], True),  # noqa: UP007 - `typing.Union` is the case under test.
    ("x", (bytes, (Union[int, str],)), True),  # noqa: UP007 - same, nested inside tuples.
    (1.0, (int, (str, bytes)), False),
])
def test_is_instance_accepts_every_spelling_of_a_union(obj: Any, class_info: Any, expected: bool) -> None:
    assert is_instance(obj, class_info) is expected


def test_is_subclass_accepts_every_spelling_of_a_union() -> None:
    assert is_subclass(OrderedDict, Union[list, dict])  # noqa: UP007 - `typing.Union` is the case under test.
    assert is_subclass(bool, (str, int | float))
    assert not is_subclass(str, (int, Union[list, dict]))  # noqa: UP007


def test_is_exception_is_true_only_for_exception_instances() -> None:
    assert core.is_exception(ValueError())
    assert not core.is_exception(ValueError)
    assert not core.is_exception("error")


def test_is_container_accepts_plain_collections() -> None:
    assert is_container([1, 2, 3])
    assert is_container((1, 2, 3))
    assert is_container({1, 2, 3})
    assert is_container({"a": 1})
    assert is_container(range(3))
    assert is_container(x for x in range(2))  # generator expression -> Generator ABC


def test_is_container_accepts_bare_iterator() -> None:
    # Container names Iterator rather than listing filter/enumerate/zip one by
    # one -- those are all Iterators anyway, and neither `filter` nor `zip` is
    # subscriptable at runtime, so `filter[I]` raised TypeError the moment the
    # alias was evaluated. Consequence of the wider member: any single-pass
    # iterator now counts as a container, list_iterator included.
    assert is_container(iter([1, 2]))
    assert is_container(filter(None, [1, 2]))
    assert is_container(enumerate([1, 2]))
    assert is_container(zip([1, 2], "ab"))
    assert is_container(map(str, [1, 2]))


def test_is_container_rejects_not_container_types() -> None:
    # str/bytes/bytearray/memoryview are explicitly excluded even though
    # they are technically iterable, per typings.NotContainer.
    assert not is_container("abc")
    assert not is_container(b"abc")
    assert not is_container(bytearray(b"abc"))
    assert not is_container(memoryview(b"abc"))
    assert not is_container(1)
    assert not is_container(None)


def test_is_mapping() -> None:
    assert is_mapping({"a": 1})
    assert not is_mapping([1, 2])


def test_is_sub_container_and_is_sub_mapping() -> None:
    assert is_sub_container(list)
    assert is_sub_container(dict)
    assert not is_sub_container(str)
    assert not is_sub_container([])
    assert is_sub_mapping(dict)
    assert not is_sub_mapping(list)
    assert not is_sub_mapping({})


async def _coro() -> None:
    """Do nothing, as a coroutine function."""


def _sync() -> None:
    """Do nothing, as a plain function."""


def _wrap(f: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap `f` in a plain function that hides whether it is async."""

    @functools.wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Call `f`."""
        return f(*args, **kwargs)

    return wrapper


def _async_wrap(f: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap `f` in a coroutine function."""

    @functools.wraps(f)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Call `f`."""
        return f(*args, **kwargs)

    return wrapper


def test_iscoroutinefunction_wrapped_sees_through_wrappers() -> None:
    assert iscoroutinefunction_wrapped(_coro)
    assert iscoroutinefunction_wrapped(_wrap(_wrap(_coro)))
    assert not iscoroutinefunction_wrapped(_sync)
    assert not iscoroutinefunction_wrapped(_wrap(_sync))


def test_iscoroutinefunction_wrapped_stops_at_the_first_coroutine_function() -> None:
    assert iscoroutinefunction_wrapped(_async_wrap(_sync))
    assert iscoroutinefunction_wrapped(_wrap(_async_wrap(_sync)))


def test_validation_passes_silently_when_the_condition_holds() -> None:
    assert validation(True, "never raised") is None


def test_validation_raises_a_validation_error_with_the_message() -> None:
    with pytest.raises(ValidationError, match="bad input"):
        validation(False, "bad input")


def test_validation_raises_a_bare_validation_error_without_a_message() -> None:
    with pytest.raises(ValidationError):
        validation(False)


def test_validation_raises_the_given_exception_without_context() -> None:
    error = KeyError("missing")

    with pytest.raises(KeyError) as caught:
        try:
            raise RuntimeError
        except RuntimeError:
            validation(False, error)

    assert caught.value is error
    assert caught.value.__suppress_context__


def test_all_of_and_any_of_are_all_and_any_over_arguments() -> None:
    assert all_of(1, "a", True)
    assert not all_of(1, 0)
    assert all_of()
    assert any_of(0, "", 3)
    assert not any_of(0, "")
    assert not any_of()


def test_all_deep_and_any_deep_flatten_and_skip_none() -> None:
    assert all_deep([1, [2, (3, None)]], 4)
    assert not all_deep([1, [0]])
    assert any_deep([0, [None, ("", 5)]])
    assert not any_deep([0, [None, ""]])
