from __future__ import annotations as _annotations

import os

import pytest

from pytrove._internal._stability import _default_stability_check, _STABILITY_MIN_SIZE


def _stat_of_size(size: int) -> os.stat_result:
    """Build a real `os.stat_result` whose only meaningful field is `st_size`."""
    fields = [0] * 10
    fields[6] = size
    return os.stat_result(fields)


def test_stability_min_size_is_one_mebibyte() -> None:
    assert _STABILITY_MIN_SIZE == 1 << 20


@pytest.mark.parametrize(
    ("size", "guarded"),
    [
        (0, False),
        (_STABILITY_MIN_SIZE - 1, False),
        (_STABILITY_MIN_SIZE, True),
        (_STABILITY_MIN_SIZE * 4, True),
    ],
)
def test_default_stability_check_guards_only_files_at_least_the_minimum_size(
    size: int, guarded: bool
) -> None:
    assert _default_stability_check(_stat_of_size(size), "ignored/path") is guarded
