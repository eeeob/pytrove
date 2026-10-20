from __future__ import annotations as _annotations

import pytrove._internal


def test_internal_package_exports_nothing() -> None:
    assert pytrove._internal.__all__ == ()
