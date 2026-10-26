"""Helpers private to `validate_tools`."""

from __future__ import annotations as _annotations

import sys
from enum import (
    Enum,
    EnumMeta as EnumType,
)  # `EnumType` became the name of `EnumMeta` only in 3.11.
from types import UnionType
from typing import TYPE_CHECKING, Any, Final, TypeAlias, Union, get_args, get_origin

try:
    from typeguard import TypeCheckError, TypeCheckMemo, check_type_internal  # type: ignore[import-not-found]  # Optional: the `typecheck` extra.
except ImportError:
    HAS_TYPEGUARD = False
else:
    HAS_TYPEGUARD = True

from .._internal import _optional_import
from ..typings import Container, ContainerWithoutMapping, NotContainer

if TYPE_CHECKING:
    from collections.abc import Callable

_CONTAINER: Final[tuple[type, ...]] = tuple(
    get_origin(arg) or arg for arg in get_args(getattr(Container, "__value__", Container))
)
"""The classes `Container` stands for, ready for `isinstance`."""

_NOT_CONTAINER: Final[tuple[type, ...]] = tuple(
    get_origin(arg) or arg for arg in get_args(getattr(NotContainer, "__value__", NotContainer))
)
"""The iterable classes treated as single values, ready for `isinstance`."""

if sys.version_info >= (3, 12):
    from typing import TypeAliasType

    _ALIAS_TYPES: Final[tuple[type, ...]] = (TypeAliasType,)
else:
    _ALIAS_TYPES: Final[tuple[type, ...]] = ()
"""The classes of PEP 695 aliases, whose parametrised forms typeguard cannot see through on its own."""

_CONTAINER_ALIASES: Final[tuple[Any, ...]] = (Container, ContainerWithoutMapping)
"""The package's container aliases, checked by `is_container` rather than as plain unions.

Expanding them would let typeguard treat a `str` as a `Sequence` and walk
into its own characters forever.
"""

# The nested tuple is typed `Any` rather than recursively: a quoted self-reference is allowed only in the
# pre-3.12 branch of a version split (rule 4.2), and a split here would cost a module for one private alias.
_ClassInfo: TypeAlias = type | UnionType | tuple[Any, ...]
"""What `isinstance` accepts as its second argument, nested tuples included."""


def _flatten_class_info(class_info: _ClassInfo) -> tuple[type, ...]:
    """Normalise `class_info` into the flat tuple of types `isinstance` always accepts.

    `typing.Union[...]` is unwrapped (bare `isinstance` rejects it before
    3.14), and tuples are flattened recursively in first-seen order.

    Args:
        class_info: A type, an `X | Y` or `Union[...]`, or a nested tuple of them.

    Returns:
        Every type named, each once.
    """
    if isinstance(class_info, tuple):
        flattened: dict[type, None] = {}

        for c in class_info:
            for t in _flatten_class_info(c):
                flattened[t] = None

        return tuple(flattened)

    if isinstance(class_info, UnionType) or get_origin(class_info) is Union:
        return _flatten_class_info(get_args(class_info))

    return (class_info,)


def _is_container(obj: Any) -> bool:
    """Tell whether `obj` is a container in the package's sense.

    Args:
        obj: The value to test.

    Returns:
        Whether it is a `Container` and not a `NotContainer`.
    """
    return isinstance(obj, _CONTAINER) and not isinstance(obj, _NOT_CONTAINER)


@_optional_import(("typeguard", "typecheck"))
def _checker_lookup(origin_type: Any, args: tuple[Any, ...], *_: Any) -> Callable[..., None] | None:
    """Teach typeguard the package's three extra checks; registered by `typecheck`.

    A value checked against an `Enum` passes if it is any member's value, a
    value checked against `Container[X]` is walked and each item checked
    against `X`, and a parametrised PEP 695 alias (3.12+) is checked as the type
    it stands for. Returning `None` leaves every other type to typeguard.

    Args:
        origin_type: The type typeguard is checking against.
        args: Its type arguments.
        *_: The rest of typeguard's lookup arguments, unused.

    Returns:
        A checker for an enum, a package container type or a parametrised PEP 695
        alias, otherwise `None`.
    """

    def validate_alias(
        value: Any, origin_type: Any, args: tuple[Any, ...], memo: TypeCheckMemo, *_: Any
    ) -> None:
        """Check `value` against the type a parametrised PEP 695 alias stands for.

        Args:
            value: The value being checked.
            origin_type: The alias.
            args: The alias's type arguments, substituted into its value.
            memo: typeguard's check state.
            *_: The rest of typeguard's checker arguments, unused.
        """
        check_type_internal(value, origin_type.__value__[args], memo)

    def validate_enum(value: Any, origin_type: EnumType, *_: Any) -> None:
        """Accept any value of the enum, not only its members.

        Args:
            value: The value being checked.
            origin_type: The enum class.
            *_: The rest of typeguard's checker arguments, unused.

        Raises:
            TypeCheckError: If no member has `value` as its value.
        """
        try:
            origin_type(value)
        except (ValueError, TypeError) as exc:
            raise TypeCheckError(str(exc)) from exc

    def validate_container(
        value: Any, origin_type: Any, args: tuple[Any, ...], memo: TypeCheckMemo, *_: Any
    ) -> None:
        """Check that `value` is a container whose items match the type argument.

        Args:
            value: The value being checked.
            origin_type: The container type, unused beyond the lookup.
            args: The container's type arguments.
            memo: typeguard's check state.
            *_: The rest of typeguard's checker arguments, unused.

        Raises:
            TypeCheckError: If `value` is not a container or an item does not match.
        """
        del origin_type  # The lookup already matched it; only the arguments matter now.

        if not _is_container(value):
            msg = "is not container"
            raise TypeCheckError(msg)

        if not args or args == (Any,):
            return

        for i, v in enumerate(memo.config.collection_check_strategy.iterate_samples(value)):
            try:
                check_type_internal(v, args[0], memo)
            except TypeCheckError as exc:
                exc.append_path_element(f"item {i}")
                raise

    if origin_type in _CONTAINER_ALIASES:
        return validate_container

    # typeguard 4.6 unwraps a plain `type X = ...` alias itself, but still accepts a bad value
    # for a parametrised one such as `Pair[int]`, so only that case is handled here.
    if args and isinstance(origin_type, _ALIAS_TYPES):
        return validate_alias

    if isinstance(origin_type, type) and issubclass(origin_type, Enum):
        return validate_enum

    if (
        isinstance(origin_type, type)
        and issubclass(origin_type, _CONTAINER)
        and not issubclass(origin_type, _NOT_CONTAINER)
    ):
        return validate_container

    return None


__all__ = (
    "_ClassInfo",
    "_checker_lookup",
    "_flatten_class_info",
    "_is_container",
    "_CONTAINER",
    "_ALIAS_TYPES",
    "_CONTAINER_ALIASES",
    "_NOT_CONTAINER",
    "HAS_TYPEGUARD",
)
