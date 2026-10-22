"""`data_tools.walk`: the recursive transforms, and the container reconstruction
underneath them: what `type(data)(items)` gets wrong, and for which types."""

from __future__ import annotations as _annotations

import array
import contextlib
import logging
import types
from collections import ChainMap, Counter, OrderedDict, UserDict, UserList, defaultdict, deque, namedtuple
from collections.abc import Callable, Iterator, Mapping
from enum import Enum
from typing import Any

import pytest

from pytrove.data_tools import (
    DefaultWeakKeyDict,
    DefaultWeakValueDict,
    KeyDefaultDict,
    KeyDefaultWeakKeyDict,
    KeyDefaultWeakValueDict,
    clean_none_kw,
    clean_none_values,
    enum_to_value,
    map_deep,
    map_deep_kv,
    snapshot,
    value_to_enum,
)
from pytrove.errors import ValidationError


@contextlib.contextmanager
def caplog_at_warning() -> Iterator[list[logging.LogRecord]]:
    """Collect `pytrove.data_tools._internal` warnings without depending on caplog's
    propagation setup, so the records are the assertion."""
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]  # The handler only has to collect.
    logger = logging.getLogger("pytrove.data_tools._internal")
    logger.addHandler(handler)

    try:
        yield records
    finally:
        logger.removeHandler(handler)


class Color(Enum):
    RED = "red"
    BLUE = "blue"


class Size(Enum):
    SMALL = 1


Point = namedtuple("Point", "x y")  # noqa: PYI024  # A runtime namedtuple is what the rebuild has to handle.


class Cfg(dict):  # type: ignore[type-arg]  # Only the constructor shape matters here.
    """A mapping whose __init__ takes something the reconstruction cannot
    guess -- and which swallows a mapping passed positionally as that
    argument, coming back empty rather than raising."""

    def __init__(self, name: Any, *a: Any, **kw: Any) -> None:
        self.name = name
        super().__init__(*a, **kw)


class Box:
    """Weak-referenceable, hashable, and cheap to compare in a message."""

    def __init__(self, n: int) -> None:
        self.n = n

    def __hash__(self) -> int:
        return hash(self.n)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Box) and self.n == other.n

    def __repr__(self) -> str:
        return f"Box({self.n})"


# --- the transforms themselves -------------------------------------------

def test_map_deep_applies_func_to_every_leaf() -> None:
    data = {"a": "x", "b": ["y", "z"]}
    assert map_deep(data, str.upper) == {"A": "X", "B": ["Y", "Z"]}


def test_map_deep_converts_a_mapping_key_as_well_as_its_value() -> None:
    assert map_deep({"a": "b"}, str.upper) == {"A": "B"}


def test_map_deep_applies_func_to_a_bare_leaf() -> None:
    assert map_deep("x", str.upper) == "X"


def test_map_deep_preserves_the_container_type() -> None:
    result = map_deep(("a", "b"), str.upper)
    assert type(result) is tuple
    assert result == ("A", "B")


def test_whatever_func_raises_propagates_out_of_a_container_too() -> None:
    # `str.upper(1)` is a TypeError, the same class a constructor raises when it
    # refuses the items: the rebuild must not read the one as the other and
    # hand the data back un-transformed.
    with pytest.raises(TypeError):
        map_deep([1], str.upper)

    with pytest.raises(TypeError):
        map_deep({"a": [1]}, str.upper)

    with pytest.raises(ValueError, match="no"):
        map_deep_kv((1,), lambda v: (_ for _ in ()).throw(ValueError("no")))


def test_map_deep_kv_applies_value_func_to_every_leaf_value() -> None:
    assert map_deep_kv({"a": "x", "b": ["y", "z"]}, str.upper) == {"a": "X", "b": ["Y", "Z"]}


def test_map_deep_kv_leaves_keys_untouched_by_default() -> None:
    assert map_deep_kv({"a": 1}, lambda v: v + 1) == {"a": 2}


def test_map_deep_kv_applies_key_func_to_a_bare_leaf_key() -> None:
    assert map_deep_kv({"a": 1}, str, key_func=str.upper) == {"A": "1"}


def test_map_deep_kv_uses_value_func_for_a_container_key_not_key_func() -> None:
    # A tuple key has no "keys" of its own to offer key_func -- it is
    # rebuilt the same way any other container is, through value_func.
    result = map_deep_kv(
        {(1, 2): "x"},
        lambda v: v * 10 if isinstance(v, int) else v.upper(),
        key_func=lambda k: "should not run",
    )

    assert result == {(10, 20): "X"}


def test_map_deep_kv_recurses_into_a_nested_mapping_with_both_funcs() -> None:
    data = {"a": {"b": 1}}
    assert map_deep_kv(data, lambda v: v + 1, key_func=str.upper) == {"A": {"B": 2}}


def test_map_deep_kv_applies_value_func_to_a_bare_leaf() -> None:
    assert map_deep_kv("x", str.upper) == "X"


def test_map_deep_kv_preserves_the_container_type() -> None:
    result = map_deep_kv(("a", "b"), str.upper)
    assert type(result) is tuple
    assert result == ("A", "B")


def test_snapshot_equals_the_original() -> None:
    data = {"a": [1, 2, {3, 4}], "b": (5, [6, 7])}
    assert snapshot(data) == data


def test_snapshot_breaks_the_link_at_every_level() -> None:
    data: dict[str, Any] = {"a": [1, 2]}
    result = snapshot(data)

    data["a"].append(99)
    data["b"] = "new"

    assert result == {"a": [1, 2]}


def test_snapshot_leaves_a_leaf_untouched() -> None:
    assert snapshot("text") == "text"
    assert snapshot(5) == 5
    assert snapshot(None) is None
    assert snapshot(b"raw") == b"raw"


def test_snapshot_leaves_a_non_container_key_untouched() -> None:
    key = "k"
    result = snapshot({key: [3, 4]})

    assert next(iter(result)) is key


def test_snapshot_rebuilds_a_container_key_into_an_equal_one() -> None:
    # A tuple key is walked exactly as a value is -- it comes back equal,
    # not the same object, since map_deep does not skip a mapping's keys.
    key = (1, 2)
    result = snapshot({key: [3, 4]})

    got = next(iter(result))
    assert got == key and got is not key


def test_snapshot_preserves_dict_and_list_subclasses() -> None:
    od = OrderedDict(x=1, y=[2, 3])
    result = snapshot(od)

    assert type(result) is OrderedDict
    assert result == od
    assert result["y"] is not od["y"]

    dq = deque([1, [2, 3]])
    result_dq = snapshot(dq)

    assert type(result_dq) is deque
    assert list(result_dq) == [1, [2, 3]]
    assert result_dq[1] is not dq[1]


def test_snapshot_preserves_tuple_and_recurses_into_it() -> None:
    data = (1, [2, 3], (4, 5))
    result = snapshot(data)

    assert type(result) is tuple
    assert result == data
    assert result[1] is not data[1]


def test_snapshot_keeps_a_defaultdicts_factory() -> None:
    dd = defaultdict(list, {"a": [1, 2]})
    result = snapshot(dd)

    assert type(result) is defaultdict
    assert result.default_factory is list
    assert result == {"a": [1, 2]}
    assert result["a"] is not dd["a"]


class _NoUpdateFactoryDict(dict):  # type: ignore[type-arg]  # Only the constructor shape matters here.
    """A `dict` with a `default_factory` whose `update` refuses, as some strict mappings do."""

    def __init__(self, arg: Any = None) -> None:
        if callable(arg):
            self.default_factory = arg
            super().__init__()
        else:
            self.default_factory = None
            super().__init__(arg or {})

    def update(self, *args: Any, **kwargs: Any) -> None:
        msg = "update refused"
        raise TypeError(msg)


def test_a_factory_mapping_whose_update_refuses_falls_back_to_the_pairs_constructor() -> None:
    data = _NoUpdateFactoryDict(list)
    dict.__setitem__(data, "a", 1)
    result = map_deep(data, str)
    assert type(result) is _NoUpdateFactoryDict
    assert dict(result) == {"a": "1"}


def test_snapshot_returns_a_range_untouched() -> None:
    # A range holds only ints -- nothing under it needed decoupling in the
    # first place, so getting the same object back is the correct answer,
    # not a fallback that happened to be good enough.
    r = range(3)
    with caplog_at_warning():
        assert snapshot(r) is r


def test_enum_to_value_replaces_members_recursively() -> None:
    assert enum_to_value(Color.RED) == "red"
    assert enum_to_value({"k": Color.RED}) == {"k": "red"}
    assert enum_to_value([Color.RED, [Color.BLUE]]) == ["red", ["blue"]]
    assert enum_to_value("plain") == "plain"


def test_enum_to_value_converts_a_mapping_key_as_well_as_its_value() -> None:
    # Both sides, which it used to be neither of: the pairs were handed to
    # the transform whole, as tuples, so a key was only ever reached by
    # accident of the container branch.
    assert enum_to_value({Color.RED: Color.BLUE}) == {"red": "blue"}


def test_value_to_enum_round_trips_enum_to_value() -> None:
    assert value_to_enum("red", Color) is Color.RED
    assert value_to_enum({"k": "red"}, Color) == {"k": Color.RED}
    assert value_to_enum(enum_to_value({"k": Color.RED}), Color) == {"k": Color.RED}


def test_value_to_enum_takes_any_nesting_of_classes_and_passes_strangers_through() -> None:
    assert value_to_enum(["red", 1, "other", [1]], [Color, (Size,)]) == [Color.RED, Size.SMALL, "other", [Size.SMALL]]
    assert value_to_enum("red", [Color, Color]) is Color.RED


def test_value_to_enum_picks_the_side_map_resolve_type_names() -> None:
    assert value_to_enum({"red": "blue"}, Color, "k") == {Color.RED: "blue"}
    assert value_to_enum({"red": "blue"}, Color, "K") == {Color.RED: "blue"}
    assert value_to_enum({"red": "blue"}, Color, "v") == {"red": Color.BLUE}
    assert value_to_enum({"red": {"blue": "red"}}, Color, "V") == {"red": {"blue": Color.RED}}


def test_value_to_enum_rejects_an_unknown_side() -> None:
    with pytest.raises(ValidationError, match="must be k or v"):
        value_to_enum({}, [], "x")


def test_clean_none_values_drops_none_at_every_depth() -> None:
    assert clean_none_values({"a": 1, "b": None, "c": {"d": None, "e": 2}}) == {"a": 1, "c": {"e": 2}}
    assert clean_none_values([1, None, [2, None]]) == [1, [2]]


def test_clean_none_values_keeps_an_empty_container_but_not_a_none() -> None:
    # Empty is not None: the entry was cleaned, not absent.
    assert clean_none_values({"a": [None], "b": None}) == {"a": []}


def test_clean_none_values_returns_a_non_container_as_is() -> None:
    assert clean_none_values(None) is None
    assert clean_none_values(5) == 5


def test_clean_none_kw_leaves_unset_arguments_out() -> None:
    assert clean_none_kw(limit=10, offset=None) == {"limit": 10}
    assert clean_none_kw(nested={"a": None, "b": 1}) == {"nested": {"b": 1}}
    assert clean_none_kw() == {}


# --- reconstruction: the type survives -----------------------------------

@pytest.mark.parametrize("value", [
    [Color.RED, Color.BLUE],
    (Color.RED,),
    {Color.RED},
    frozenset({Color.RED}),
    deque([Color.RED]),
    Point(Color.RED, Color.BLUE),
    UserList([Color.RED]),
    {"a": Color.RED},
    defaultdict(list, {"a": Color.RED}),
    OrderedDict(a=Color.RED),
    ChainMap({"a": Color.RED}),
    types.MappingProxyType({"a": Color.RED}),
    UserDict({"a": Color.RED}),
])
def test_the_container_type_survives_the_transform(value: Any) -> None:
    assert type(enum_to_value(value)) is type(value)


def test_a_namedtuple_is_rebuilt_through_make() -> None:
    # Point(items) is a missing-argument TypeError -- one constructor
    # argument per field -- so _make is the door.
    out = enum_to_value(Point(Color.RED, Color.BLUE))

    assert out == Point("red", "blue")
    assert out.x == "red"


def test_a_namedtuple_that_loses_a_field_comes_back_whole(caplog: pytest.LogCaptureFixture) -> None:
    # A namedtuple cannot be short, and nothing else may be substituted for
    # it, so it comes back untouched -- None still in place -- and says so.
    source = Point(1, None)

    with caplog.at_level(logging.WARNING, logger="pytrove.data_tools._internal"):
        out = clean_none_values(source)

    assert out is source
    assert "Point" in caplog.text


def test_an_array_keeps_its_typecode() -> None:
    out = enum_to_value(array.array("i", [1, 2]))

    assert isinstance(out, array.array)
    assert out.typecode == "i"
    assert list(out) == [1, 2]


def test_an_array_whose_items_no_longer_fit_comes_back_as_it_was() -> None:
    # `array("i", ["x"])` is a TypeError; nothing else can hold the strings as an array.
    source = array.array("i", [1])

    with caplog_at_warning() as records:
        out = map_deep(source, str)

    assert out is source
    assert records


# --- reconstruction: what used to be silently wrong ----------------------

def test_a_counter_is_not_rebuilt_by_counting_its_own_pairs() -> None:
    # Counter(pairs) counts the pairs as elements: {"a": 1} came back as
    # Counter({("a", 1): 1}). No exception -- just a wrong answer.
    out = enum_to_value(Counter({"a": 1, "b": 2}))

    assert isinstance(out, Counter)
    assert out == Counter({"a": 1, "b": 2})


def test_a_chainmap_is_not_rebuilt_with_an_iterator_as_one_of_its_maps() -> None:
    # ChainMap(pairs) took the iterator to be a map. What comes back now is
    # the flattened contents in a single map, which is the only reading that
    # survives a transform.
    out = enum_to_value(ChainMap({"a": Color.RED}, {"b": Color.BLUE}))

    assert isinstance(out, ChainMap)
    assert dict(out) == {"a": "red", "b": "blue"}


def test_a_mappingproxy_is_handed_a_mapping_and_not_an_iterator() -> None:
    out = enum_to_value(types.MappingProxyType({"a": Color.RED}))

    assert isinstance(out, types.MappingProxyType)
    assert dict(out) == {"a": "red"}


@pytest.mark.parametrize(("make", "expected"), [
    (lambda: zip([Color.RED], [Color.BLUE], strict=True), [("red", "blue")]),
    (lambda: enumerate([Color.RED, Color.BLUE]), [(0, "red"), (1, "blue")]),
    (lambda: map(lambda v: v, [Color.RED]), ["red"]),  # noqa: C417 - the case is a `map` iterator
    (lambda: reversed([Color.RED, Color.BLUE]), ["blue", "red"]),
    (lambda: (v for v in [Color.RED]), ["red"]),
])
def test_an_iterator_yields_its_real_contents(make: Callable[[], Iterator[Any]], expected: list[Any]) -> None:
    # zip(items) and enumerate(items) both *succeeded* and both returned
    # something else: a zip over one iterable, and a re-numbering from zero.
    # An iterator is no longer rebuilt as its own type at all.
    assert list(enum_to_value(make())) == expected


def test_a_constructor_that_swallows_its_argument_does_not_lose_the_data() -> None:
    # Cfg(mapping) takes the mapping as `name` and comes back empty, without
    # raising. The result is measured rather than trusted, and the copy path
    # then carries the instance state across.
    out = enum_to_value(Cfg("cfg-name", {"a": Color.RED}))

    assert type(out) is Cfg
    assert dict(out) == {"a": "red"}
    assert out.name == "cfg-name"


class NamedList(list):  # type: ignore[type-arg]  # Only the constructor shape matters here.
    """A list whose constructor takes a name, so `cls(items)` stores the items as the name."""

    def __init__(self, name: Any) -> None:
        self.name = name
        super().__init__()


def test_a_sequence_whose_constructor_swallows_its_argument_is_refilled() -> None:
    source = NamedList("n")
    source.extend([Color.RED])

    out = enum_to_value(source)

    assert type(out) is NamedList
    assert list(out) == ["red"]
    assert out.name == "n"


# --- reconstruction: types that carry a default_factory ------------------

def test_a_defaultdict_keeps_its_factory() -> None:
    # defaultdict(pairs) is a "first argument must be callable" TypeError:
    # the factory is in the position the contents would be passed in.
    out = enum_to_value(defaultdict(list, {"a": Color.RED}))

    assert type(out) is defaultdict
    assert out.default_factory is list
    assert dict(out) == {"a": "red"}


def test_key_default_dict_is_not_silently_emptied() -> None:
    # The worst of them: KeyDefaultDict(pairs) stored the pairs as the
    # factory and returned an empty mapping. Total loss, no exception.
    source: KeyDefaultDict[str, Any] = KeyDefaultDict(lambda k: k * 2)
    source["a"] = Color.RED

    out = enum_to_value(source)

    assert type(out) is KeyDefaultDict
    assert dict(out) == {"a": "red"}
    assert out["zz"] == "zzzz", "the factory did not survive"


def test_the_weak_key_default_dicts_keep_type_and_factory() -> None:
    kept = Box(1)
    source: KeyDefaultWeakValueDict[str, Box] = KeyDefaultWeakValueDict(lambda k: kept)
    source["a"] = kept

    out = enum_to_value(source)

    assert type(out) is KeyDefaultWeakValueDict
    assert dict(out) == {"a": kept}
    assert out["missing"] is kept


def test_a_zero_argument_factory_survives_being_handed_back() -> None:
    # DefaultWeakValueDict wraps its factory to take a key. Rebuilding from
    # `default_factory` wrapped it a second time, and the second wrapper then
    # called the first with no arguments -- so every miss on the rebuilt
    # mapping raised TypeError, nowhere near the line that caused it.
    kept = Box(1)
    source: DefaultWeakValueDict[str, Box] = DefaultWeakValueDict(lambda: kept)
    source["a"] = kept

    out = enum_to_value(source)

    assert type(out) is DefaultWeakValueDict
    assert out["missing"] is kept


def test_a_zero_argument_key_dict_factory_survives_too() -> None:
    key = Box(2)
    source: DefaultWeakKeyDict[Box, Any] = DefaultWeakKeyDict(lambda: 7)
    source[key] = Color.RED

    out = enum_to_value(source)

    assert type(out) is DefaultWeakKeyDict
    assert out[key] == "red"
    assert out[Box(3)] == 7


def test_a_weak_key_dict_keeps_its_type() -> None:
    key = Box(4)
    source: KeyDefaultWeakKeyDict[Box, Any] = KeyDefaultWeakKeyDict(lambda k: 1)
    source[key] = Color.RED

    out = enum_to_value(source)

    assert type(out) is KeyDefaultWeakKeyDict
    assert out[key] == "red"


# --- reconstruction: types that cannot keep themselves -------------------

@pytest.mark.parametrize("value", [
    range(3),
    {Color.RED: 1}.keys(),
    {1: Color.RED}.values(),
])
def test_a_container_that_cannot_be_rebuilt_comes_back_as_it_was(value: Any) -> None:
    # A range cannot hold arbitrary values and a dict view cannot be
    # constructed at all. Handing back a list would be a silent substitution
    # of a type the caller cannot use as the one it asked for, so the original
    # is returned and the transform is what is given up.
    with caplog_at_warning() as records:
        out = enum_to_value(value)

    assert out is value
    assert records, "the skipped conversion was not reported"


def test_the_warning_names_the_type_that_was_skipped(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="pytrove.data_tools._internal"):
        enum_to_value(range(3))

    assert "range" in caplog.text
    assert "un-transformed" in caplog.text


def test_a_mapping_that_cannot_be_rebuilt_falls_back_to_a_dict() -> None:
    # The other half of the trade: a mapping keeps its converted contents and
    # gives up its type, because a dict is still usable as a mapping.
    class Frozen(Mapping):  # type: ignore[type-arg]  # Only the constructor shape matters here.
        """Read-only, and built from something the reconstruction cannot
        reproduce -- so no attempt can put the new contents into one."""

        def __init__(self, pairs: Mapping[Any, Any], tag: str) -> None:
            self._d = dict(pairs)
            self.tag = tag

        def __getitem__(self, k: Any) -> Any:
            return self._d[k]

        def __iter__(self) -> Iterator[Any]:
            return iter(self._d)

        def __len__(self) -> int:
            return len(self._d)

    out = enum_to_value(Frozen({"a": Color.RED}, "t"))

    assert type(out) is dict
    assert out == {"a": "red"}


def test_the_original_is_never_mutated() -> None:
    source = {"a": Color.RED, "b": None}
    before = dict(source)

    enum_to_value(source)
    clean_none_values(source)
    value_to_enum(source, Color)

    assert source == before
