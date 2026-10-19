from __future__ import annotations as _annotations

import importlib

import pytest

from pytrove import misc_tools


def test_misc_tools_exports_exactly_the_moved_names() -> None:
    assert misc_tools.__all__ == tuple(misc_tools._MOVED)
    assert set(misc_tools._MOVED.values()) == {"pytrove.object_tools", "pytrove.crypto_tools"}


@pytest.mark.parametrize("name", list(misc_tools._MOVED))
def test_misc_tools_resolves_a_moved_name_with_a_deprecation_warning(name: str) -> None:
    with pytest.warns(DeprecationWarning, match=f"pytrove.misc_tools.{name} is deprecated"):
        assert getattr(misc_tools, name) is getattr(importlib.import_module(misc_tools._MOVED[name]), name)


def test_misc_tools_refuses_a_name_it_never_held() -> None:
    with pytest.raises(AttributeError, match="never_existed"):
        misc_tools.never_existed  # noqa: B018 - the attribute access is the case under test.
