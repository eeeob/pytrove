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
    failed: list[str] = []
    for key in args.only or list(BUILDERS):
        print(f"== {key}")
        # A builder says it cannot build its platform by raising SystemExit
        # before it writes anything. One platform's outage is no reason to
        # leave the others stale, so the run goes on and only the exit code
        # remembers it.
        try:
            BUILDERS[key](cache).run()
        except SystemExit as exc:
            why = str(exc.code).replace("\n", "\n  ")
            print(f"  not built: {why}")
            failed.append(key)

    if failed:
        print(f"not built: {', '.join(failed)} -- left as it was")
    return 1 if failed else 0
