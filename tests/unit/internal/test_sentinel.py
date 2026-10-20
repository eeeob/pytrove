from __future__ import annotations as _annotations

import pytest

from pytrove._internal._sentinel import _is_given


def test_the_object_class_means_not_given() -> None:
    assert _is_given(object) is False


@pytest.mark.parametrize("value", [None, 0, "", [], object(), int])
def test_anything_else_is_given(value: object) -> None:
    assert _is_given(value) is True


def test_sentinel_module_exports_only_is_given() -> None:
    import pytrove._internal._sentinel as sentinel

    assert sentinel.__all__ == ("_is_given",)
