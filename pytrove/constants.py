"""Constants shared across the library: for now, where its bundled data lives.

A constant one module alone reads stays beside its use; this module holds the
ones more than one section reads, or that describe the package itself.
"""

from __future__ import annotations as _annotations

from pathlib import Path
from typing import Final

DATA_DIR: Final[Path] = Path(__file__).parent / "data"
"""The root of the data shipped inside the package; every bundled file lives below it."""

DEVICE_CATALOGS_DIR: Final[Path] = DATA_DIR / "devices"
"""One generated JSON device catalog per `PlatformDevice` member, read on the first draw."""

TG_ACCOUNT_POINTS_FILE: Final[Path] = DATA_DIR / "tg_points.json"
"""Known Telegram `[user id, "YYYY-MM-DD"]` creation points in date order, read on first use."""

__all__ = (
    "DATA_DIR",
    "DEVICE_CATALOGS_DIR",
    "TG_ACCOUNT_POINTS_FILE",
)
