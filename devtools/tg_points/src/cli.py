"""The argument parsing that drives the build."""

from __future__ import annotations as _annotations

import argparse
from datetime import date

from .cache import Cache
from .points import Points


def main(argv: list[str] | None = None) -> int:
    """Parse the command line, build the points, return the exit code."""
    parser = argparse.ArgumentParser(
        description="Regenerate pytrove/data/tg_points.json from public sources."
    )
    parser.add_argument("--offline", action="store_true", help="rebuild from the cache only")
    args = parser.parse_args(argv)

    # The build says it cannot run by raising SystemExit before it writes
    # anything, so the data on disk is either the old file or a whole new one.
    try:
        Points(Cache(offline=args.offline)).run(date.today())
    except SystemExit as exc:
        why = str(exc.code).replace("\n", "\n  ")
        print(f"not built: {why}\n  the data was left as it was")
        return 1
    return 0
