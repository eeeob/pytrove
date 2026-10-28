"""Static checks of the `smart_split` overloads: `make typecheck` runs `ty` on this file.

Each `assert_type` fails `ty` when an overload resolves to another type; the test
also runs under pytest, so every call is valid at runtime too.
"""

from __future__ import annotations as _annotations

import sys
from typing import TYPE_CHECKING

from pytrove.text_tools import smart_split

if sys.version_info >= (3, 11):
    from typing import assert_type
else:
    from typing_extensions import assert_type

if TYPE_CHECKING:
    from collections.abc import Callable


def test_smart_split_overloads_pick_the_return_type() -> None:
    separator: str | None | Callable[[], str | None] = ","

    assert_type(smart_split("1,2", 0, int, separator=separator), int)
    assert_type(smart_split("1,2", 0, separator=","), str)
    assert_type(smart_split("1,2", 0, None, True, separator=","), str)
    assert_type(smart_split("1,2", slice(0, 1), int, separator=","), list[int])
    assert_type(smart_split("1,2", slice(0, 1), separator=","), list[str])
    assert_type(smart_split("1,2", None, int, separator=","), list[int])
    assert_type(smart_split("1,2", part_resolver=int, separator=","), list[int])
    assert_type(smart_split("1,2", separator=None), list[str])
