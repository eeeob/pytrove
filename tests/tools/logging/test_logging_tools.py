from __future__ import annotations as _annotations

import io
import logging
import time
from collections.abc import Iterator
from datetime import timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from pytrove.logging_tools import (
    UTC3LogFormatter,
    attach_logger_handlers,
    flush_logger_handler,
    get_rotating_log_files,
    set_loggers,
    _UTC3,
)
from pytrove.models import LoggerOptions, LogHandlerOptions


class _Counting(logging.Handler):
    """A handler that counts its flushes."""

    def __init__(self) -> None:
        """Start at zero."""
        super().__init__()
        self.flushes = 0

    def emit(self, record: logging.LogRecord) -> None:
        """Ignore records."""

    def flush(self) -> None:
        """Count a flush."""
        self.flushes += 1


@pytest.fixture
def logger_name(request: pytest.FixtureRequest) -> Iterator[str]:
    """A logger unique to the test, cleaned of handlers afterwards."""
    name = f"pytrove-test.{request.node.name}"
    yield name
    logger = logging.getLogger(name)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def test_flush_one_or_every_handler(logger_name: str) -> None:
    handler = _Counting()
    flush_logger_handler(handler)
    assert handler.flushes == 1

    logging.getLogger(logger_name).addHandler(handler)
    flush_logger_handler()
    assert handler.flushes == 2


def test_attach_one_handler_configured(logger_name: str) -> None:
    stream = io.StringIO()
    formatter = logging.Formatter("%(message)s!")
    handler = attach_logger_handlers(
        LogHandlerOptions(logger=logger_name, handler=stream, level=logging.WARNING, formatter=formatter, filter=lambda r: True),
    )
    assert isinstance(handler, logging.StreamHandler)
    assert handler.level == logging.WARNING
    assert handler in logging.getLogger(logger_name).handlers
    logging.getLogger(logger_name).warning("hi")
    assert stream.getvalue() == "hi!\n"


def test_attach_several_returns_pairs(logger_name: str, tmp_path: Path) -> None:
    pairs = attach_logger_handlers(
        [LogHandlerOptions(logger=logger_name, handler=io.StringIO()), [LogHandlerOptions(logger=logger_name, handler=tmp_path / "f.log")]],
        return_loggers=True,
    )
    assert [type(h) for _, h in pairs] == [logging.StreamHandler, logging.FileHandler]
    assert all(logger.name == logger_name for logger, _ in pairs)


def test_set_loggers(logger_name: str) -> None:
    logger = set_loggers(LoggerOptions(logger=logger_name, level=logging.ERROR, propagate=False, filter=lambda r: True))
    assert logger.level == logging.ERROR
    assert logger.propagate is False
    assert set_loggers(LoggerOptions(logger=logger_name, reset_level=True)).level == logging.NOTSET
    assert len(set_loggers([LoggerOptions(logger=logger_name), LoggerOptions(logger=logger_name)])) == 2


def test_rotating_files_oldest_first(tmp_path: Path) -> None:
    handler = RotatingFileHandler(tmp_path / "app.log", backupCount=2)

    try:
        names = [p.name for p in get_rotating_log_files(handler)]
        assert names == ["app.log.2", "app.log.1", "app.log"]
        assert [p.name for p in get_rotating_log_files(handler, with_base=False)] == ["app.log.2", "app.log.1"]
    finally:
        handler.close()


def test_utc3_formatter_writes_utc_plus_3() -> None:
    record = logging.LogRecord("x", logging.INFO, "f", 1, "m", None, None)
    record.created = 0.0
    assert UTC3LogFormatter("%(asctime)s").format(record).startswith("1970-01-01 03:00:00")


def test_utc3_zone_is_a_fixed_plus_three_hours() -> None:
    assert _UTC3.utcoffset(None) == timedelta(hours=3)


def test_utc3_converter_is_the_static_to_utc3() -> None:
    assert UTC3LogFormatter.converter is UTC3LogFormatter._to_utc3
    assert UTC3LogFormatter()._to_utc3(0.0)[:8] == time.gmtime(3 * 3600)[:8]


@pytest.mark.parametrize("args", [(None,), ()])
def test_utc3_converter_reads_a_missing_stamp_as_now(monkeypatch: pytest.MonkeyPatch, args: tuple[None, ...]) -> None:
    monkeypatch.setattr(time, "time", lambda: 86_400.0)
    assert UTC3LogFormatter().converter(*args)[:8] == time.gmtime(86_400 + 3 * 3600)[:8]
