"""`pytrove.constants.paths`: the bundled-data paths point at files that ship in the package."""

from __future__ import annotations as _annotations

from pathlib import Path

import pytrove
from pytrove.constants import paths
from pytrove.constants.paths import (
    DATA_DIR,
    DEVICE_CATALOGS_DIR,
    TG_ACCOUNT_BLOCKS_FILE,
    TG_ACCOUNT_POINTS_FILE,
)
from pytrove.enums import PlatformDevice


def test_data_dir_is_the_package_data_folder() -> None:
    assert DATA_DIR == Path(pytrove.__file__).parent / "data"
    assert DATA_DIR.is_dir()


def test_device_catalogs_dir_holds_one_catalog_per_platform() -> None:
    assert DEVICE_CATALOGS_DIR.parent == DATA_DIR
    assert {p.stem for p in DEVICE_CATALOGS_DIR.glob("*.json")} == {
        member.value for member in PlatformDevice
    }


def test_tg_account_points_file_ships_in_the_data_folder() -> None:
    assert TG_ACCOUNT_POINTS_FILE.parent == DATA_DIR
    assert TG_ACCOUNT_POINTS_FILE.is_file()


def test_tg_account_blocks_file_ships_in_the_data_folder() -> None:
    assert TG_ACCOUNT_BLOCKS_FILE.parent == DATA_DIR
    assert TG_ACCOUNT_BLOCKS_FILE.is_file()


def test_all_lists_exactly_the_paths() -> None:
    assert paths.__all__ == (
        "DATA_DIR",
        "DEVICE_CATALOGS_DIR",
        "TG_ACCOUNT_BLOCKS_FILE",
        "TG_ACCOUNT_POINTS_FILE",
    )
