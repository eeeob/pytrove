"""Values and helpers every other module needs, and nothing else.

Imports nothing from the package, so it can be read first and loaded alone.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import NamedTuple

#: The repository root, which is also where the output lives.
ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = ROOT / "pytrove" / "data" / "devices"
CACHE_DIR = ROOT / "tools" / ".device-cache"

USER_AGENT = {"User-Agent": "pytrove-device-data"}
TODAY = date.today().isoformat()

#: Bumped only when the JSON layout changes; `_devices._SCHEMA` must match.
SCHEMA = 1

# ============================= shared helpers =============================

def version_key(version: str) -> tuple[int, ...]:
    """Sort key for a dotted version, so 18.10 follows 18.9."""

    return tuple(int(part) for part in re.findall(r"\d+", version))


def major_of(version: str) -> int:
    return int(version.split(".")[0])


def normalize(value: str | None) -> str:
    """Lowercase, strip punctuation, collapse spaces.

    Used to match a device name across sources that spell it differently
    ("Galaxy S23+ 5G" vs "galaxy s23+ 5g").
    """

    value = re.sub(r"[^a-z0-9+]+", " ", (value or "").lower().strip())
    return re.sub(r"\s+", " ", value).strip()


class Share(NamedTuple):
    """One option and its relative popularity, for hand-estimated mixes."""

    name: str
    weight: int
