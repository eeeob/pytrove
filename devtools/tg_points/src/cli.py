"""The argument parsing that drives the build."""

from __future__ import annotations as _annotations

import argparse
from datetime import date
from typing import TYPE_CHECKING

from .blocks import Blocks
from .cache import Cache
from .points import Points

if TYPE_CHECKING:
    from pathlib import Path


def build(cache: Cache, today: date, data_dir: Path = Points.DATA_DIR) -> None:
    """Build the points and the blocks, then write both; nothing is written if either stops."""
    points = Points(cache, data_dir)
    blocks = Blocks(points)
    rows = points.collect(today)
    spans = blocks.collect(today)
    points.write(rows)
    blocks.write(spans)


def main(argv: list[str] | None = None) -> int:
    """Parse the command line, build the data, return the exit code."""
    parser = argparse.ArgumentParser(
        description="Regenerate pytrove/data/tg_points.json and tg_blocks.json from public sources."
    )
    parser.add_argument("--offline", action="store_true", help="rebuild from the cache only")
    args = parser.parse_args(argv)

    # A build says it cannot run by raising SystemExit before it writes
    # anything, so the data on disk is either the old files or two new ones.
    try:
        build(Cache(offline=args.offline), date.today())
    except SystemExit as exc:
        why = str(exc.code).replace("\n", "\n  ")
        print(f"not built: {why}\n  the data was left as it was")
        return 1
    return 0
