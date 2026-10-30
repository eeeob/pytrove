from __future__ import annotations as _annotations

import io
import logging
import time
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

import pytest

from pytrove.logging_tools import (
    UTC3LogFormatter,
    attach_logger_handlers,
    flush_logger_handler,
    get_rotating_log_files,
    set_loggers,
)
from pytrove.models import LoggerOptions, LogHandlerOptions

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


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
        LogHandlerOptions(
            logger=logger_name,
            handler=stream,
            level=logging.WARNING,
            formatter=formatter,
            filter=lambda r: True,
        ),
    )
    assert isinstance(handler, logging.StreamHandler)
    assert handler.level == logging.WARNING
    assert handler in logging.getLogger(logger_name).handlers
    logging.getLogger(logger_name).warning("hi")
    assert stream.getvalue() == "hi!\n"


def test_attach_several_returns_pairs(logger_name: str, tmp_path: Path) -> None:
    pairs = attach_logger_handlers(
        [
            LogHandlerOptions(logger=logger_name, handler=io.StringIO()),
            [LogHandlerOptions(logger=logger_name, handler=tmp_path / "f.log")],
        ],
        return_loggers=True,
    )
    assert [type(h) for _, h in pairs] == [logging.StreamHandler, logging.FileHandler]
    assert all(logger.name == logger_name for logger, _ in pairs)


def test_set_loggers(logger_name: str) -> None:
    logger = set_loggers(
        LoggerOptions(
            logger=logger_name, level=logging.ERROR, propagate=False, filter=lambda r: True
        )
    )
    assert logger.level == logging.ERROR
    assert logger.propagate is False
    assert set_loggers(LoggerOptions(logger=logger_name, reset_level=True)).level == logging.NOTSET
    assert (
        len(set_loggers([LoggerOptions(logger=logger_name), LoggerOptions(logger=logger_name)]))
        == 2
    )


def test_rotating_files_oldest_first(tmp_path: Path) -> None:
    handler = RotatingFileHandler(tmp_path / "app.log", backupCount=2)

    try:
        names = [p.name for p in get_rotating_log_files(handler)]
        assert names == ["app.log.2", "app.log.1", "app.log"]
        assert [p.name for p in get_rotating_log_files(handler, include_base=False)] == [
            "app.log.2",
            "app.log.1",
        ]
    finally:
        handler.close()


def test_utc3_formatter_writes_utc_plus_3() -> None:
    record = logging.LogRecord("x", logging.INFO, "f", 1, "m", None, None)
    record.created = 0.0
    assert UTC3LogFormatter("%(asctime)s").format(record).startswith("1970-01-01 03:00:00")


def test_utc3_converter_is_the_only_name_for_the_conversion() -> None:
    assert UTC3LogFormatter.converter(0.0)[:8] == time.gmtime(3 * 3600)[:8]
    assert UTC3LogFormatter().converter(0.0)[:8] == time.gmtime(3 * 3600)[:8]
    assert not hasattr(UTC3LogFormatter, "_to_utc3")


@pytest.mark.parametrize("args", [(None,), ()])
def test_utc3_converter_reads_a_missing_stamp_as_now(
    monkeypatch: pytest.MonkeyPatch, args: tuple[None, ...]
) -> None:
    monkeypatch.setattr(time, "time", lambda: 86_400.0)
    assert UTC3LogFormatter().converter(*args)[:8] == time.gmtime(86_400 + 3 * 3600)[:8]


def test_flush_reaches_the_root_handlers_and_skips_placeholders(logger_name: str) -> None:
    handler = _Counting()
    logging.root.addHandler(handler)
    # A child logger leaves a `PlaceHolder` for its parent in `loggerDict`.
    logging.getLogger(f"{logger_name}.parent.child")

    try:
        assert isinstance(
            logging.Logger.manager.loggerDict[f"{logger_name}.parent"], logging.PlaceHolder
        )
        flush_logger_handler()
    finally:
        logging.root.removeHandler(handler)

    assert handler.flushes == 1


def test_flush_survives_a_logger_created_while_it_runs(
    logger_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = []

    class _Spawning(_Counting):
        """A handler whose flush creates a logger, as another thread could."""

        def flush(self) -> None:
            """Create a new logger mid-iteration."""
            super().flush()
            created.append(logging.getLogger(f"{logger_name}.spawned{len(created)}"))

    handler = _Spawning()
    logging.getLogger(logger_name).addHandler(handler)

    flush_logger_handler()

    assert handler.flushes == 1
    assert created


def test_attach_adds_the_filter_to_the_handler(logger_name: str) -> None:
    def keep(record: logging.LogRecord) -> bool:
        return True

    handler = attach_logger_handlers(
        LogHandlerOptions(logger=logger_name, handler=io.StringIO(), filter=keep)
    )
    assert keep in handler.filters


def test_attach_one_with_loggers_returns_the_pair(logger_name: str) -> None:
    logger, handler = attach_logger_handlers(
        LogHandlerOptions(logger=logger_name, handler=io.StringIO()), return_loggers=True
    )
    assert logger is logging.getLogger(logger_name)
    assert handler in logger.handlers


@pytest.mark.parametrize("return_loggers", [False, True])
def test_attach_a_container_of_one_returns_a_list(logger_name: str, return_loggers: bool) -> None:
    result = attach_logger_handlers(
        [LogHandlerOptions(logger=logger_name, handler=io.StringIO())],
        return_loggers=return_loggers,
    )
    assert isinstance(result, list)
    assert len(result) == 1


def test_attach_an_empty_container_returns_an_empty_list() -> None:
    assert attach_logger_handlers([]) == []


def test_set_loggers_adds_the_filter_and_resets_before_setting_the_level(logger_name: str) -> None:
    def keep(record: logging.LogRecord) -> bool:
        return True

    logger = set_loggers(
        LoggerOptions(logger=logger_name, level=logging.WARNING, reset_level=True, filter=keep)
    )
    assert keep in logger.filters
    assert logger.level == logging.WARNING


def test_set_loggers_returns_a_list_for_any_container(logger_name: str) -> None:
    assert set_loggers([LoggerOptions(logger=logger_name)]) == [logging.getLogger(logger_name)]
    assert set_loggers([]) == []


def test_rotating_files_without_backups_is_the_base_alone(tmp_path: Path) -> None:
    handler = RotatingFileHandler(tmp_path / "app.log", backupCount=0)

    try:
        assert [p.name for p in get_rotating_log_files(handler)] == ["app.log"]
        assert list(get_rotating_log_files(handler, include_base=False)) == []
    finally:
        handler.close()


def test_rotating_files_follow_the_handler_namer(tmp_path: Path) -> None:
    handler = RotatingFileHandler(tmp_path / "app.log", backupCount=2)
    handler.namer = lambda name: name + ".gz"

    try:
        assert [p.name for p in get_rotating_log_files(handler)] == [
            "app.log.2.gz",
            "app.log.1.gz",
            "app.log",
        ]
    finally:
        handler.close()
