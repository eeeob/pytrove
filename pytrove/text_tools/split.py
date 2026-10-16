"""Splitting text into cleaned, filtered and converted parts."""

from __future__ import annotations as _annotations

from collections.abc import Callable
from typing import Any, overload

from ..iter_tools import flat_cont, to_list
from ..typings import NestedContainer, _T
from ._internal import _smart_split_part


@overload
def smart_split(
    text: NestedContainer[str],
    indexing: int,
    part_resolver: Callable[[str], _T],
    strip: bool = ...,
    remove_spaces: bool = ...,
    max_split: int = ...,
    part_filter: Callable[[str], bool] | None = ...,
    *,
    separator: str | Callable[[], str],
) -> _T: ...
@overload
def smart_split(
    text: NestedContainer[str],
    indexing: int,
    *,
    strip: bool = ...,
    remove_spaces: bool = ...,
    max_split: int = ...,
    part_filter: Callable[[str], bool] | None = ...,
    separator: str | Callable[[], str],
) -> str: ...
@overload
def smart_split(
    text: NestedContainer[str],
    indexing: slice,
    part_resolver: Callable[[str], _T],
    strip: bool = ...,
    remove_spaces: bool = ...,
    max_split: int = ...,
    part_filter: Callable[[str], bool] | None = ...,
    *,
    separator: str | Callable[[], str],
) -> list[_T]: ...
@overload
def smart_split(
    text: NestedContainer[str],
    indexing: slice,
    *,
    strip: bool = ...,
    remove_spaces: bool = ...,
    max_split: int = ...,
    part_filter: Callable[[str], bool] | None = ...,
    separator: str | Callable[[], str],
) -> list[str]: ...
@overload
def smart_split(
    text: NestedContainer[str],
    *,
    part_resolver: Callable[[str], _T],
    strip: bool = ...,
    remove_spaces: bool = ...,
    max_split: int = ...,
    part_filter: Callable[[str], bool] | None = ...,
    separator: str | Callable[[], str],
) -> list[_T]: ...
@overload
def smart_split(
    text: NestedContainer[str],
    *,
    strip: bool = ...,
    remove_spaces: bool = ...,
    max_split: int = ...,
    part_filter: Callable[[str], bool] | None = ...,
    separator: str | Callable[[], str],
) -> list[str]: ...
def smart_split(
    text: NestedContainer[str],
    indexing: int | slice | None = None,
    part_resolver: Callable[[str], Any] | None = None,
    strip: bool = False,
    remove_spaces: bool = False,
    max_split: int = -1,
    part_filter: Callable[[str], bool] | None = None,
    *,
    separator: str | Callable[[], str],
) -> Any:
    """Split text into parts, then select, filter, clean and convert them.

    `part_filter` sees each raw part, before cleaning, so `bool` keeps a
    whitespace-only part; filter on `t.strip()` to drop those.

    Args:
        text: A string to split, or a container of parts already split, which
            is flattened instead and ignores `separator` and `max_split`.
        indexing: An int to return one part unwrapped, or a slice of parts.
        part_resolver: Converts each kept part.
        strip: Whether to strip whitespace around each part.
        remove_spaces: Whether to remove all whitespace in each part.
        max_split: The most splits to make; `-1` for no limit.
        part_filter: Keeps a raw part when it returns true.
        separator: The separator, or a zero-argument callable returning it.

    Returns:
        The selected part for an int `indexing`, otherwise the list of parts.

    Raises:
        IndexError: If an int `indexing` is out of range or its part is filtered out.
    """
    if not isinstance(separator, str):
        separator = separator()

    parts = text.split(separator, max_split) if isinstance(text, str) else flat_cont(text)

    if indexing is not None:
        parts = to_list(parts[indexing])

    kept = []

    for part in parts:
        keep, value = _smart_split_part(part, part_filter, strip, remove_spaces, part_resolver)

        if keep:
            kept.append(value)

    return kept[0] if isinstance(indexing, int) else kept


__all__ = ("smart_split",)
