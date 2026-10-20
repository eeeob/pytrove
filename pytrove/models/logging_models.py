"""Options for configuring loggers and their handlers with `logging_tools`."""

from __future__ import annotations as _annotations

import io
from dataclasses import dataclass
from logging import FileHandler, Formatter, Handler, StreamHandler
from pathlib import Path

from ..errors import ValidationError
from ._internal import _LoggerModel


@dataclass(slots=True, kw_only=True)
class LogHandlerOptions(_LoggerModel):
    """A handler to attach to a logger."""

    handler: Handler | io.IOBase | Path | str
    """A `Handler`, a stream to log to, or a file path to log to; `resolve_handler()` replaces it with the `Handler`."""

    formatter: Formatter | None = None
    """The formatter to set on the handler; `None` leaves the handler's own."""

    def resolve_handler(self) -> Handler:
        """Replace a path or stream in `handler` with the `Handler` it implies, and return it.

        Returns:
            The resolved handler: a UTF-8 `FileHandler` for a path, a
            `StreamHandler` for a stream, or `handler` itself.

        Raises:
            ValidationError: If `handler` is none of the accepted kinds.
        """
        hdlr = self.handler

        if isinstance(hdlr, (Path, str)):
            hdlr = FileHandler(hdlr, encoding="utf-8")
        elif isinstance(hdlr, io.IOBase):
            hdlr = StreamHandler(hdlr)
        elif not isinstance(hdlr, Handler):
            msg = f"Invalid Logger Handler {hdlr}"
            raise ValidationError(msg)

        self.handler = hdlr
        return hdlr


@dataclass(slots=True, kw_only=True)
class LoggerOptions(_LoggerModel):
    """Settings to apply to a logger."""

    propagate: bool | None = None
    """The value to set on `Logger.propagate`; `None` leaves it alone."""

    reset_level: bool | None = None
    """Whether to reset the level to `NOTSET`; falsy leaves it alone."""


__all__ = (
    "LogHandlerOptions",
    "LoggerOptions",
)
