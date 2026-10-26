"""Where the data bundled inside the package lives."""

from __future__ import annotations as _annotations

from pathlib import Path
from typing import Final

DATA_DIR: Final[Path] = Path(__file__).parent.parent / "data"
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
