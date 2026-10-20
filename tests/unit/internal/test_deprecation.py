from __future__ import annotations as _annotations

import pytest

from pytrove._internal._deprecation import _moved_attribute


def test_moved_attribute_warns_and_resolves() -> None:
    with pytest.warns(DeprecationWarning, match="old.to_str is deprecated"):
        assert _moved_attribute("old", {"to_str": "pytrove.text_tools"}, "to_str")(1) == "1"


def test_moved_attribute_refuses_an_unknown_name() -> None:
    with pytest.raises(AttributeError, match="no attribute"):
        _moved_attribute("old", {}, "missing")
