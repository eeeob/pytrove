from __future__ import annotations

from typing import Iterator, overload
from pathlib import Path
from logging.handlers import RotatingFileHandler

from .typings import _False, _True, Container, NestedContainer
from .models import LoggerOptions, LogHandlerOptions
from .iter_tools import iter_flat_cont

import logging




def flush_logger_handler(handler: logging.Handler | None = None) -> None:
    if handler is None:
        for logger in logging.Logger.manager.loggerDict.values():
            if isinstance(logger, logging.Logger):
                for handler in logger.handlers:
                    handler.flush()

        for handler in logging.root.handlers:
            handler.flush()

    else:
        handler.flush()


@overload
def attach_logger_handlers(
    hdlrs_options: LogHandlerOptions, 
    return_loggers: _False = ...
    ) -> logging.Handler: ...
@overload
def attach_logger_handlers(
    hdlrs_options: LogHandlerOptions, 
    return_loggers: _True
    ) -> tuple[logging.Logger, logging.Handler]: ...
@overload
def attach_logger_handlers(
    hdlrs_options: 'Container[NestedContainer[LogHandlerOptions]]', 
    return_loggers: _False = ...
    ) -> list[logging.Handler]: ...
@overload
def attach_logger_handlers(
    hdlrs_options: 'Container[NestedContainer[LogHandlerOptions]]', 
    return_loggers: _True
    ) -> list[tuple[logging.Logger, logging.Handler]]: ...

def attach_logger_handlers(
    hdlrs_options: NestedContainer[LogHandlerOptions], 
    return_loggers: bool = False
    ):
    
    handlers = []

    for options in iter_flat_cont(hdlrs_options):
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
    loggers = []

    for options in iter_flat_cont(loggers_options):
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
    base = Path(handler.baseFilename)
    backup_count = handler.backupCount

    for i in range(backup_count, 0, -1):
        yield base.with_name(f"{base.name}.{i}")

    if with_base:
        yield base


__all__ = (
    "flush_logger_handler", 
    "attach_logger_handlers", 
    "set_loggers", 
    "get_rotating_log_files", 
)




