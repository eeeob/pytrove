from __future__ import annotations as _annotations

import io
import logging
from pathlib import Path

import pytest

from pytrove.errors import ValidationError
from pytrove.models import LoggerOptions, LogHandlerOptions


def test_logger_options_resolve_a_name_none_or_logger() -> None:
    logger = logging.getLogger("pytrove.test.models")

    assert LoggerOptions(logger="pytrove.test.models").resolve_logger() is logger
    assert LoggerOptions().resolve_logger() is logging.getLogger()
    assert LoggerOptions(logger=logger).resolve_logger() is logger

    with pytest.raises(ValidationError, match="Invalid Logger"):
        LoggerOptions(logger=5).resolve_logger()


def test_handler_options_resolve_a_path_stream_or_handler(tmp_path: Path) -> None:
    stream = io.StringIO()
    file_handler = LogHandlerOptions(handler=tmp_path / "a.log").resolve_handler()

    try:
        assert isinstance(file_handler, logging.FileHandler)
        assert file_handler.encoding == "utf-8"
    finally:
        file_handler.close()

    assert LogHandlerOptions(handler=stream).resolve_handler().stream is stream
    handler = logging.NullHandler()
    assert LogHandlerOptions(handler=handler).resolve_handler() is handler

    with pytest.raises(ValidationError, match="Invalid Logger Handler"):
        LogHandlerOptions(handler=5).resolve_handler()


def test_logger_options_defaults() -> None:
    options = LoggerOptions()
    assert options.propagate is None and options.reset_level is None and options.level is None
