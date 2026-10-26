"""`_internal._rebuild`: rebuilding a container as its own type."""

from __future__ import annotations as _annotations

import array
import logging
import weakref
from collections import defaultdict, deque, namedtuple
from collections.abc import Hashable
from typing import TYPE_CHECKING, Any, TypeVar

from pytrove._internal._rebuild import (
    _filled,
    _reconstruct,
    _reconstruct_mapping,
    _refilled,
    _transform,
    _transform_mapping,
    _MESS,
    _R,
    _RK,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    import pytest

Point = namedtuple("Point", "x y")  # noqa: PYI024  # A runtime namedtuple is what the rebuild has to handle.


class _Stubborn:
    """Copyable, with `clear` and `update` that refuse."""

    def clear(self) -> None:
        msg = "no"
        raise RuntimeError(msg)

    def update(self, items: Any) -> None:
        msg = "no"
        raise RuntimeError(msg)


class _NoOpUpdateDict(dict):  # type: ignore[type-arg]  # Only the constructor shape matters here.
    """A `dict` with a `default_factory` whose `update` does nothing, so every rebuild comes back empty."""

    def __init__(self, factory: Any = None) -> None:
        self.default_factory = factory
        super().__init__()

    def update(self, *args: Any, **kwargs: Any) -> None:
        pass


def test_transform_applies_the_function_and_drops_mess() -> None:
    assert list(_transform([1, 2, 3], lambda v: _MESS if v == 2 else v * 10)) == [10, 30]
    assert list(_transform([1, 2])) == [1, 2]


def test_transform_mapping_drops_a_pair_when_either_side_is_mess() -> None:
    data = {"a": 1, "b": 2, "c": 3}
    seen_values: list[int] = []

    def value_func(v: int) -> Any:
        seen_values.append(v)
        return _MESS if v == 3 else v

    pairs = _transform_mapping(data, lambda k: _MESS if k == "a" else k, value_func)
    assert list(pairs) == [("b", 2)]
    assert seen_values == [2, 3]  # a dropped key never pays for its value
    assert list(_transform_mapping(data)) == [("a", 1), ("b", 2), ("c", 3)]


def test_filled_detects_only_a_total_loss() -> None:
    assert _filled([1, 2], [1])
    assert not _filled([1, 2], [])
    assert _filled([], [])  # the transform itself dropped everything
    assert _filled([1], object())  # unsized: nothing to judge
    # mappings go through the same check
    assert _filled({"a": 1}, {"a": 1})
    assert not _filled({"a": 1}, {})
    assert _filled({}, {})


def test_refilled_keeps_the_instance_configuration() -> None:
    original = defaultdict(list, a=[1])
    new = _refilled(original, {"b": [2]})
    assert type(new) is defaultdict
    assert new.default_factory is list
    assert dict(new) == {"b": [2]}

    refilled_list = _refilled([1, 2], [3])
    assert refilled_list == [3]


def test_refilled_returns_none_when_a_copy_cannot_be_refilled() -> None:
    assert _refilled(range(3), [1]) is None  # no `clear`
    assert _refilled((1, 2), [3]) is None
    assert _refilled(_Stubborn(), [1]) is None  # `clear`/`update` refuse
    assert _refilled(iter([1]), [1]) is None  # cannot be copied at all


def test_refilled_refuses_a_copy_of_another_class() -> None:
    class Sub(weakref.WeakValueDictionary):  # type: ignore[type-arg]  # Only the copy behaviour matters here.
        pass

    assert type(Sub().copy()) is weakref.WeakValueDictionary
    assert _refilled(Sub(), {}) is None


def test_reconstruct_rebuilds_in_order_of_preference() -> None:
    it = _reconstruct(iter([1, 2]), lambda v: v + 1)
    assert list(it) == [2, 3]

    assert _reconstruct(Point(1, 2), lambda v: v * 2) == Point(2, 4)
    assert _reconstruct(array.array("i", [1]), lambda v: v + 1) == array.array("i", [2])
    assert _reconstruct({1, 2}, lambda v: v * 2) == {2, 4}
    assert _reconstruct([1, 2]) == [1, 2]


def test_reconstruct_falls_through_to_refill_and_then_gives_up(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class NamedList(list):  # type: ignore[type-arg]  # Only the constructor shape matters here.
        def __init__(self, name: Any) -> None:
            self.name = name
            super().__init__()

    source = NamedList("n")
    source.append(1)
    out = _reconstruct(source, str)
    assert type(out) is NamedList and list(out) == ["1"] and out.name == "n"

    with caplog.at_level("WARNING", logger="pytrove._internal._rebuild"):
        bad_array = _reconstruct(array.array("i", [1]), str)
        kept_range = _reconstruct(range(2), str)

    assert isinstance(bad_array, array.array) and list(bad_array) == [1]
    assert kept_range == range(2)
    assert caplog.text.count("un-transformed") == 2


def test_reconstruct_mapping_restores_a_factory_or_falls_back_to_a_dict() -> None:
    dd = _reconstruct_mapping(defaultdict(list, {"a": 1}), str, str)
    assert type(dd) is defaultdict and dd.default_factory is list and dict(dd) == {"a": "1"}

    plain = _reconstruct_mapping({"a": 1}, value_func=lambda v: _MESS)
    assert plain == {}

    source = _NoOpUpdateDict(list)
    dict.__setitem__(source, "a", 1)
    out = _reconstruct_mapping(source)
    assert type(out) is dict and out == {"a": 1}  # every rebuild came back empty


def test_result_type_variables() -> None:
    assert isinstance(_R, TypeVar)
    assert isinstance(_RK, TypeVar)
    assert _RK.__bound__ is Hashable


def test_mess_is_a_unique_marker() -> None:
    value: Any = _MESS
    assert value is not None
    assert value != object()


_LOGGER = "pytrove._internal._rebuild"


def test_transform_is_lazy() -> None:
    seen: list[int] = []
    out = _transform([1, 2], lambda v: seen.append(v) or v)

    assert seen == []
    assert next(out) == 1
    assert seen == [1]


def test_reconstruct_returns_an_iterator_as_a_lazy_view_of_its_source() -> None:
    source: Iterator[int] = iter([1, 2, 3])
    out = _reconstruct(source, lambda v: v * 10)

    assert next(source) == 1  # consuming the source drains the result too
    assert list(out) == [20, 30]


def test_reconstruct_keeps_a_deques_maxlen() -> None:
    out = _reconstruct(deque([1, 2], maxlen=2), str)

    assert type(out) is deque
    assert out.maxlen == 2
    assert list(out) == ["1", "2"]


def test_reconstruct_leaves_a_namedtuple_that_cannot_shrink_whole(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # `_make` refuses one item, `Point([1])` misses `y`, and a tuple cannot be refilled.
    source = Point(1, None)

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        out = _reconstruct(source, lambda v: _MESS if v is None else v)

    assert out is source
    assert "Point" in caplog.text


class _PickyList(list):  # type: ignore[type-arg]  # Only the constructor shape matters here.
    """A list whose constructor refuses any items with `ValueError`."""

    def __init__(self, items: Any = ()) -> None:
        if items:
            msg = "no items here"
            raise ValueError(msg)

        super().__init__()


class _TypedList(list):  # type: ignore[type-arg]  # Only the constructor shape matters here.
    """A list with a `typecode`, whose typecode constructor refuses with `ValueError`."""

    typecode = "x"

    def __init__(self, *args: Any) -> None:
        if len(args) == 2:
            msg = "bad typecode"
            raise ValueError(msg)

        super().__init__(*args)


def test_reconstruct_takes_a_value_error_as_a_constructor_refusal() -> None:
    picky = _PickyList()
    picky.append(1)
    out = _reconstruct(picky, str)
    assert type(out) is _PickyList and list(out) == ["1"]  # refilled instead

    typed = _reconstruct(_TypedList([1]), str)
    assert type(typed) is _TypedList and list(typed) == ["1"]  # `cls(items)` instead


def test_reconstruct_takes_an_overflow_error_as_a_constructor_refusal(
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = array.array("b", [1])

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        out = _reconstruct(source, lambda v: v * 200)

    assert out is source
    assert "un-transformed" in caplog.text


def test_reconstruct_gives_up_on_a_set_whose_items_become_unhashable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = {1, 2}

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        out = _reconstruct(source, lambda v: [v])

    assert out is source
    assert "set" in caplog.text


class _FactoryValueErrorDict(dict):  # type: ignore[type-arg]  # Only the constructor shape matters here.
    """A dict with a callable `default_factory` that its constructor refuses with `ValueError`."""

    default_factory = staticmethod(list)

    def __init__(self, arg: Any = None) -> None:
        if callable(arg):
            msg = "no factory here"
            raise ValueError(msg)

        super().__init__(arg or {})


def test_reconstruct_mapping_moves_past_a_factory_constructor_value_error() -> None:
    out = _reconstruct_mapping(_FactoryValueErrorDict({"a": 1}), value_func=str)

    assert type(out) is _FactoryValueErrorDict
    assert dict(out) == {"a": "1"}


class _NamedDict(dict):  # type: ignore[type-arg]  # Only the constructor shape matters here.
    """A dict whose constructor takes a name and swallows a mapping passed as it."""

    def __init__(self, name: Any, *args: Any) -> None:
        self.name = name
        super().__init__(*args)


def test_reconstruct_mapping_falls_back_to_a_refilled_copy() -> None:
    out = _reconstruct_mapping(_NamedDict("n", {"a": 1}), value_func=str)

    assert type(out) is _NamedDict
    assert dict(out) == {"a": "1"}
    assert out.name == "n"
