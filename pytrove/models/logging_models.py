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
    """A handler to attach to a logger.

    Attributes:
        handler: A `Handler`, a stream to log to, or a file path to log to.
        formatter: The formatter to set on the handler, if any.
    """

    handler: Handler | io.IOBase | Path | str
    formatter: Formatter | None = None

    def resolve_handler(self) -> FileHandler | StreamHandler:
        """Replace a path or stream in `handler` with the `Handler` it implies, and return it.

        Returns:
            The resolved handler: a UTF-8 `FileHandler` for a path, a
            `StreamHandler` for a stream.

        Raises:
            ValidationError: If `handler` is none of the accepted kinds.
        """
        hdlr = self.handler

        if isinstance(hdlr, (Path, str)):
            self.handler = FileHandler(hdlr, encoding="utf-8")
        elif isinstance(hdlr, io.IOBase):
            self.handler = StreamHandler(hdlr)
        elif not isinstance(hdlr, Handler):
            msg = f"Invalid Logger Handler {hdlr}"
            raise ValidationError(msg)

        return self.handler


@dataclass(slots=True, kw_only=True)
class LoggerOptions(_LoggerModel):
    """Settings to apply to a logger.

    Attributes:
        propagate: The value to set on `Logger.propagate`, if any.
        reset_level: Reset the level to `NOTSET`.
    """

    propagate: bool | None = None
    reset_level: bool | None = None


__all__ = (
    "LogHandlerOptions",
    "LoggerOptions",
)
