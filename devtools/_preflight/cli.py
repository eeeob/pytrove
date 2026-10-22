"""`python -m devtools._preflight`: check and clean, and nothing else.

Arguments in, an exit code out. The work is `flight.Preflight`; the decisions
are `Report.exit_code`; this module only reads a command line and prints what
came back, so the one thing to look for here is that nothing judges anything.

Naming a tool is required. Running over everything is a decision, not a
default: one of these caches is 20 MB and 5,700 requests to rebuild, and it
should not be touched because somebody typed the command bare.
"""

from __future__ import annotations as _annotations

import argparse
import sys
import time
from typing import TYPE_CHECKING, ClassVar

from .enums import Exit
from .flight import Preflight
from .layout import Layout
from .registry import RegistryError
from .report import JsonReport, TextReport

if TYPE_CHECKING:
    from collections.abc import Sequence

# ============================== the command ==============================


class Cli:
    """Argument parsing and the top-level flow."""

    PROG: ClassVar[str] = "python -m devtools._preflight"

    @classmethod
    def parser(cls) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog=cls.PROG, description="Check a tool's sources and clean its stale cache."
        )

        which = parser.add_mutually_exclusive_group()
        which.add_argument(
            "--tool", metavar="NAME", help="the tool directory under devtools/ to work on"
        )
        which.add_argument("--all", action="store_true", help="every tool that declares sources")
        which.add_argument(
            "--list", action="store_true", help="list the tools that declare sources, and exit"
        )

        stage = parser.add_mutually_exclusive_group()
        stage.add_argument("--check", action="store_true", help="check only; touch no cache")
        stage.add_argument("--janitor", action="store_true", help="check and clean, the default")

        parser.add_argument(
            "--allow-flaky", action="store_true", help="treat an unreachable source as passable"
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="report what would be cleaned, change nothing"
        )
        parser.add_argument("--json", action="store_true", help="machine-readable output")
        parser.add_argument(
            "--quiet", action="store_true", help="print nothing; the exit code is the answer"
        )
        return parser

    # --- one tool ---------------------------------------------------------

    @classmethod
    def one(cls, tool: str, args: argparse.Namespace) -> int:
        started = time.monotonic()
        flight = Preflight(tool, dry_run=args.dry_run or args.check)

        report = flight.check()
        actions = [] if args.check else flight.clean(report)
        wrote = flight.record(report, actions, time.monotonic() - started)

        if not args.quiet:
            if args.json:
                print(JsonReport.render(report, flight.registry, actions, schedule=flight.schedule))
            else:
                print(
                    TextReport.render(
                        report,
                        flight.registry,
                        actions,
                        dry_run=flight.dry_run,
                        schedule=flight.schedule,
                    )
                )
                if wrote:
                    print(
                        f"  lock updated: "
                        f"{Layout.lock_path(tool).relative_to(Layout.TOOLS_DIR.parent)}"
                    )

        return report.exit_code(allow_flaky=args.allow_flaky)

    # --- entry point ------------------------------------------------------

    @classmethod
    def main(cls, argv: Sequence[str] | None = None) -> int:
        args = cls.parser().parse_args(argv)

        if args.list:
            for tool in Layout.tools():
                print(tool)
            return Exit.OK

        if args.all:
            tools = Layout.tools()
            if not tools:
                print("no tool under devtools/ declares sources", file=sys.stderr)
                return Exit.REGISTRY
        elif args.tool:
            tools = [args.tool]
        else:
            cls.parser().error("name a tool with --tool, or pass --all")
            return Exit.REGISTRY  # unreachable; parser exits

        worst: int = Exit.OK
        for index, tool in enumerate(tools):
            if len(tools) > 1 and not args.quiet and not args.json:
                print(f"{'' if index == 0 else chr(10)}== {tool}")
            try:
                code = cls.one(tool, args)
            except RegistryError as exc:
                print(f"{tool}: {exc}", file=sys.stderr)
                code = Exit.REGISTRY
            worst = Exit.worse(worst, code)
        return worst


def main(argv: Sequence[str] | None = None) -> int:
    return Cli.main(argv)
