"""`data_tools.mappings`: the dicts that build a missing value from its key."""

from __future__ import annotations as _annotations

import copy
import gc
import pickle
import weakref
from typing import Any

import pytest

from pytrove.data_tools import (
    DefaultWeakKeyDict,
    DefaultWeakValueDict,
    KeyDefaultDict,
    KeyDefaultWeakKeyDict,
    KeyDefaultWeakValueDict,
)


class Box:
    """Weak-referenceable and hashable."""

    def __init__(self, n: int) -> None:
        self.n = n


def test_key_default_dict_builds_stores_and_is_callable() -> None:
    calls: list[str] = []

    def factory(key: str) -> str:
        calls.append(key)
        return key.upper()

    d = KeyDefaultDict(factory)

    assert d["a"] == "A"
    assert d("a") == "A"
    assert d("b") == "B"
    assert dict(d) == {"a": "A", "b": "B"}
    assert calls == ["a", "b"]
    assert d.default_factory is factory
    assert d.get("zz") is None  # `get` does not build


def test_key_default_weak_value_dict_rebuilds_a_collected_value() -> None:
    built: list[str] = []

    def factory(key: str) -> Box:
        built.append(key)
        return Box(len(key))

    d = KeyDefaultWeakValueDict(factory)
    first = d["ab"]

    assert first.n == 2
    assert d("ab") is first
    assert d.default_factory is factory

    del first
    gc.collect()

    assert "ab" not in d
    assert d["ab"].n == 2
    assert built == ["ab", "ab"]


def test_key_default_weak_key_dict_builds_from_the_key_and_drops_it_with_the_key() -> None:
    d = KeyDefaultWeakKeyDict(lambda key: key.n * 10)
    key = Box(3)

    assert d[key] == 30
    assert d(key) == 30
    assert len(d) == 1

    del key
    gc.collect()

    assert len(d) == 0


@pytest.mark.parametrize(
    "cls",
    [
        KeyDefaultDict,
        KeyDefaultWeakValueDict,
        DefaultWeakValueDict,
        KeyDefaultWeakKeyDict,
        DefaultWeakKeyDict,
    ],
)
def test_every_dict_refuses_a_factory_that_is_not_callable(cls: Any) -> None:
    with pytest.raises(TypeError, match="must be callable"):
        cls("not callable")


def test_default_weak_value_dict_takes_a_zero_argument_factory() -> None:
    kept = Box(1)
    d = DefaultWeakValueDict(lambda: kept)

    assert d["anything"] is kept
    assert d("other") is kept
    assert isinstance(d, weakref.WeakValueDictionary)
    assert d.default_factory.__wrapped__() is kept  # type: ignore[attr-defined]  # The adapter keeps the original.


def test_default_weak_key_dict_takes_a_zero_argument_factory() -> None:
    d = DefaultWeakKeyDict(list)
    key = Box(1)

    assert d[key] == []
    assert d(key) is d[key]
    assert isinstance(d, weakref.WeakKeyDictionary)

    with pytest.raises(TypeError, match="must be callable"):
        DefaultWeakKeyDict(5)  # type: ignore[arg-type]  # The wrong type is the point.


def _fail(_key: Any = None) -> Any:
    msg = "factory failed"
    raise LookupError(msg)


@pytest.mark.parametrize(
    ("make", "key"),
    [
        (lambda: KeyDefaultDict(_fail), "a"),
        (lambda: KeyDefaultWeakValueDict(_fail), "a"),
        (lambda: KeyDefaultWeakKeyDict(_fail), Box(1)),
    ],
)
def test_a_raising_factory_leaves_no_entry(make: Any, key: Any) -> None:
    d = make()

    with pytest.raises(LookupError, match="factory failed"):
        d[key]

    assert len(d) == 0


def test_key_default_weak_value_dict_refuses_a_value_it_cannot_reference_weakly() -> None:
    d = KeyDefaultWeakValueDict(len)

    with pytest.raises(TypeError, match="weak reference"):
        d["abc"]

    assert len(d) == 0


def test_key_default_weak_key_dict_keeps_its_factory() -> None:
    def factory(key: Box) -> int:
        return key.n

    d = KeyDefaultWeakKeyDict(factory)
    assert d.default_factory is factory


def test_key_default_weak_key_dict_calls_the_factory_once_per_key() -> None:
    calls: list[Box] = []
    d = KeyDefaultWeakKeyDict(lambda key: calls.append(key) or key.n)
    key = Box(5)

    assert d(key) == 5
    assert d(key) == 5
    assert d[key] == 5
    assert calls == [key]


def test_the_weak_dicts_do_not_build_on_get_in_or_setdefault() -> None:
    kept = Box(1)
    values = KeyDefaultWeakValueDict(lambda key: kept)

    assert values.get("a") is None
    assert "a" not in values
    assert values.setdefault("b", kept) is kept
    assert list(values) == ["b"]

    keys = KeyDefaultWeakKeyDict(lambda key: 1)
    key = Box(2)

    assert keys.get(key) is None
    assert key not in keys
    assert keys.setdefault(key, 9) == 9
    assert keys[key] == 9


def _upper(key: str) -> str:
    return key.upper()


def test_key_default_dict_copies_and_pickles_with_its_factory() -> None:
    d = KeyDefaultDict(_upper)
    d["a"] = "x"

    for clone in (copy.copy(d), pickle.loads(pickle.dumps(d))):  # noqa: S301 - our own pickle
        assert type(clone) is KeyDefaultDict
        assert dict(clone) == {"a": "x"}
        assert clone.default_factory is _upper
        assert clone["b"] == "B"
