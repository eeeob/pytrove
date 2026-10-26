"""`data_tools._internal.cleaning`: the step behind `clean_none_values`."""

from __future__ import annotations as _annotations

from collections import UserString

from pytrove._internal import _MESS
from pytrove.data_tools._internal.cleaning import _none_cleaner


def test_none_cleaner_drops_none_and_cleans_the_rest() -> None:
    assert _none_cleaner(None) is _MESS
    assert _none_cleaner([1, None]) == [1]
    assert _none_cleaner({"a": None, "b": [None, 2]}) == {"b": [2]}
    assert _none_cleaner(0) == 0


def test_none_cleaner_walks_mappings_and_leaves_text_whole() -> None:
    assert _none_cleaner({"a": None, "b": [None, 1]}) == {"b": [1]}
    text = UserString("ab")
    assert _none_cleaner(text) is text
