"""Helpers private to the `models` section."""

from __future__ import annotations as _annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from logging import Logger, LogRecord, getLogger
from typing import Any, Final, get_type_hints

from ..errors import ValidationError

_INV_PHI: Final[float] = 0.6180339887498949
"""`(5 ** 0.5 - 1) / 2`: the golden-ratio step `Jitter` walks its window with."""


@dataclass(slots=True, kw_only=True)
class _LoggerModel:
    """The logger fields every logging options model shares.

    Attributes:
        logger: A `Logger`, a logger name, or `None` for the root logger.
        level: The level to set, if any.
        filter: A filter to add, if any.
    """

    logger: Logger | str | None = None

    level: int | None = None
    filter: Callable[[LogRecord], bool] | None = None

    def resolve_logger(self) -> Logger:
        """Replace a name or `None` in `logger` with the `Logger` it names, and return it.

        Returns:
            The resolved logger.

        Raises:
            ValidationError: If `logger` is neither a `Logger`, a name, nor `None`.
        """
        logger = self.logger

        if logger is None or isinstance(logger, str):
            self.logger = getLogger(logger)
        elif not isinstance(logger, Logger):
            msg = f"Invalid Logger {logger}"
            raise ValidationError(msg)

        return self.logger


def _resolved_hints(cls: type) -> list[Any]:
    """Return every annotation on `cls` and its bases, each resolved on its own.

    `get_type_hints(cls)` resolves all of them together, so one annotation
    naming a type that is not importable here (an optional extra's class, or
    one imported only under `TYPE_CHECKING`) would fail the whole class. Such
    an annotation is skipped instead: its field has no enum type to find,
    which is the same as not having one, and the rest of the class still works.

    Args:
        cls: The class to read.

    Returns:
        The resolved annotations, base classes first.
    """
    hints = []

    for klass in reversed(cls.__mro__):
        for name, annotation in inspect.get_annotations(klass).items():
            holder = type("_AnnotationHolder", (), {"__annotations__": {name: annotation}, "__module__": klass.__module__})

            try:
                hints.append(get_type_hints(holder)[name])
            except NameError:
                continue

    return hints


__all__ = ("_INV_PHI", "_LoggerModel", "_resolved_hints")
