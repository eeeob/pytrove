from __future__ import annotations as _annotations

import sys
from collections import UserString
from collections.abc import Iterable, Iterator
from typing import Any, Generic, TypeVar

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
    can only be unwrapped by a caller-supplied predicate. Generic with a typed
    `__iter__` on purpose: that is what lets a type checker walk through it and
    land on the real element type.
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
    # predicate is accepted wherever a plain `bool` one is -- and neither
    # changes what the element type is inferred to be.
    if sys.version_info >= (3, 13):
        from typing import TypeIs  # noqa: PLC0415 - `typing.TypeIs` exists only from 3.13
    else:
        from typing import TypeGuard as TypeIs  # noqa: PLC0415 - the pre-3.13 stand-in for `TypeIs`

    def is_box(x: Any) -> TypeIs[_Box[Any]]:
        return isinstance(x, _Box)

    assert flat_cont_by(_Box(1, _Box(2, 3)), is_container=is_box) == [1, 2, 3]


def test_a_narrowing_predicate_really_does_stop_at_the_first_layer() -> None:
    # The runtime half of the caveat in the docstring: a predicate that
    # refuses what `is_container` would have taken leaves the inner
    # structure whole, whatever a type checker reads the call as.
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
