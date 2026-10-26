from __future__ import annotations as _annotations

import itertools
import sys
from collections import UserString
from collections.abc import Generator, Iterable, Iterator
from enum import Enum
from typing import Any, Generic, TypeVar

import pytest

from pytrove import (
    flat_cont,
    flat_cont_by,
    flat_map,
    iter_flat_cont,
    iter_flat_cont_by,
    iter_flat_map,
)

_T = TypeVar("_T")


def test_flat_cont_ignores_none_entries() -> None:
    assert flat_cont([1, None, 2, None, [3, None]]) == [1, 2, 3]


def test_flat_cont_deeply_nested() -> None:
    nested = [1, [2, [3, [4, [5]]]]]
    assert flat_cont(nested) == [1, 2, 3, 4, 5]


def test_flat_cont_treats_strings_as_atomic() -> None:
    # `str` is explicitly excluded from `Container` (`NotContainer`), so it must
    # not be exploded into individual characters.
    assert flat_cont(["ab", ["cd"]]) == ["ab", "cd"]


def test_flat_cont_multiple_container_args() -> None:
    assert flat_cont([1, 2], [3, 4], None) == [1, 2, 3, 4]


def test_flat_cont_keeps_none_when_asked() -> None:
    assert flat_cont([1, None, 2, [3, None]], exclude_none=False) == [1, None, 2, 3, None]


def test_flat_cont_excludes_none_by_default() -> None:
    # The default is the long-standing behaviour, unchanged by adding the
    # option to keep `None`.
    assert flat_cont([1, None, 2]) == [1, 2]


def test_flat_cont_flattens_nested_containers() -> None:
    # This is the exact call shape (`flat_cont(container.values())`) that runs
    # at module import time in `tg_tools` -- a regression here breaks
    # `import pytrove` entirely, which is exactly what happened pre-fix on
    # Python versions where `isinstance()` rejects a bare `typing.Union`.
    assert flat_cont([1, [2, [3, None]], (4,)]) == [1, 2, 3, 4]
    assert flat_cont(None) == []
    assert set(flat_cont({1, 2}, [3, 4])) == {1, 2, 3, 4}


class _Box(Iterable[_T], Generic[_T]):
    """A container the built-in `is_container` does not recognise.

    It is not a `Collection`, an `Iterator`, a `Sequence` or a `Mapping`, so it
    can only be unwrapped by a caller-supplied predicate. `flat_cont_by` types
    its leaves `Any`, since the predicate decides the depth.
    """

    def __init__(self, *items: _T) -> None:
        self.items = items

    def __iter__(self) -> Iterator[_T]:
        return iter(self.items)


def _is_box(x: object) -> bool:
    return isinstance(x, _Box)


def test_flat_cont_by_uses_the_given_predicate_instead_of_is_container() -> None:
    assert flat_cont_by(_Box(1, 2, [3, 4]), is_container=_is_box) == [1, 2, [3, 4]]


def test_flat_cont_by_applies_the_predicate_at_every_depth() -> None:
    nested = _Box(1, _Box(2, _Box(3)), 4)
    assert flat_cont_by(nested, is_container=_is_box) == [1, 2, 3, 4]


def test_flat_cont_by_ignores_what_the_default_predicate_would_have_unwrapped() -> None:
    # A plain list is not a `_Box`, so under this predicate it is a leaf --
    # the opposite of what `flat_cont` would do with it.
    assert flat_cont_by([1, [2, 3]], is_container=_is_box) == [[1, [2, 3]]]


def test_flat_cont_by_defaults_to_is_container() -> None:
    assert flat_cont_by([1, None, 2, [3, None]]) == [1, 2, 3]


def test_flat_cont_by_ignores_none_entries() -> None:
    assert flat_cont_by(_Box(1, None, 2), is_container=_is_box) == [1, 2]


def test_flat_cont_by_keeps_none_when_asked() -> None:
    assert flat_cont_by(_Box(1, None, 2), is_container=_is_box, exclude_none=False) == [1, None, 2]


def test_iter_flat_cont_is_a_generator() -> None:
    result = iter_flat_cont([1, [2, None]], 3)
    assert list(result) == [1, 2, 3]
    assert list(result) == []  # exhausted, like any generator


def test_iter_flat_cont_matches_iter_flat_cont_by_with_the_default_predicate() -> None:
    data = ([1, (2, None)], {"a": 1}, "xy", None)
    for exclude_none in (True, False):
        assert list(iter_flat_cont(*data, exclude_none=exclude_none)) == list(
            iter_flat_cont_by(*data, exclude_none=exclude_none)
        )


def test_iter_flat_cont_by_is_a_generator() -> None:
    result = iter_flat_cont_by(_Box(1, 2), is_container=_is_box)
    assert list(result) == [1, 2]
    assert list(result) == []  # exhausted, like any generator


def test_flat_cont_by_accepts_a_type_guard_predicate() -> None:
    # `TypeGuard`/`TypeIs` return types are subtypes of `bool`, so a narrowing
    # predicate is accepted wherever a plain `bool` one is; the leaves stay `Any`.
    if sys.version_info >= (3, 13):
        from typing import TypeIs  # noqa: PLC0415 - `typing.TypeIs` exists only from 3.13
    else:
        from typing import TypeGuard as TypeIs  # noqa: PLC0415 - the pre-3.13 stand-in for `TypeIs`

    def is_box(x: Any) -> TypeIs[_Box[Any]]:
        return isinstance(x, _Box)

    assert flat_cont_by(_Box(1, _Box(2, 3)), is_container=is_box) == [1, 2, 3]


def test_a_narrowing_predicate_really_does_stop_at_the_first_layer() -> None:
    # The predicate alone decides the depth, as the docstring says: one that
    # refuses what `is_container` would have taken leaves the inner structure whole.
    nested = [1, [2, 3]]

    assert flat_cont_by(nested, is_container=_is_box) == [nested]


def test_flat_map_yields_both_keys_and_values() -> None:
    # `flat_cont` walks a mapping's keys alone -- iterating a dict does that,
    # and `flat_cont` has no special case for one. This is the special case:
    # both sides come out.
    assert flat_map({"a": 1, "b": 2}) == ["a", 1, "b", 2]


def test_flat_map_recurses_into_a_nested_mapping() -> None:
    assert flat_map({"a": {"b": 2}}) == ["a", "b", 2]


def test_flat_map_recurses_into_a_mapping_reached_through_a_container() -> None:
    assert flat_map([1, {"a": 2}, 3]) == [1, "a", 2, 3]


def test_flat_map_still_flattens_a_plain_container() -> None:
    assert flat_map([1, [2, 3], None]) == [1, 2, 3]


def test_iter_flat_map_is_a_generator() -> None:
    result = iter_flat_map({"a": 1})
    assert list(result) == ["a", 1]
    assert list(result) == []  # exhausted, like any generator


def test_flat_map_excludes_none_by_default() -> None:
    assert flat_map({"a": None, "b": 1}) == ["a", "b", 1]


def test_flat_map_keeps_none_when_asked() -> None:
    assert flat_map({"a": None, "b": 1}, exclude_none=False) == ["a", None, "b", 1]


def test_every_flattener_keeps_a_user_string_whole() -> None:
    text = UserString("ab")
    assert list(iter_flat_cont([text, ["c"]])) == [text, "c"]
    assert flat_cont(text) == [text]
    assert list(iter_flat_map({"k": text})) == ["k", text]
    assert flat_map([text]) == [text]
    assert list(iter_flat_cont_by(text)) == [text]
    assert flat_cont_by([text]) == [text]


def _first_then_fail() -> Generator[int, None, None]:
    yield 1
    msg = "read past the first leaf"
    raise RuntimeError(msg)


@pytest.mark.parametrize(
    "first_leaf",
    [
        lambda: next(iter_flat_cont(_first_then_fail())),
        lambda: next(iter_flat_cont([_first_then_fail()])),
        lambda: next(iter_flat_cont_by(_first_then_fail())),
        lambda: next(iter_flat_map(_first_then_fail())),
        lambda: next(iter_flat_map([_first_then_fail()])),
        lambda: next(iter_flat_cont(itertools.count(1))),
        lambda: next(iter_flat_map({1: itertools.count()})),
    ],
)
def test_the_iterating_flatteners_yield_a_leaf_before_reading_further(
    first_leaf: Any,
) -> None:
    # Each level is iterated, not star-unpacked into a tuple first, so the
    # first leaf comes out of a failing or endless source.
    assert first_leaf() == 1


@pytest.mark.parametrize("flatten", [flat_cont, flat_map, flat_cont_by])
def test_the_flatteners_with_no_arguments_give_nothing(flatten: Any) -> None:
    assert flatten() == []


def test_the_flatteners_take_generators_and_iterators() -> None:
    assert flat_cont((v for v in [1, [2]]), iter([3])) == [1, 2, 3]
    assert flat_map(iter([{"a": 1}]), (v for v in [2])) == ["a", 1, 2]


class _Shade(Enum):
    DARK = 1


class _AwaitableList(list):  # type: ignore[type-arg]  # Only the awaitable shape matters here.
    """A list that is also awaitable, so `NotContainer` makes it a leaf."""

    def __await__(self) -> Iterator[None]:
        return iter(())


@pytest.mark.parametrize(
    "leaf",
    [b"ab", bytearray(b"ab"), memoryview(b"ab"), _Shade, _AwaitableList([1]), UserString("ab")],
)
def test_every_flattener_keeps_a_not_container_whole(leaf: Any) -> None:
    assert flat_cont([leaf]) == [leaf]
    assert flat_map({"k": [leaf]}) == ["k", leaf]
    assert flat_cont_by([leaf]) == [leaf]


def test_flat_map_flattens_a_tuple_key_and_drops_a_none_key() -> None:
    assert flat_map({(1, 2): "v"}) == [1, 2, "v"]
    assert flat_map({None: 1}) == [1]
    assert flat_map({None: 1}, exclude_none=False) == [None, 1]


def test_flat_map_keeps_none_inside_a_list_when_asked() -> None:
    assert flat_map([{"a": None}, None], exclude_none=False) == ["a", None, None]


def test_a_predicate_that_takes_strings_never_reaches_a_leaf() -> None:
    # Each character of a `str` is a `str` again, as the docstring warns.
    with pytest.raises(RecursionError):
        flat_cont_by(["ab"], is_container=lambda x: isinstance(x, (str, list)))


def test_deep_nesting_well_inside_the_recursion_limit_flattens() -> None:
    nested: list[Any] = [0]
    for depth in range(1, 200):
        nested = [depth, nested]

    assert sorted(flat_cont(nested)) == list(range(200))
