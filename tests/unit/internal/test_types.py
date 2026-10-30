from __future__ import annotations as _annotations

import os
import tarfile
import typing
import zipfile
from collections.abc import Callable
from typing import get_args

from pytrove._internal import _types


def test_every_private_alias_is_listed_in_all() -> None:
    assert set(_types.__all__) == {"_ExcFilter", "_RawEntry", "_Rule"}


def test_exc_filter_accepts_a_class_a_tuple_or_none() -> None:
    assert set(get_args(_types._ExcFilter)) == {
        type[BaseException],
        tuple[type[BaseException], ...],
        type(None),
    }


def test_raw_entry_covers_every_entry_an_archive_filter_sees() -> None:
    assert set(get_args(_types._RawEntry)) == {
        os.DirEntry,
        zipfile.ZipInfo,
        tarfile.TarInfo,
        type(None),
    }


def test_rule_is_a_pattern_a_path_or_a_predicate_over_path_and_entry() -> None:
    glob, path, predicate = get_args(_types._Rule)
    assert glob is str
    assert path == os.PathLike[str]
    assert typing.get_origin(predicate) is Callable
    assert get_args(predicate)[0] == [str, _types._RawEntry]
