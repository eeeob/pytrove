"""`files_tools.read`: `read_file`."""

from __future__ import annotations as _annotations

import threading
from typing import TYPE_CHECKING
from unittest.mock import Mock, call

import pytest

from pytrove.files_tools import read_file

if TYPE_CHECKING:
    from pathlib import Path


def test_read_file_reads_text_or_bytes(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_bytes("é".encode())

    assert read_file(target) == "é"
    assert read_file(str(target), binary=True) == "é".encode()


@pytest.mark.parametrize("binary", [False, True])
def test_read_file_takes_binary_as_a_plain_bool(tmp_path: Path, binary: bool) -> None:
    # A `bool` variable, not a literal: the last overload types the result `str | bytes`.
    target = tmp_path / "f.txt"
    target.write_bytes(b"x")

    assert read_file(target, binary=binary) == (b"x" if binary else "x")


def test_read_file_honours_the_encoding(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_bytes("é".encode("latin-1"))

    assert read_file(target, encoding="latin-1") == "é"


def test_read_file_forwards_open_keywords(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_bytes(b"a\r\nb")

    assert read_file(target, newline="") == "a\r\nb"
    assert read_file(target) == "a\nb"


def test_read_file_holds_the_lock_around_the_read_and_releases_it_either_way(
    tmp_path: Path,
) -> None:
    target = tmp_path / "f.txt"
    target.write_text("x", encoding="utf-8")
    lock = threading.Lock()

    assert read_file(target, lock=lock) == "x"
    assert not lock.locked()

    recording = Mock()

    with pytest.raises(FileNotFoundError):
        read_file(tmp_path / "missing", lock=recording)

    assert recording.mock_calls == [call.acquire(), call.release()]


def test_read_file_raises_for_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_file(tmp_path / "missing")

    with pytest.raises(FileNotFoundError):
        read_file(tmp_path / "missing", binary=True)


def test_read_file_raises_a_failed_acquire_as_is_and_never_releases(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("x", encoding="utf-8")
    lock = Mock(**{"acquire.side_effect": TimeoutError("lock timed out")})

    with pytest.raises(TimeoutError, match="lock timed out"):
        read_file(target, lock=lock)

    assert lock.mock_calls == [call.acquire()]
