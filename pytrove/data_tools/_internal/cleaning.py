"""Helpers private to `data_tools`: the step behind `clean_none_values`."""

from __future__ import annotations as _annotations

from typing import Any

from ..._internal import _MESS, _reconstruct, _reconstruct_mapping
from ...validate_tools import is_container, is_mapping


def _none_cleaner(value: Any) -> Any:
    """Drop a `None`, and clean `None`s out of anything else; `clean_none_values`' step.

    Args:
        value: One item or mapping value.

    Returns:
        `_MESS` for `None`, otherwise the value cleaned recursively.
    """
    if value is None:
        return _MESS

    if is_mapping(value):
        return _reconstruct_mapping(value, value_func=_none_cleaner)

    if is_container(value):
        return _reconstruct(value, _none_cleaner)

    return value


__all__ = ("_none_cleaner",)
