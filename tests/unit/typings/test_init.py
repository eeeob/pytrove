from __future__ import annotations as _annotations

import pytrove.typings
from pytrove.typings import archive, core, template


def test_the_entry_point_is_the_union_of_its_modules() -> None:
    assert pytrove.typings.__all__ == (*archive.__all__, *core.__all__, *template.__all__)
    assert all(hasattr(pytrove.typings, name) for name in pytrove.typings.__all__)
