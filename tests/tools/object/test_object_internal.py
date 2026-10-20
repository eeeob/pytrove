from __future__ import annotations as _annotations

from collections.abc import Hashable

from pytrove.object_tools._internal import _WeakRegistryKT


def test_weak_registry_key_type_is_hashable_and_defaults_to_int() -> None:
    assert _WeakRegistryKT.__bound__ is Hashable
    assert _WeakRegistryKT.__default__ is int
