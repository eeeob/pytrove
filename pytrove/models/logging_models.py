from __future__ import annotations

from typing import Callable
from pathlib import Path

from dataclasses import dataclass
from logging import (
    getLogger, Formatter, 
    LogRecord, Logger, 
    Handler, FileHandler, StreamHandler, 
)

from ..errors import ValidationError


import io

@dataclass(slots=True, kw_only=True)
class _LoggerModel:
    logger: Logger | str | None = None

    level: int | None = None
    filter: Callable[[LogRecord], bool] | None = None

    def resolve_logger(self) -> Logger:
        logger = self.logger

        if logger is None or isinstance(logger, str):
            self.logger = getLogger(logger)
        elif not isinstance(logger, Logger):
            raise ValidationError("Invalid Logger %s" % str(logger))
        
        return self.logger
    
@dataclass(slots=True, kw_only=True)
class LogHandlerOptions(_LoggerModel):
    handler: Handler | io.IOBase | Path | str
    formatter: Formatter | None = None

    def resolve_handler(self) -> FileHandler | StreamHandler:
        hdlr = self.handler

        if isinstance(hdlr, (Path, str)):
            self.handler = FileHandler(hdlr, encoding="utf-8")
        elif isinstance(hdlr, io.IOBase):
            self.handler = StreamHandler(hdlr)
        elif not isinstance(hdlr, Handler):
            raise ValidationError("Invalid Logger Handler %s" % str(hdlr))
        
        return self.handler

@dataclass(slots=True, kw_only=True)
class LoggerOptions(_LoggerModel):
    propagate: bool | None = None
    reset_level: bool | None = None




__all__ = (
    "LogHandlerOptions", 
    "LoggerOptions", 
)