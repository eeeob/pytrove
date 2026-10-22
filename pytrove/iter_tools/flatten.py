"""Flattening nested containers and mappings into their leaves."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, Any, overload

from ..validate_tools import is_container, is_mapping

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Mapping

    from ..typings import NestedContainer, NestedContainerMappingValue, _False, _KT, _T, _True, _VT


@overload
def iter_flat_cont(
    *containers: NestedContainer[_T | None], exclude_none: _True = True
) -> Generator[_T, None, None]: ...
@overload
def iter_flat_cont(
    *containers: NestedContainer[_T], exclude_none: _False
) -> Generator[_T, None, None]: ...
def iter_flat_cont(*containers: Any, exclude_none: bool = True) -> Generator[Any, None, None]:
    """Yield every leaf under `containers`, flattening nested containers lazily.

    A mapping counts as a container of its keys.

    Args:
        *containers: Leaves or containers of them, at any depth.
        exclude_none: Whether to drop `None` leaves.

    Yields:
        Each leaf, depth first, in order.
    """
    for item in containers:
        if is_container(item):
            yield from iter_flat_cont(*item, exclude_none=exclude_none)
        elif not exclude_none or item is not None:
            yield item


@overload
def flat_cont(*containers: NestedContainer[_T | None], exclude_none: _True = True) -> list[_T]: ...
@overload
def flat_cont(*containers: NestedContainer[_T], exclude_none: _False) -> list[_T]: ...
def flat_cont(*containers: Any, exclude_none: bool = True) -> list[Any]:
    """Collect `iter_flat_cont` into a list.

    Args:
        *containers: Leaves or containers of them, at any depth.
        exclude_none: Whether to drop `None` leaves.

    Returns:
        Every leaf, depth first, in order.

    Example:
        >>> flat_cont([1, [2, None, (3,)]], 4)
        [1, 2, 3, 4]
        >>> flat_cont([1, None], exclude_none=False)
        [1, None]
        >>> flat_cont({"a": 1})
        ['a']
    """
    return list(iter_flat_cont(*containers, exclude_none=exclude_none))


@overload
def iter_flat_map(
    *containers: Mapping[_KT, NestedContainerMappingValue[_KT, _VT | None]],
    exclude_none: _True = True,
) -> Generator[_KT | _VT, None, None]: ...
@overload
def iter_flat_map(
    *containers: Mapping[_KT, NestedContainerMappingValue[_KT, _VT]],
    exclude_none: _False,
) -> Generator[_KT | _VT, None, None]: ...
@overload
def iter_flat_map(
    *containers: NestedContainer[_T | None], exclude_none: _True = True
) -> Generator[_T, None, None]: ...
@overload
def iter_flat_map(
    *containers: NestedContainer[_T], exclude_none: _False
) -> Generator[_T, None, None]: ...
def iter_flat_map(*containers: Any, exclude_none: bool = True) -> Generator[Any, None, None]:
    """Yield every leaf like `iter_flat_cont`, but a mapping gives up its values as well as its keys.

    `{"a": 1}` yields `"a"` then `1`, pair by pair, at any depth.

    Args:
        *containers: Leaves, containers or mappings, at any depth.
        exclude_none: Whether to drop `None` leaves.

    Yields:
        Each key and leaf, depth first, in order.
    """
    for item in containers:
        if is_mapping(item):
            yield from iter_flat_map(*item.items(), exclude_none=exclude_none)
        elif is_container(item):
            yield from iter_flat_map(*item, exclude_none=exclude_none)
        elif not exclude_none or item is not None:
            yield item


@overload
def flat_map(
    *containers: Mapping[_KT, NestedContainerMappingValue[_KT, _VT | None]],
    exclude_none: _True = True,
) -> list[_KT | _VT]: ...
@overload
def flat_map(
    *containers: Mapping[_KT, NestedContainerMappingValue[_KT, _VT]],
    exclude_none: _False,
) -> list[_KT | _VT]: ...
@overload
def flat_map(*containers: NestedContainer[_T | None], exclude_none: _True = True) -> list[_T]: ...
@overload
def flat_map(*containers: NestedContainer[_T], exclude_none: _False) -> list[_T]: ...
def flat_map(*containers: Any, exclude_none: bool = True) -> list[Any]:
    """Collect `iter_flat_map` into a list.

    Args:
        *containers: Leaves, containers or mappings, at any depth.
        exclude_none: Whether to drop `None` leaves.

    Returns:
        Every key and leaf, depth first, in order.

    Example:
        >>> flat_map({"a": [1, {"b": 2}]})
        ['a', 1, 'b', 2]
    """
    return list(iter_flat_map(*containers, exclude_none=exclude_none))


def iter_flat_cont_by(
    *containers: Any,
    is_container: Callable[[Any], bool] = is_container,
    exclude_none: bool = True,
) -> Generator[Any, None, None]:
    """Yield every leaf like `iter_flat_cont`, with your own test for what to descend into.

    Args:
        *containers: Leaves or containers of them, at any depth.
        is_container: Decides, per item, whether it is a container to flatten.
        exclude_none: Whether to drop `None` leaves.

    Yields:
        Each leaf, depth first, in order.
    """
    for item in containers:
        if is_container(item):
            yield from iter_flat_cont_by(
                *item, is_container=is_container, exclude_none=exclude_none
            )
        elif not exclude_none or item is not None:
            yield item


def flat_cont_by(
    *containers: Any,
    is_container: Callable[[Any], bool] = is_container,
    exclude_none: bool = True,
) -> list[Any]:
    """Collect `iter_flat_cont_by` into a list.

    Args:
        *containers: Leaves or containers of them, at any depth.
        is_container: Decides, per item, whether it is a container to flatten.
        exclude_none: Whether to drop `None` leaves.

    Returns:
        Every leaf, depth first, in order.

    Example:
        >>> flat_cont_by((1, [2], (3, 4)), is_container=lambda x: isinstance(x, tuple))
        [1, [2], 3, 4]
    """
    return list(
        iter_flat_cont_by(*containers, is_container=is_container, exclude_none=exclude_none)
    )


__all__ = (
    "iter_flat_cont",
    "flat_cont",
    "iter_flat_cont_by",
    "flat_cont_by",
    "iter_flat_map",
    "flat_map",
)
