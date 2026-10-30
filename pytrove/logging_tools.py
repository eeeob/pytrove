"""Configuring loggers and handlers from option models."""

from __future__ import annotations as _annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast, overload

from .constants import TZ_UTC_PLUS_3
from .iter_tools import iter_flat_cont
from .models import LoggerOptions, LogHandlerOptions

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from logging.handlers import RotatingFileHandler

    from .typings import Container, NestedContainer, _False, _True


class UTC3LogFormatter(logging.Formatter):
    """A formatter that writes record times in UTC+3, whatever the machine's zone."""

    # `Formatter.converter` is a writable attribute, so `ty` refuses a method in its place;
    # a `staticmethod` value keeps it the only name for the conversion.
    converter: Callable[[float | None], time.struct_time] = staticmethod(
        lambda stamp=None: datetime.fromtimestamp(
            time.time() if stamp is None else stamp, tz=TZ_UTC_PLUS_3
        ).timetuple()
    )
    """Turn a record's Unix timestamp into a UTC+3 time tuple; `None` means now, as with `time.localtime`."""


def flush_logger_handler(handler: logging.Handler | None = None) -> None:
    """Flush one handler, or every handler of every logger.

    Args:
        handler: The handler; `None` flushes all of them, the root's included.
    """
    if handler is not None:
        handler.flush()
        return

    # A copy: another thread may create a logger while this loop runs.
    for logger in list(logging.Logger.manager.loggerDict.values()):
        if isinstance(logger, logging.Logger):
            for each in logger.handlers:
                each.flush()

    for each in logging.root.handlers:
        each.flush()


@overload
def attach_logger_handlers(
    hdlrs_options: LogHandlerOptions, return_loggers: _False = False
) -> logging.Handler: ...
@overload
def attach_logger_handlers(
    hdlrs_options: LogHandlerOptions,
    return_loggers: _True,
) -> tuple[logging.Logger, logging.Handler]: ...
@overload
def attach_logger_handlers(
    hdlrs_options: Container[NestedContainer[LogHandlerOptions]],
    return_loggers: _False = False,
) -> list[logging.Handler]: ...
@overload
def attach_logger_handlers(
    hdlrs_options: Container[NestedContainer[LogHandlerOptions]],
    return_loggers: _True,
) -> list[tuple[logging.Logger, logging.Handler]]: ...
def attach_logger_handlers(
    hdlrs_options: NestedContainer[LogHandlerOptions], return_loggers: bool = False
) -> Any:
    """Build each described handler, configure it and attach it to its logger.

    Args:
        hdlrs_options: One or more handler descriptions, at any nesting.
        return_loggers: Whether to return `(logger, handler)` pairs.

    Returns:
        The handler (or pair) when `hdlrs_options` is one `LogHandlerOptions`,
        otherwise a list of them, even for a container of one or none.

    Example:
        >>> import io
        >>> from pytrove.models import LogHandlerOptions
        >>> logger, handler = attach_logger_handlers(
        ...     LogHandlerOptions(logger="pytrove.example", handler=io.StringIO(), level=logging.INFO),
        ...     return_loggers=True,
        ... )
        >>> logger.name, type(handler).__name__, handler.level
        ('pytrove.example', 'StreamHandler', 20)
        >>> logger.removeHandler(handler)
    """
    handlers: list[logging.Handler | tuple[logging.Logger, logging.Handler]] = []

    # `ty` binds `_T` to the container arm of the recursive `NestedContainer[_T]`, so
    # it cannot recover the leaf type (astral-sh/ty#1703); the parameter states it.
    for options in cast("Iterator[LogHandlerOptions]", iter_flat_cont(hdlrs_options)):
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

    return handlers[0] if isinstance(hdlrs_options, LogHandlerOptions) else handlers


@overload
def set_loggers(loggers_options: LoggerOptions) -> logging.Logger: ...
@overload
def set_loggers(
    loggers_options: Container[NestedContainer[LoggerOptions]],
) -> list[logging.Logger]: ...
def set_loggers(
    loggers_options: NestedContainer[LoggerOptions],
) -> logging.Logger | list[logging.Logger]:
    """Configure each described logger.

    Args:
        loggers_options: One or more logger descriptions, at any nesting.

    Returns:
        The logger when `loggers_options` is one `LoggerOptions`, otherwise a
        list of them, even for a container of one or none.

    Example:
        >>> from pytrove.models import LoggerOptions
        >>> set_loggers(LoggerOptions(logger="pytrove.example", level=logging.DEBUG, propagate=False)).level
        10
    """
    loggers = []

    # `ty` binds `_T` to the container arm of the recursive `NestedContainer[_T]`, so
    # it cannot recover the leaf type (astral-sh/ty#1703); the parameter states it.
    for options in cast("Iterator[LoggerOptions]", iter_flat_cont(loggers_options)):
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

    return loggers[0] if isinstance(loggers_options, LoggerOptions) else loggers


def get_rotating_log_files(
    handler: RotatingFileHandler, include_base: bool = True
) -> Iterator[Path]:
    """List a rotating handler's files, oldest backup first.

    Args:
        handler: The handler.
        include_base: Whether to end with the current file.

    Yields:
        `<file>.N` down to `<file>.1`, each as the handler's `namer` renames
        it, then the file itself.
    """
    base = Path(handler.baseFilename)

    for i in range(handler.backupCount, 0, -1):
        yield Path(handler.rotation_filename(f"{handler.baseFilename}.{i}"))

    if include_base:
        yield base


__all__ = (
    "flush_logger_handler",
    "attach_logger_handlers",
    "set_loggers",
    "get_rotating_log_files",
    "UTC3LogFormatter",
)
