"""Helpers private to the `models` section."""

from __future__ import annotations as _annotations

import inspect
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import Enum
from logging import Logger, LogRecord, getLogger
from types import UnionType
from typing import Annotated, Any, Final, Union, get_args, get_origin, get_type_hints, is_typeddict

if sys.version_info >= (3, 14):
    import annotationlib

from .._internal import _reconstruct, _reconstruct_mapping
from ..errors import ValidationError
from ..validate_tools import is_container, is_mapping

_INV_PHI: Final[float] = 0.6180339887498949
"""`(5 ** 0.5 - 1) / 2`: the golden-ratio step `Jitter` walks its window with."""

_WOBBLE_SPREAD: Final[float] = 0.28
"""The widest noise `Jitter` adds to its step, as a fraction of `_INV_PHI`.

With it the step stays inside `_INV_PHI * (1 +/- 0.28)`, about `[0.445, 0.791]`,
so the wrapped CDF gap between two consecutive values never falls under about
`0.209` (`1 - 0.791`): two draws in a row cannot cluster.
"""


@dataclass(slots=True, kw_only=True)
class _LoggerModel:
    """The logger fields every logging options model shares."""

    logger: Logger | str | None = None
    """A `Logger`, a logger name, or `None` for the root logger; `resolve_logger()` replaces it with the `Logger`."""

    level: int | None = None
    """The level to set; `None` leaves it alone."""

    filter: Callable[[LogRecord], bool] | None = None
    """A filter to add; `None` adds none."""

    def resolve_logger(self) -> Logger:
        """Replace a name or `None` in `logger` with the `Logger` it names, and return it.

        Returns:
            The resolved logger.

        Raises:
            ValidationError: If `logger` is neither a `Logger`, a name, nor `None`.
        """
        logger = self.logger

        if logger is None or isinstance(logger, str):
            logger = getLogger(logger)
        elif not isinstance(logger, Logger):
            msg = f"Invalid Logger {logger}"
            raise ValidationError(msg)

        self.logger = logger
        return logger


def _resolved_hints(cls: type) -> dict[str, Any]:
    """Return every annotation on `cls` and its bases, each resolved on its own.

    `get_type_hints(cls)` resolves all of them together, so one annotation
    naming a type that is not importable here (an optional extra's class, or
    one imported only under `TYPE_CHECKING`), a missing attribute, or a bad
    subscript would fail the whole class. Such an annotation is skipped
    instead: its field has no enum type to find, which is the same as not
    having one, and the rest of the class still works. From 3.14 annotations
    are read as forward references, since reading their values would evaluate
    every one of them in a module without `from __future__ import annotations`.

    Args:
        cls: The class to read.

    Returns:
        Each resolvable annotation by name; a subclass's annotation replaces its base's.
    """
    hints: dict[str, Any] = {}

    for klass in reversed(cls.__mro__):
        if sys.version_info >= (3, 14):
            annotations = annotationlib.get_annotations(
                klass, format=annotationlib.Format.FORWARDREF
            )
        else:
            annotations = inspect.get_annotations(klass)

        for name, annotation in annotations.items():
            holder = type(
                "_AnnotationHolder",
                (),
                {"__annotations__": {name: annotation}, "__module__": klass.__module__},
            )

            try:
                hints[name] = get_type_hints(holder)[name]
            except (NameError, AttributeError, TypeError):
                continue

    return hints


def _is_enum(hint: Any) -> bool:
    """Tell whether a type hint is an enum class itself."""
    return isinstance(hint, type) and issubclass(hint, Enum)


def _iter_enums(hint: Any) -> Iterator[type[Enum]]:
    """Yield every enum class inside a type hint, walking `get_origin()`/`get_args()`.

    Args:
        hint: A resolved type hint.

    Yields:
        Each enum class it names, at any depth.
    """
    if _is_enum(hint):
        yield hint
    elif is_typeddict(hint):
        for value_hint in _resolved_hints(hint).values():
            yield from _iter_enums(value_hint)
    elif (origin := get_origin(hint)) is not None:
        for arg in (*get_args(hint), origin):
            yield from _iter_enums(arg)


def _enum_member(enum: type[Enum], value: Any) -> Any:
    """Return the member of `enum` whose value is `value`, or `value` itself when there is none.

    Args:
        enum: The enum class the hint names.
        value: A leaf value; a container or mapping is never a member's value here.

    Returns:
        The member, or `value` unchanged.
    """
    if isinstance(value, enum) or is_container(value) or is_mapping(value):
        return value

    try:
        return enum(value)
    except (ValueError, TypeError):  # No such value, or an unhashable one.
        return value


def _union_to_enums(value: Any, arms: tuple[Any, ...]) -> Any:
    """Convert `value` by the first arm of a union that turns it into something else.

    Enum arms are tried first, so `str | Status` turns `"on"` into `Status.ON`;
    then the arms holding an enum deeper, such as `list[Status]` in
    `list[Status] | None`. Arms are tried in the order the annotation lists them.

    Args:
        value: The value.
        arms: The union's members.

    Returns:
        The converted value, or `value` unchanged.
    """
    for arm in arms:
        if _is_enum(arm) and (member := _enum_member(arm, value)) is not value:
            return member

    for arm in arms:
        if not _is_enum(arm) and (converted := _to_enums(value, arm)) is not value:
            return converted

    return value


def _to_enums(value: Any, hint: Any) -> Any:
    """Turn raw values into enum members exactly where `hint` says an enum goes.

    Containers are walked only along hints that hold an enum, and rebuilt as
    their own type by `_reconstruct`/`_reconstruct_mapping` (a `defaultdict`
    keeps its factory, a namedtuple its class): `str` next to a `ButtonStyle`
    stays a `str` even when it equals a member's value, and in
    `dict[str, Status]` only the values are converted, never the keys.

    Args:
        value: The value, as the dict being loaded holds it.
        hint: The resolved annotation of the field, or of the part of it `value` is.

    Returns:
        The value with members in the places `hint` types as enums.
    """
    if _is_enum(hint):
        return _enum_member(hint, value)

    if next(_iter_enums(hint), None) is None:
        return value  # No enum anywhere below: nothing to convert, nothing to rebuild.

    origin, args = get_origin(hint), get_args(hint)

    if origin is Annotated:
        return _to_enums(value, args[0])

    if origin is Union or origin is UnionType:
        return _union_to_enums(value, args)

    if is_typeddict(hint):
        if type(value) is not dict:
            return value

        fields = _resolved_hints(hint)
        return {k: _to_enums(v, fields[k]) if k in fields else v for k, v in value.items()}

    if not isinstance(origin, type) or not args:
        return value

    if issubclass(origin, tuple) and is_container(value) and isinstance(value, tuple):
        if len(args) == 2 and args[1] is Ellipsis:  # `tuple[T, ...]`
            return _reconstruct(value, lambda v: _to_enums(v, args[0]))

        if len(args) != len(value):
            return value

        # `_reconstruct` passes the items through once, in order, so each takes the next hint.
        item_hints = iter(args)
        return _reconstruct(value, lambda v: _to_enums(v, next(item_hints)))

    if issubclass(origin, Mapping) and len(args) == 2 and is_mapping(value):
        key_hint, value_hint = args
        return _reconstruct_mapping(
            value, lambda k: _to_enums(k, key_hint), lambda v: _to_enums(v, value_hint)
        )

    if issubclass(origin, Iterable) and len(args) == 1 and is_container(value):
        if is_mapping(value):
            return value  # `Counter[Status]` and the like: rebuilding from keys alone loses the values.

        return _reconstruct(value, lambda v: _to_enums(v, args[0]))

    return value


__all__ = (
    "_INV_PHI",
    "_WOBBLE_SPREAD",
    "_LoggerModel",
    "_enum_member",
    "_is_enum",
    "_iter_enums",
    "_resolved_hints",
    "_to_enums",
    "_union_to_enums",
)
