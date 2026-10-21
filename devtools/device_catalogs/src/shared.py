"""Values and helpers every other module needs, and nothing else.

Imports nothing from the package, so it can be read first and loaded alone.
"""

from __future__ import annotations as _annotations

import re
from datetime import date
from pathlib import Path
from typing import NamedTuple

#: This tool's own directory, and the repository root above it. Derived from
#: TOOL_DIR rather than counting `.parent` from here, so moving a module
#: between `src/` and a subpackage of it cannot silently shift every path.
TOOL_DIR = Path(__file__).resolve().parent.parent
ROOT = TOOL_DIR.parent.parent

OUT_DIR = ROOT / "pytrove" / "data" / "devices"

#: Every tool keeps its downloads in its own `.cache`, so one tool's cache is
#: never cleared by another's run and `devtools/*/.cache/` ignores all of them.
CACHE_DIR = TOOL_DIR / ".cache"

USER_AGENT = {"User-Agent": "pytrove-device-data"}
TODAY = date.today().isoformat()

#: Bumped only when the JSON layout changes; `_devices._SCHEMA` must match.
SCHEMA = 1

# ============================= shared helpers =============================

def version_key(version: str) -> tuple[int, ...]:
    """Sort key for a dotted version, so 18.10 follows 18.9."""
    return tuple(int(part) for part in re.findall(r"\d+", version))


def major_of(version: str) -> int:
    """Return the major component of a dotted version string."""
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
