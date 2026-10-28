"""Splitting text into cleaned, filtered and converted parts."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, Any, overload

from ..iter_tools import flat_cont, to_list
from ._internal import _WHITESPACE_PATTERN

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..typings import NestedContainer, _T


@overload
def smart_split(
    text: NestedContainer[str],
    indexing: int,
    part_resolver: Callable[[str], _T],
    strip: bool = False,
    remove_spaces: bool = False,
    max_split: int = -1,
    part_filter: Callable[[str], bool] | None = None,
    *,
    separator: str | None | Callable[[], str | None],
) -> _T: ...
@overload
def smart_split(
    text: NestedContainer[str],
    indexing: int,
    part_resolver: None = None,
    strip: bool = False,
    remove_spaces: bool = False,
    max_split: int = -1,
    part_filter: Callable[[str], bool] | None = None,
    *,
    separator: str | None | Callable[[], str | None],
) -> str: ...
@overload
def smart_split(
    text: NestedContainer[str],
    indexing: slice,
    part_resolver: Callable[[str], _T],
    strip: bool = False,
    remove_spaces: bool = False,
    max_split: int = -1,
    part_filter: Callable[[str], bool] | None = None,
    *,
    separator: str | None | Callable[[], str | None],
) -> list[_T]: ...
@overload
def smart_split(
    text: NestedContainer[str],
    indexing: slice,
    part_resolver: None = None,
    strip: bool = False,
    remove_spaces: bool = False,
    max_split: int = -1,
    part_filter: Callable[[str], bool] | None = None,
    *,
    separator: str | None | Callable[[], str | None],
) -> list[str]: ...
@overload
def smart_split(
    text: NestedContainer[str],
    indexing: None,
    part_resolver: Callable[[str], _T],
    strip: bool = False,
    remove_spaces: bool = False,
    max_split: int = -1,
    part_filter: Callable[[str], bool] | None = None,
    *,
    separator: str | None | Callable[[], str | None],
) -> list[_T]: ...
@overload
def smart_split(
    text: NestedContainer[str],
    indexing: None = None,
    *,
    part_resolver: Callable[[str], _T],
    strip: bool = False,
    remove_spaces: bool = False,
    max_split: int = -1,
    part_filter: Callable[[str], bool] | None = None,
    separator: str | None | Callable[[], str | None],
) -> list[_T]: ...
@overload
def smart_split(
    text: NestedContainer[str],
    indexing: None = None,
    part_resolver: None = None,
    strip: bool = False,
    remove_spaces: bool = False,
    max_split: int = -1,
    part_filter: Callable[[str], bool] | None = None,
    *,
    separator: str | None | Callable[[], str | None],
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
    separator: str | None | Callable[[], str | None],
) -> Any:
    """Split text into parts, then select, filter, clean and convert them.

    `indexing` selects among the raw parts first; `part_filter` then sees
    each selected part before cleaning, so `bool` keeps a whitespace-only
    part; filter on `t.strip()` to drop those.

    Args:
        text: A string to split, or a container of parts already split, which
            is flattened with `flat_cont` instead (`None` leaves dropped, a
            mapping gives its keys) and ignores `separator` and `max_split`.
        indexing: An int to return one part unwrapped, or a slice of parts.
        part_resolver: Converts each kept part.
        strip: Whether to strip whitespace around each part.
        remove_spaces: Whether to remove all whitespace in each part; wins over `strip`.
        max_split: The most splits to make; `-1` for no limit.
        part_filter: Keeps a raw part when it returns true.
        separator: The separator, or a zero-argument callable returning it;
            `None` splits on runs of whitespace, as `str.split` does.

    Returns:
        The selected part for an int `indexing`, otherwise the list of parts.

    Raises:
        IndexError: If an int `indexing` is out of range or its part is filtered out.
        ValueError: If `separator` is an empty string.

    Example:
        >>> smart_split("1, 2, 3", separator=",")
        ['1', ' 2', ' 3']
        >>> smart_split("1, 2, 3", slice(1, None), strip=True, separator=",")
        ['2', '3']
        >>> smart_split("1, 2, 3", 0, int, separator=",")
        1
    """
    if not isinstance(separator, str) and callable(separator):
        separator = separator()

    parts = text.split(separator, max_split) if isinstance(text, str) else flat_cont(text)

    if indexing is not None:
        parts = to_list(parts[indexing])

    kept = []

    for part in parts:
        if part_filter is not None and not part_filter(part):
            continue

        if remove_spaces:
            cleaned = _WHITESPACE_PATTERN.sub("", part)
        else:
            cleaned = part.strip() if strip else part

        kept.append(cleaned if part_resolver is None else part_resolver(cleaned))

    return kept[0] if isinstance(indexing, int) else kept


__all__ = ("smart_split",)
