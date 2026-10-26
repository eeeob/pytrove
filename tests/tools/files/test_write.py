"""`files_tools.write`: `atomic_write`, `write_file` and `truncate_file`."""

from __future__ import annotations as _annotations

import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Literal
from unittest.mock import Mock, call

import pytest

from pytrove.enums import TruncateSide
from pytrove.errors import ValidationError
from pytrove.files_tools import atomic_write, truncate_file, write, write_file

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Content with no repeating window, so a wrongly ordered or wrongly cut
#: part cannot pass a comparison by accident.
_DATA = bytes(range(256)) * 40  # 10240 bytes

#: What a lock that was taken and given back records.
_HELD = [call.acquire(), call.release()]


def _symlink(link: Path, target: Path) -> None:
    """Point `link` at `target`, or skip where this account may not make symlinks."""
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("cannot make a symlink here")


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    path = tmp_path / "app.log"
    path.write_bytes(_DATA)
    return path


# --- atomic_write / write_file ---------------------------------------------


def test_atomic_write_writes_text_or_bytes_through_a_temp_file(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"

    with atomic_write(target) as f:
        f.write("héllo")
        assert not target.exists()
        assert [p.suffix for p in tmp_path.iterdir()] == [".tmp"]

    assert target.read_text(encoding="utf-8") == "héllo"

    with atomic_write(target, binary=True, fsync=False) as f:
        f.write(b"\x00\x01")

    assert target.read_bytes() == b"\x00\x01"
    assert [p.name for p in tmp_path.iterdir()] == ["out.txt"]


def test_atomic_write_honours_the_encoding(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"

    with atomic_write(target, encoding="latin-1", fsync=False) as f:
        f.write("é")

    assert target.read_bytes() == b"\xe9"


def test_a_block_that_raises_leaves_the_old_contents_and_no_temp_file(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("old", encoding="utf-8")

    with pytest.raises(RuntimeError), atomic_write(target) as f:
        f.write("new")
        msg = "boom"
        raise RuntimeError(msg)

    assert target.read_text(encoding="utf-8") == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["out.txt"]


def test_atomic_write_does_not_let_its_cleanup_mask_the_blocks_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The removal runs in a finally. An exception from there would replace
    # whatever the caller's block was already raising, and a leftover .tmp
    # is not worth losing that.
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise PermissionError(13, "held")

    monkeypatch.setattr(os, "unlink", refuse)

    with (
        pytest.raises(ValueError, match="the block's own"),
        atomic_write(tmp_path / "out.txt") as f,
    ):
        f.write("x")
        msg = "the block's own error"
        raise ValueError(msg)


def test_atomic_write_holds_the_lock_and_releases_it_even_when_the_block_raises(
    tmp_path: Path,
) -> None:
    lock = Mock()

    with atomic_write(tmp_path / "out.txt", lock=lock, fsync=False) as f:
        assert lock.mock_calls == [call.acquire()]
        f.write("x")

    assert lock.mock_calls == _HELD

    lock.reset_mock()

    with pytest.raises(RuntimeError), atomic_write(tmp_path / "out.txt", lock=lock, fsync=False):
        msg = "boom"
        raise RuntimeError(msg)

    assert lock.mock_calls == _HELD


def test_atomic_write_into_a_missing_directory_raises_and_releases_the_lock(tmp_path: Path) -> None:
    lock = Mock()

    with (
        pytest.raises(FileNotFoundError),
        atomic_write(tmp_path / "missing" / "out.txt", lock=lock, fsync=False),
    ):
        pass

    assert lock.mock_calls == _HELD
    assert list(tmp_path.iterdir()) == []


def test_a_new_file_gets_0o644_and_an_existing_one_keeps_its_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    modes: list[int] = []
    real_chmod = os.chmod
    monkeypatch.setattr(
        os, "chmod", lambda p, m, *a, **k: (modes.append(m), real_chmod(p, m, *a, **k))
    )
    target = tmp_path / "out.txt"

    with atomic_write(target, fsync=False) as f:
        f.write("x")

    assert modes == [0o644]  # `mkstemp` makes it `0o600`; a new file is opened up to `0o644`.

    with atomic_write(target, fsync=False) as f:
        f.write("y")

    assert modes == [0o644, stat.S_IMODE(target.stat().st_mode)]


def test_writing_through_a_symlink_replaces_the_target_and_keeps_the_link(tmp_path: Path) -> None:
    target = tmp_path / "real.txt"
    target.write_text("old", encoding="utf-8")
    link = tmp_path / "link.txt"
    _symlink(link, target)

    with atomic_write(link, fsync=False) as f:
        f.write("new")

    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == "new"


def test_a_successful_write_does_not_try_to_remove_the_renamed_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    removed: list[object] = []
    monkeypatch.setattr(write, "remove_file", lambda *a, **k: removed.append(a))

    with atomic_write(tmp_path / "out.txt", fsync=False) as f:
        f.write("x")

    assert removed == []

    with pytest.raises(RuntimeError), atomic_write(tmp_path / "out.txt", fsync=False):
        msg = "boom"
        raise RuntimeError(msg)

    assert len(removed) == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_atomic_write_keeps_the_existing_mode_or_takes_the_one_given(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o640)

    with atomic_write(target, fsync=False) as f:
        f.write("new")

    assert stat.S_IMODE(target.stat().st_mode) == 0o640

    with atomic_write(target, mode=0o600, fsync=False) as f:
        f.write("newer")

    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_atomic_write_applies_an_explicit_mode_through_chmod(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Windows keeps only the write bit, so the call itself is observed rather than the result.
    modes: list[int] = []
    real_chmod = os.chmod

    def record(path: Any, mode: int, *args: Any, **kwargs: Any) -> None:
        modes.append(mode)
        real_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(os, "chmod", record)
    target = tmp_path / "out.txt"

    with atomic_write(target, mode=0o644, fsync=False) as f:
        f.write("x")

    assert modes == [0o644]

    with atomic_write(target, fsync=False) as f:
        f.write("y")

    assert modes[1] == stat.S_IMODE(target.stat().st_mode)


def test_atomic_write_fsyncs_the_file_and_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Windows refuses `os.open` on a directory, so the directory handle is stood in for by a
    # file's: what is checked is that the directory is opened, synced and closed again.
    target = tmp_path / "out.txt"
    anchor = tmp_path / "anchor"
    anchor.write_text("", encoding="utf-8")
    real_open, real_fsync = os.open, os.fsync
    dir_fds: list[int] = []
    synced: list[int] = []

    def open_dir_as_anchor(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if Path(path).is_dir():
            dir_fds.append(real_open(anchor, flags))
            return dir_fds[-1]

        return real_open(path, flags, *args, **kwargs)

    def record_fsync(fd: int) -> None:
        synced.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "open", open_dir_as_anchor)
    monkeypatch.setattr(os, "fsync", record_fsync)

    with atomic_write(target) as f:
        f.write("x")
        file_fd = f.fileno()

    assert dir_fds and synced == [file_fd, dir_fds[0]]

    with pytest.raises(OSError):  # the directory handle was closed
        os.fstat(dir_fds[0])

    synced.clear()

    with atomic_write(target, fsync=False) as f:
        f.write("y")

    assert synced == []


def test_atomic_write_survives_a_directory_that_cannot_be_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_open = os.open

    def refuse_dirs(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if Path(path).is_dir():
            raise PermissionError(13, "no directory handles here")

        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", refuse_dirs)
    target = tmp_path / "out.txt"

    with atomic_write(target) as f:
        f.write("x")

    assert target.read_text(encoding="utf-8") == "x"


def test_text_is_written_with_the_platforms_newlines(tmp_path: Path) -> None:
    # Text mode, as `open` gives: only bytes are written exactly as they are.
    write_file(tmp_path / "t.txt", "a\nb", fsync=False)
    write_file(tmp_path / "b.bin", b"a\nb", fsync=False)

    assert (tmp_path / "t.txt").read_bytes() == os.linesep.join(["a", "b"]).encode()
    assert (tmp_path / "b.bin").read_bytes() == b"a\nb"


def test_write_file_forwards_fsync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    synced: list[int] = []
    monkeypatch.setattr(os, "fsync", synced.append)

    write_file(tmp_path / "t.txt", "x", fsync=False)
    assert synced == []

    write_file(tmp_path / "t.txt", "x")
    assert synced  # the file, and the directory where the platform allows it


def test_write_file_picks_binary_from_the_content(tmp_path: Path) -> None:
    text = tmp_path / "t.txt"
    raw = tmp_path / "r.bin"

    write_file(text, "é")
    write_file(raw, "é".encode("latin-1"), fsync=False)

    assert text.read_bytes() == "é".encode()
    assert raw.read_bytes() == b"\xe9"


def test_write_file_forwards_encoding_lock_and_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    modes: list[int] = []
    real_chmod = os.chmod
    monkeypatch.setattr(
        os, "chmod", lambda p, m, *a, **k: (modes.append(m), real_chmod(p, m, *a, **k))
    )
    lock = Mock()
    target = tmp_path / "t.txt"

    write_file(target, "é", encoding="latin-1", mode=0o600, lock=lock, fsync=False)

    assert target.read_bytes() == b"\xe9"
    assert lock.mock_calls == _HELD
    assert modes == [0o600]


# --- truncate_file ---------------------------------------------------------


def test_truncate_keeps_the_head_and_drops_the_tail(sample: Path) -> None:
    assert truncate_file(sample, 1000, cut=TruncateSide.TAIL) == sample
    assert sample.read_bytes() == _DATA[:1000]


def test_truncate_keeps_the_tail_and_drops_the_head(sample: Path) -> None:
    assert truncate_file(sample, 1000, cut=TruncateSide.HEAD) == sample
    assert sample.read_bytes() == _DATA[-1000:]


def test_the_default_keeps_the_newest_bytes(sample: Path) -> None:
    # HEAD by default: the case this exists for is a log, where the end
    # is the part worth keeping. Pinned so that changing it has to be
    # deliberate.
    truncate_file(sample, 1000)

    assert sample.read_bytes() == _DATA[-1000:]


def test_the_path_that_comes_back_is_the_resolved_one(sample: Path) -> None:
    # resolve_path is what the function works with, so that is what it
    # hands back -- a caller can stat or reopen it without rebuilding it.
    got = truncate_file(sample, 100)

    assert got.is_absolute()
    assert got.stat().st_size == 100


def test_size_is_what_stays_not_what_goes(sample: Path) -> None:
    # The argument names the size the file is left at, on either end --
    # not an amount to remove from it.
    truncate_file(sample, 1500, cut=TruncateSide.HEAD)
    assert sample.stat().st_size == 1500

    sample.write_bytes(_DATA)
    truncate_file(sample, 1500, cut=TruncateSide.TAIL)
    assert sample.stat().st_size == 1500


def test_a_tail_cut_without_fsync_still_cuts(sample: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    synced: list[int] = []
    monkeypatch.setattr(os, "fsync", synced.append)

    truncate_file(sample, 1500, cut=TruncateSide.TAIL, fsync=False)

    assert sample.read_bytes() == _DATA[:1500]
    assert synced == []

    sample.write_bytes(_DATA)
    truncate_file(sample, 1500, cut=TruncateSide.TAIL)

    assert len(synced) == 1


def test_a_file_already_small_enough_is_left_alone(sample: Path) -> None:
    assert truncate_file(sample, len(_DATA)) == sample
    assert truncate_file(sample, len(_DATA) + 1) == sample
    # with spill on there is a list to answer with, and nothing in it
    assert truncate_file(sample, len(_DATA), spill=True) == []
    assert sample.read_bytes() == _DATA


@pytest.mark.parametrize("cut", ["tail", "head"])
def test_the_parts_and_the_file_put_the_original_back_together(
    sample: Path, cut: Literal["tail", "head"]
) -> None:
    # The whole promise of spilling: nothing is lost, and reassembly is a
    # concatenation in numbered order and nothing cleverer.
    parts = truncate_file(sample, 3000, cut=cut, spill=True)

    assert [p.name for p in parts] == ["app.log.1", "app.log.2", "app.log.3"]
    assert [p.stat().st_size for p in parts] == [3000, 3000, 1240]

    joined = b"".join(p.read_bytes() for p in parts)

    if cut == "tail":
        assert sample.read_bytes() + joined == _DATA
    else:
        assert joined + sample.read_bytes() == _DATA


def test_the_parts_go_beside_the_file_by_default(sample: Path, tmp_path: Path) -> None:
    parts = truncate_file(sample, 4096, spill=True)

    assert {p.parent for p in parts} == {tmp_path}


def test_the_parts_go_where_they_are_told_and_the_directory_is_made(
    sample: Path, tmp_path: Path
) -> None:
    into = tmp_path / "chunks" / "deep"

    parts = truncate_file(sample, 4096, spill=into)

    assert into.is_dir()
    assert {p.parent for p in parts} == {into}
    assert b"".join(p.read_bytes() for p in parts) == _DATA[4096:]


def test_a_second_truncation_numbers_on_from_the_first(sample: Path) -> None:
    first = truncate_file(sample, 3000, cut=TruncateSide.TAIL, spill=True)
    sample.write_bytes(_DATA)
    second = truncate_file(sample, 3000, cut=TruncateSide.TAIL, spill=True)

    assert [p.name for p in first] == ["app.log.1", "app.log.2", "app.log.3"]
    assert [p.name for p in second] == ["app.log.4", "app.log.5", "app.log.6"]
    # and the first set still holds what it held
    assert b"".join(p.read_bytes() for p in first) == _DATA[3000:]


def test_a_neighbour_that_is_not_a_part_does_not_move_the_numbering(
    sample: Path, tmp_path: Path
) -> None:
    # Only an all-digit suffix is a part. A backup sitting beside the file
    # must neither push the count up nor be counted as one and read back.
    (tmp_path / "app.log.bak").write_bytes(b"unrelated")
    (tmp_path / "app.log.2x").write_bytes(b"unrelated")

    parts = truncate_file(sample, 4096, spill=True)

    assert [p.name for p in parts] == ["app.log.1", "app.log.2"]
    assert (tmp_path / "app.log.bak").read_bytes() == b"unrelated"


@pytest.mark.parametrize("length", [1, 5, 9, 10, 99, 100, 101, 4096, 100_000])
def test_size_zero_cuts_the_spill_into_ten_parts_at_most(tmp_path: Path, length: int) -> None:
    # size=0 keeps nothing, so it names no part size and one is worked out
    # instead: a tenth of the spill, rounded up. Two properties, and both
    # have been wrong at some point --
    #
    #   never 0, which writes no part at all and then empties the file, so
    #   the bytes end up in neither place. A floor division does that for
    #   anything under ten bytes.
    #
    #   never more than ten, which is the whole reason it is a share of
    #   the file rather than a fixed length: a 4 GB file in 1 MiB parts is
    #   four thousand of them.
    path = tmp_path / "whole.bin"
    data = bytes((i * 7 + 3) % 256 for i in range(length))
    path.write_bytes(data)

    parts = truncate_file(path, 0, spill=True)

    assert 1 <= len(parts) <= 10, f"{length} bytes came back as {len(parts)} parts"
    assert all(p.stat().st_size > 0 for p in parts)
    assert b"".join(p.read_bytes() for p in parts) == data
    assert path.stat().st_size == 0


def test_a_small_size_still_spills_into_ten_parts_at_most(sample: Path) -> None:
    # Keeping 10 bytes of a 10 KiB file would otherwise mean 1023 parts of 10 bytes.
    parts = truncate_file(sample, 10, spill=True)

    assert len(parts) == 10
    assert [p.stat().st_size for p in parts] == [1023] * 10
    assert b"".join(p.read_bytes() for p in parts) + sample.read_bytes() == _DATA


def test_size_zero_spills_the_whole_file(sample: Path) -> None:
    # Nothing is kept, so there is no part size to read off the argument
    # and the copy buffer is the only number left.
    parts = truncate_file(sample, 0, spill=True)

    assert sample.read_bytes() == b""
    assert b"".join(p.read_bytes() for p in parts) == _DATA


def test_spilling_off_loses_the_bytes_and_answers_with_the_file(
    sample: Path, tmp_path: Path
) -> None:
    # Nothing was split, so there is one file in play and its own path is
    # the answer -- an empty list said nothing about what happened.
    assert truncate_file(sample, 3000) == sample
    assert sorted(p.name for p in tmp_path.iterdir()) == ["app.log"]


def test_spilling_answers_with_the_parts_and_not_with_the_file(sample: Path) -> None:
    got = truncate_file(sample, 3000, spill=True)

    assert isinstance(got, list)
    assert sample not in got
    assert [p.name for p in got] == ["app.log.1", "app.log.2", "app.log.3"]


def test_the_raw_string_picks_the_same_end_as_the_enum(tmp_path: Path) -> None:
    for spelling in ("head", TruncateSide.HEAD):
        path = tmp_path / f"x{spelling!s}.bin"
        path.write_bytes(_DATA)
        truncate_file(path, 500, cut=spelling)
        assert path.read_bytes() == _DATA[-500:]


def test_an_unknown_cut_is_refused_before_anything_changes(sample: Path) -> None:
    with pytest.raises(ValueError, match="middle"):
        truncate_file(sample, 10, cut="middle")  # type: ignore[arg-type]  # The wrong value is the point.

    assert sample.read_bytes() == _DATA


def test_size_zero_without_spill_empties_the_file(sample: Path, tmp_path: Path) -> None:
    assert truncate_file(sample, 0) == sample
    assert sample.read_bytes() == b""
    assert [p.name for p in tmp_path.iterdir()] == ["app.log"]


def test_spill_takes_a_str_directory(sample: Path, tmp_path: Path) -> None:
    parts = truncate_file(sample, 4096, spill=str(tmp_path / "into"))

    assert {p.parent for p in parts} == {tmp_path / "into"}
    assert b"".join(p.read_bytes() for p in parts) == _DATA[:-4096]


def test_an_empty_spill_path_is_the_current_directory(
    sample: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `""` is falsy but a directory all the same; reading it as `False` lost the bytes.
    into = tmp_path / "cwd"
    into.mkdir()
    monkeypatch.chdir(into)

    parts = truncate_file(sample, 4096, spill="")

    assert isinstance(parts, list)
    assert {p.parent for p in parts} == {into.resolve()}
    assert b"".join(p.read_bytes() for p in parts) + sample.read_bytes() == _DATA

    assert truncate_file(sample, len(_DATA), spill="") == []


def test_a_spill_path_that_is_a_file_is_refused_and_nothing_is_cut(
    sample: Path, tmp_path: Path
) -> None:
    taken = tmp_path / "taken"
    taken.write_bytes(b"keep")

    with pytest.raises(FileExistsError):
        truncate_file(sample, 10, spill=taken)

    assert sample.read_bytes() == _DATA
    assert taken.read_bytes() == b"keep"


@pytest.mark.parametrize("cut", [TruncateSide.HEAD, TruncateSide.TAIL])
def test_a_spill_that_fails_midway_leaves_the_file_whole(
    sample: Path, monkeypatch: pytest.MonkeyPatch, cut: TruncateSide
) -> None:
    # The parts are written first, so a failure there can only leave extra copies behind.
    real = write.atomic_write
    opened: list[object] = []

    @contextmanager
    def fail_on_the_second_part(*args: Any, **kwargs: Any) -> Iterator[IO[Any]]:
        opened.append(args[0])

        if len(opened) == 2:
            msg = "disk full"
            raise OSError(28, msg)

        with real(*args, **kwargs) as f:
            yield f

    monkeypatch.setattr(write, "atomic_write", fail_on_the_second_part)

    with pytest.raises(OSError, match="disk full"):
        truncate_file(sample, 3000, cut=cut, spill=True)

    assert sample.read_bytes() == _DATA
    assert len(opened) == 2


def test_a_head_cut_without_fsync_never_syncs(
    sample: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced: list[int] = []
    monkeypatch.setattr(os, "fsync", synced.append)

    truncate_file(sample, 1500, cut=TruncateSide.HEAD, fsync=False)

    assert sample.read_bytes() == _DATA[-1500:]
    assert synced == []

    sample.write_bytes(_DATA)
    truncate_file(sample, 1500, cut=TruncateSide.HEAD)

    assert synced


@pytest.mark.parametrize("bad", [-1, 3.5, True, "1000", None])
def test_a_size_that_is_not_a_count_of_bytes_is_refused(sample: Path, bad: Any) -> None:
    with pytest.raises(ValidationError, match="whole number of bytes"):
        truncate_file(sample, bad)

    assert sample.read_bytes() == _DATA


def test_a_directory_is_not_a_file_to_truncate(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="is not a file"):
        truncate_file(tmp_path, 10)


def test_a_missing_file_is_reported_as_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        truncate_file(tmp_path / "nope.log", 10)


def test_nothing_temporary_is_left_behind(sample: Path, tmp_path: Path) -> None:
    truncate_file(sample, 3000, cut=TruncateSide.HEAD, spill=True)

    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_a_head_cut_keeps_the_file_mode(sample: Path) -> None:
    sample.chmod(0o640)

    truncate_file(sample, 3000, cut=TruncateSide.HEAD)

    assert sample.stat().st_mode & 0o777 == 0o640


def test_atomic_write_raises_a_failed_acquire_as_is_and_leaves_nothing(tmp_path: Path) -> None:
    lock = Mock(**{"acquire.side_effect": TimeoutError("lock timed out")})

    with (
        pytest.raises(TimeoutError, match="lock timed out"),
        atomic_write(tmp_path / "out.txt", lock=lock, fsync=False),
    ):
        pass

    assert lock.mock_calls == [call.acquire()]
    assert list(tmp_path.iterdir()) == []
