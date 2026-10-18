"""Tests of the `data_tools` default dicts that still live here; they belong in `tests/tools/data/`."""

from __future__ import annotations as _annotations

import pytest

from pytrove.data_tools import (
    DefaultWeakKeyDict,
    DefaultWeakValueDict,
    KeyDefaultDict,
    KeyDefaultWeakKeyDict,
    KeyDefaultWeakValueDict,
)
from pytrove.data_tools._factories import _no_arg_factory


class _Box:
    """A weak-referenceable value."""

    def __init__(self, n: int = 0) -> None:
        """Store `n`."""
        self.n = n


def test_key_default_dicts_build_missing_values() -> None:
    plain = KeyDefaultDict(str.upper)
    assert plain["a"] == "A"
    assert plain("b") == "B"

    keyed_values = KeyDefaultWeakValueDict(lambda k: _Box(k))
    assert keyed_values(2).n == 2

    values = DefaultWeakValueDict(_Box)
    held = values["x"]
    assert values["x"] is held

    key = _Box()
    assert KeyDefaultWeakKeyDict(lambda k: k.n)[key] == 0
    assert DefaultWeakKeyDict(list)(key) == []

    for factory in (KeyDefaultWeakValueDict, KeyDefaultWeakKeyDict):
        with pytest.raises(TypeError):
            factory(5)


def test_no_arg_factory_unwraps_its_own_adapter() -> None:
    adapter = _no_arg_factory(list)
    assert adapter("ignored") == []
    assert _no_arg_factory(adapter)("ignored") == []

    with pytest.raises(TypeError):
        _no_arg_factory(5)
