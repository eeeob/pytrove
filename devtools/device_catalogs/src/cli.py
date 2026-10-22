"""Which builders exist, and the argument parsing that drives them."""

from __future__ import annotations as _annotations

import argparse
from typing import TYPE_CHECKING

from .android import AndroidBuilder
from .cache import Cache
from .desktop import DesktopBuilder
from .ios import IOSBuilder
from .web import WebBuilder

if TYPE_CHECKING:
    from .builder import Builder

#: `--only` name -> the step. The order is the order a full run writes in.
BUILDERS: dict[str, type[Builder]] = {
    builder.key: builder for builder in (IOSBuilder, AndroidBuilder, DesktopBuilder, WebBuilder)
}


def main(argv: list[str] | None = None) -> int:
    """Parse the command line, run the selected builders, return the exit code."""
    parser = argparse.ArgumentParser(
        description="Regenerate pytrove/data/devices/*.json from public sources."
    )
    parser.add_argument("--offline", action="store_true", help="rebuild from the cache only")
    parser.add_argument(
        "--only",
        choices=tuple(BUILDERS),
        action="append",
        help="build just this platform; repeatable",
    )
    args = parser.parse_args(argv)

    cache = Cache(offline=args.offline)
    for key in args.only or list(BUILDERS):
        print(f"== {key}")
        BUILDERS[key](cache).run()

    return 0
