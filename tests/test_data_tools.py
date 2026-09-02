"""Covers data_tools' recursive transforms, and above all the container
reconstruction underneath them: what `type(data)(items)` gets wrong, and for
which types."""

import array
import contextlib
import logging
import sys
import types

from collections.abc import Mapping
from collections import (ChainMap, Counter, OrderedDict, UserDict, UserList,
                         defaultdict, deque, namedtuple)
from enum import Enum

import pytest

from pytrove import (clean_none_kw, clean_none_values, enum_to_value,
                     get_nested_dict_value, value_to_enum)
from pytrove.classes import (DefaultWeakKeyDict, DefaultWeakValueDict,
                             KeyDefaultDict, KeyDefaultWeakKeyDict,
                             KeyDefaultWeakValueDict)


@contextlib.contextmanager
def caplog_at_warning():
    """Collect pytrove._data_tools warnings without depending on caplog's
    propagation setup, so the records are the assertion."""

    records = []
    handler = logging.Handler()
    handler.emit = records.append
    logger = logging.getLogger("pytrove._data_tools")
    logger.addHandler(handler)

    try:
        yield records
    finally:
        logger.removeHandler(handler)


class Color(Enum):
    RED = "red"
    BLUE = "blue"


Point = namedtuple("Point", "x y")


class Cfg(dict):
    """A mapping whose __init__ takes something the reconstruction cannot
    guess -- and which swallows a mapping passed positionally as that
    argument, coming back empty rather than raising."""

    def __init__(self, name, *a, **kw):
        self.name = name
        super().__init__(*a, **kw)


class Box:
    """Weak-referenceable, hashable, and cheap to compare in a message."""

    def __init__(self, n):
        self.n = n

    def __hash__(self):
        return hash(self.n)

    def __eq__(self, other):
        return isinstance(other, Box) and self.n == other.n

    def __repr__(self):
        return f"Box({self.n})"


# --- the transforms themselves -------------------------------------------

def test_enum_to_value_replaces_members_recursively():
    assert enum_to_value(Color.RED) == "red"
    assert enum_to_value({"k": Color.RED}) == {"k": "red"}
    assert enum_to_value([Color.RED, [Color.BLUE]]) == ["red", ["blue"]]


def test_enum_to_value_converts_a_mapping_key_as_well_as_its_value():
    # Both sides, which it used to be neither of: the pairs were handed to
    # the transform whole, as tuples, so a key was only ever reached by
    # accident of the container branch.
    assert enum_to_value({Color.RED: Color.BLUE}) == {"red": "blue"}


def test_value_to_enum_round_trips_enum_to_value():
    assert value_to_enum("red", Color) is Color.RED
    assert value_to_enum({"k": "red"}, Color) == {"k": Color.RED}
    assert value_to_enum(enum_to_value({"k": Color.RED}), Color) == {"k": Color.RED}


def test_value_to_enum_picks_the_side_map_resolve_type_names():
    assert value_to_enum({"red": "blue"}, Color, "k") == {Color.RED: "blue"}
    assert value_to_enum({"red": "blue"}, Color, "v") == {"red": Color.BLUE}


def test_clean_none_values_drops_none_at_every_depth():
    assert clean_none_values({"a": 1, "b": None, "c": {"d": None, "e": 2}}) == {
        "a": 1, "c": {"e": 2}
    }
    assert clean_none_values([1, None, [2, None]]) == [1, [2]]


def test_clean_none_values_keeps_an_empty_container_but_not_a_none():
    # Empty is not None: the entry was cleaned, not absent.
    assert clean_none_values({"a": [None], "b": None}) == {"a": []}


def test_clean_none_kw_leaves_unset_arguments_out():
    assert clean_none_kw(limit=10, offset=None) == {"limit": 10}


def test_get_nested_dict_value_walks_the_path():
    assert get_nested_dict_value({"a": {"b": 1}}, "a.b") == 1
    assert get_nested_dict_value({"a": {"b": 1}}, "a|b", sep="|") == 1

    with pytest.raises(KeyError):
        get_nested_dict_value({"a": {}}, "a.b")


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
def test_the_container_type_survives_the_transform(value):
    assert type(enum_to_value(value)) is type(value)


def test_a_namedtuple_is_rebuilt_through_make():
    # Point(items) is a missing-argument TypeError -- one constructor
    # argument per field -- so _make is the door.
    out = enum_to_value(Point(Color.RED, Color.BLUE))

    assert out == Point("red", "blue")
    assert out.x == "red"


def test_a_namedtuple_that_loses_a_field_comes_back_whole(caplog):
    # A namedtuple cannot be short, and nothing else may be substituted for
    # it, so it comes back untouched -- None still in place -- and says so.
    source = Point(1, None)

    with caplog.at_level(logging.WARNING, logger="pytrove._data_tools"):
        out = clean_none_values(source)

    assert out is source
    assert "Point" in caplog.text


def test_an_array_keeps_its_typecode():
    out = enum_to_value(array.array("i", [1, 2]))

    assert isinstance(out, array.array)
    assert out.typecode == "i"
    assert list(out) == [1, 2]


# --- reconstruction: what used to be silently wrong ----------------------

def test_a_counter_is_not_rebuilt_by_counting_its_own_pairs():
    # Counter(pairs) counts the pairs as elements: {"a": 1} came back as
    # Counter({("a", 1): 1}). No exception -- just a wrong answer.
    out = enum_to_value(Counter({"a": 1, "b": 2}))

    assert isinstance(out, Counter)
    assert out == Counter({"a": 1, "b": 2})


def test_a_chainmap_is_not_rebuilt_with_an_iterator_as_one_of_its_maps():
    # ChainMap(pairs) took the iterator to be a map. What comes back now is
    # the flattened contents in a single map, which is the only reading that
    # survives a transform.
    out = enum_to_value(ChainMap({"a": Color.RED}, {"b": Color.BLUE}))

    assert isinstance(out, ChainMap)
    assert dict(out) == {"a": "red", "b": "blue"}


def test_a_mappingproxy_is_handed_a_mapping_and_not_an_iterator():
    out = enum_to_value(types.MappingProxyType({"a": Color.RED}))

    assert isinstance(out, types.MappingProxyType)
    assert dict(out) == {"a": "red"}


@pytest.mark.parametrize("make, expected", [
    (lambda: zip([Color.RED], [Color.BLUE]), [("red", "blue")]),
    (lambda: enumerate([Color.RED, Color.BLUE]), [(0, "red"), (1, "blue")]),
    (lambda: map(lambda v: v, [Color.RED]), ["red"]),
    (lambda: reversed([Color.RED, Color.BLUE]), ["blue", "red"]),
    (lambda: (v for v in [Color.RED]), ["red"]),
])
def test_an_iterator_yields_its_real_contents(make, expected):
    # zip(items) and enumerate(items) both *succeeded* and both returned
    # something else: a zip over one iterable, and a re-numbering from zero.
    # An iterator is no longer rebuilt as its own type at all.
    assert list(enum_to_value(make())) == expected


def test_a_constructor_that_swallows_its_argument_does_not_lose_the_data():
    # Cfg(mapping) takes the mapping as `name` and comes back empty, without
    # raising. The result is measured rather than trusted, and the copy path
    # then carries the instance state across.
    out = enum_to_value(Cfg("cfg-name", {"a": Color.RED}))

    assert type(out) is Cfg
    assert dict(out) == {"a": "red"}
    assert out.name == "cfg-name"


# --- reconstruction: types that carry a default_factory ------------------

def test_a_defaultdict_keeps_its_factory():
    # defaultdict(pairs) is a "first argument must be callable" TypeError:
    # the factory is in the position the contents would be passed in.
    out = enum_to_value(defaultdict(list, {"a": Color.RED}))

    assert type(out) is defaultdict
    assert out.default_factory is list
    assert dict(out) == {"a": "red"}


def test_key_default_dict_is_not_silently_emptied():
    # The worst of them: KeyDefaultDict(pairs) stored the pairs as the
    # factory and returned an empty mapping. Total loss, no exception.
    source = KeyDefaultDict(lambda k: k * 2)
    source["a"] = Color.RED

    out = enum_to_value(source)

    assert type(out) is KeyDefaultDict
    assert dict(out) == {"a": "red"}
    assert out["zz"] == "zzzz", "the factory did not survive"


def test_the_weak_key_default_dicts_keep_type_and_factory():
    kept = Box(1)
    source = KeyDefaultWeakValueDict(lambda k: kept)
    source["a"] = kept

    out = enum_to_value(source)

    assert type(out) is KeyDefaultWeakValueDict
    assert dict(out) == {"a": kept}
    assert out["missing"] is kept


def test_a_zero_argument_factory_survives_being_handed_back():
    # DefaultWeakValueDict wraps its factory to take a key. Rebuilding from
    # `default_factory` wrapped it a second time, and the second wrapper then
    # called the first with no arguments -- so every miss on the rebuilt
    # mapping raised TypeError, nowhere near the line that caused it.
    kept = Box(1)
    source = DefaultWeakValueDict(lambda: kept)
    source["a"] = kept

    out = enum_to_value(source)

    assert type(out) is DefaultWeakValueDict
    assert out["missing"] is kept


def test_a_zero_argument_key_dict_factory_survives_too():
    key = Box(2)
    source = DefaultWeakKeyDict(lambda: 7)
    source[key] = Color.RED

    out = enum_to_value(source)

    assert type(out) is DefaultWeakKeyDict
    assert out[key] == "red"
    assert out[Box(3)] == 7


def test_a_weak_key_dict_keeps_its_type():
    key = Box(4)
    source = KeyDefaultWeakKeyDict(lambda k: 1)
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
def test_a_container_that_cannot_be_rebuilt_comes_back_as_it_was(value):
    # A range cannot hold arbitrary values and a dict view cannot be
    # constructed at all. Handing back a list would be a silent substitution
    # of a type the caller cannot use as the one it asked for, so the original
    # is returned and the transform is what is given up.
    with caplog_at_warning() as records:
        out = enum_to_value(value)

    assert out is value
    assert records, "the skipped conversion was not reported"


def test_the_warning_names_the_type_that_was_skipped(caplog):
    with caplog.at_level(logging.WARNING, logger="pytrove._data_tools"):
        enum_to_value(range(3))

    assert "range" in caplog.text
    assert "un-transformed" in caplog.text


def test_a_mapping_that_cannot_be_rebuilt_falls_back_to_a_dict():
    # The other half of the trade: a mapping keeps its converted contents and
    # gives up its type, because a dict is still usable as a mapping.
    class Frozen(Mapping):
        """Read-only, and built from something the reconstruction cannot
        reproduce -- so no attempt can put the new contents into one."""

        def __init__(self, pairs, tag):
            self._d = dict(pairs)
            self.tag = tag

        def __getitem__(self, k):
            return self._d[k]

        def __iter__(self):
            return iter(self._d)

        def __len__(self):
            return len(self._d)

    out = enum_to_value(Frozen({"a": Color.RED}, "t"))

    assert type(out) is dict
    assert out == {"a": "red"}


def test_the_original_is_never_mutated():
    source = {"a": Color.RED, "b": None}
    before = dict(source)

    enum_to_value(source)
    clean_none_values(source)
    value_to_enum(source, Color)

    assert source == before
