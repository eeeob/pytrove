"""`files_tools.read`: `read_file`."""

from __future__ import annotations as _annotations

import threading
from typing import TYPE_CHECKING

import pytest

from pytrove.files_tools import read_file

if TYPE_CHECKING:
    from pathlib import Path


class _Lock:
    """A lock that records every acquire and release."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def acquire(self) -> bool:
        self.calls.append("acquire")
        return True

    def release(self) -> None:
        self.calls.append("release")


def test_read_file_reads_text_or_bytes(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_bytes("é".encode())

    assert read_file(target) == "é"
    assert read_file(str(target), binary=True) == "é".encode()


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

    recording = _Lock()

    with pytest.raises(FileNotFoundError):
        read_file(tmp_path / "missing", lock=recording)

    assert recording.calls == ["acquire", "release"]


def test_read_file_raises_for_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_file(tmp_path / "missing")

    with pytest.raises(FileNotFoundError):
        read_file(tmp_path / "missing", binary=True)
