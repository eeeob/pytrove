"""Configuring loggers and handlers from option models."""

from __future__ import annotations as _annotations

import logging
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Final, cast, overload

from .iter_tools import iter_flat_cont
from .models import LoggerOptions, LogHandlerOptions
from .typings import Container, NestedContainer, _False, _True

_UTC3: Final[timezone] = timezone(timedelta(hours=3))
"""The fixed UTC+3 zone `UTC3LogFormatter` writes record times in."""


class UTC3LogFormatter(logging.Formatter):
    """A formatter that writes record times in UTC+3, whatever the machine's zone."""

    @staticmethod
    def _to_utc3(stamp: float | None = None) -> time.struct_time:
        """Convert a record's timestamp to UTC+3.

        Args:
            stamp: The record's Unix timestamp; `None` means now, as with `time.localtime`.

        Returns:
            The time tuple in UTC+3.
        """
        stamp = time.time() if stamp is None else stamp
        return datetime.fromtimestamp(stamp, tz=_UTC3).timetuple()

    # `Formatter.converter` is a writable attribute, so it is overridden as one, not as a method.
    converter: Callable[[float | None], time.struct_time] = _to_utc3


def flush_logger_handler(handler: logging.Handler | None = None) -> None:
    """Flush one handler, or every handler of every logger.

    Args:
        handler: The handler; `None` flushes all of them, the root's included.
    """
    if handler is not None:
        handler.flush()
        return

    for logger in logging.Logger.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):
            for each in logger.handlers:
                each.flush()

    for each in logging.root.handlers:
        each.flush()


@overload
def attach_logger_handlers(hdlrs_options: LogHandlerOptions, return_loggers: _False = ...) -> logging.Handler: ...
@overload
def attach_logger_handlers(
    hdlrs_options: LogHandlerOptions, return_loggers: _True,
) -> tuple[logging.Logger, logging.Handler]: ...
@overload
def attach_logger_handlers(
    hdlrs_options: Container[NestedContainer[LogHandlerOptions]], return_loggers: _False = ...,
) -> list[logging.Handler]: ...
@overload
def attach_logger_handlers(
    hdlrs_options: Container[NestedContainer[LogHandlerOptions]], return_loggers: _True,
) -> list[tuple[logging.Logger, logging.Handler]]: ...
def attach_logger_handlers(hdlrs_options: NestedContainer[LogHandlerOptions], return_loggers: bool = False) -> Any:
    """Build each described handler, configure it and attach it to its logger.

    Args:
        hdlrs_options: One or more handler descriptions, at any nesting.
        return_loggers: Whether to return `(logger, handler)` pairs.

    Returns:
        The handler (or pair) for a single description, otherwise a list of them.

    Example:
        >>> import io
        >>> logger, handler = attach_logger_handlers(
        ...     LogHandlerOptions(logger="pytrove.example", handler=io.StringIO(), level=logging.INFO),
        ...     return_loggers=True,
        ... )
        >>> logger.name, type(handler).__name__, handler.level
        ('pytrove.example', 'StreamHandler', 20)
        >>> logger.removeHandler(handler)
    """
    handlers: list[Any] = []

    # `ty` binds `_T` to the container arm of the recursive `NestedContainer[_T]`, so
    # it cannot recover the leaf type (astral-sh/ty#1703); the parameter states it.
    for options in cast(Iterator[LogHandlerOptions], iter_flat_cont(hdlrs_options)):
        logger = options.resolve_logger()
        handler = options.resolve_handler()

        if options.level is not None:
            handler.setLevel(options.level)

        if options.filter is not None:
            handler.addFilter(options.filter)

        if options.formatter is not None:
            handler.setFormatter(options.formatter)

        logger.addHandler(handler)
        handlers.append((logger, handler) if return_loggers else handler)

    return handlers[0] if len(handlers) == 1 else handlers


def set_loggers(loggers_options: NestedContainer[LoggerOptions]) -> logging.Logger | list[logging.Logger]:
    """Configure each described logger.

    Args:
        loggers_options: One or more logger descriptions, at any nesting.

    Returns:
        The logger for a single description, otherwise a list of them.

    Example:
        >>> set_loggers(LoggerOptions(logger="pytrove.example", level=logging.DEBUG, propagate=False)).level
        10
    """
    loggers = []

    # `ty` binds `_T` to the container arm of the recursive `NestedContainer[_T]`, so
    # it cannot recover the leaf type (astral-sh/ty#1703); the parameter states it.
    for options in cast(Iterator[LoggerOptions], iter_flat_cont(loggers_options)):
        logger = options.resolve_logger()

        if options.reset_level:
            logger.setLevel(logging.NOTSET)

        if options.propagate is not None:
            logger.propagate = options.propagate

        if options.level is not None:
            logger.setLevel(options.level)

        if options.filter is not None:
            logger.addFilter(options.filter)

        loggers.append(logger)

    return loggers[0] if len(loggers) == 1 else loggers


def get_rotating_log_files(handler: RotatingFileHandler, with_base: bool = True) -> Iterator[Path]:
    """List a rotating handler's files, oldest backup first.

    Args:
        handler: The handler.
        with_base: Whether to end with the current file.

    Yields:
        `<file>.N` down to `<file>.1`, then the file itself.
    """
    base = Path(handler.baseFilename)

    for i in range(handler.backupCount, 0, -1):
        yield base.with_name(f"{base.name}.{i}")

    if with_base:
        yield base


__all__ = (
    "flush_logger_handler",
    "attach_logger_handlers",
    "set_loggers",
    "get_rotating_log_files",
    "UTC3LogFormatter",
)
