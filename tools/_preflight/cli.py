"""The command line, and the gated order it enforces.

    1. check the sources   -- a failure stops everything
    2. clean the cache     -- only what the check proved stale
    3. run the tool        -- reached only if both succeeded

Every step is conditional on the one before it. Step 3 is launched through
`runpy`, never imported: the tool stays entirely unaware that preflight
exists, which is what keeps the dependency one-directional and lets the tool
be run on its own when that is what you want.

The critical ordering is inside step 2: the janitor runs **before** the lock
is rewritten. The lock is the record of what upstream looked like last time,
and cleaning is decided by comparing against it -- overwrite it first and the
evidence is gone, every later run concludes "unchanged", and the cache stays
stale forever.
"""

from __future__ import annotations

import argparse
import runpy
import sys
import time
from typing import ClassVar, Sequence

from .check import Checker, Report
from .janitor import Action, Janitor
from .lock import Lock, RunState
from .model import Registry
from .registry import Layout, RegistryError, load
from .schedule import find as find_schedule
from .report import JsonReport, TextReport

# ============================== exit codes ==============================

class Exit:
    """What the caller -- a shell, or a scheduled workflow -- learns.

    Distinct codes rather than a bare failure, because the three outcomes
    call for three different responses: nothing, a rebuild, or a developer.
    """

    OK: ClassVar[int] = 0
    #: Sources are healthy but something moved; a rebuild is worthwhile.
    CHANGED: ClassVar[int] = 2
    #: A source is gone, reshaped, or has failed every run for long enough
    #: to be believed. Needs a human, not a retry.
    DEAD: ClassVar[int] = 1
    #: Could not be reached this once. Not an accusation; retry or
    #: --allow-flaky, which is what a scheduled run passes: weather is not a
    #: failure, and three weeks of it reports as DEAD anyway.
    UNREACHABLE: ClassVar[int] = 3
    #: The registry itself is malformed.
    REGISTRY: ClassVar[int] = 4

    #: Worst first. `--all` has to report the worst outcome across the tools
    #: it ran, not the first non-zero one: taking the first would answer
    #: "unreachable" for a run in which another tool's source is dead, and
    #: the caller would retry instead of fetching a developer.
    WORST: ClassVar[tuple[int, ...]] = (REGISTRY, DEAD, UNREACHABLE, CHANGED, OK)

    @classmethod
    def worse(cls, a: int, b: int) -> int:
        rank = {code: i for i, code in enumerate(cls.WORST)}
        return a if rank.get(a, 0) <= rank.get(b, 0) else b


# ============================== the steps ==============================

class Preflight:
    """One tool's check and clean, in the order that keeps them meaningful."""

    def __init__(self, tool: str, *, dry_run: bool = False) -> None:
        self.tool = tool
        self.dry_run = dry_run
        self.registry: Registry = load(tool)
        self.schedule = find_schedule(tool)
        self.lock = Lock(Layout.lock_path(tool))
        self.state = RunState(Layout.state_path(tool))

    def check(self) -> Report:
        return Checker(self.registry, self.lock).run()

    def clean(self, report: Report) -> list[Action]:
        """Step 2. Runs before the lock is saved, deliberately."""

        return Janitor(self.registry, dry_run=self.dry_run).run(report)

    def record(self, report: Report, actions: list[Action],
               duration_s: float) -> bool:
        """Persist both files. Returns whether the tracked lock changed."""

        if self.dry_run:
            return False
        wrote = self.lock.save(self.lock.rebuild(self.registry, list(report.verdicts)))
        self.state.write(
            verdicts=list(report.verdicts),
            network=report.network,
            pruned=Janitor.removed(actions),
            duration_s=duration_s,
        )
        return wrote

    @staticmethod
    def code(report: Report, *, allow_flaky: bool = False) -> int:
        """The one thing a scheduler reads.

        An escalated source is DEAD and `--allow-flaky` does not waive it.
        That is the whole point of counting consecutive runs: the waiver
        covers a dropped connection, not three weeks of one, and until
        something acted on the count the rule was a sentence in a report that
        changed no outcome.
        """

        if report.fatal or report.escalated:
            return Exit.DEAD
        if report.transient and not allow_flaky:
            return Exit.UNREACHABLE
        if report.changed:
            return Exit.CHANGED
        return Exit.OK


# ============================== the command ==============================

class Cli:
    """Argument parsing and the top-level flow."""

    PROG: ClassVar[str] = "python -m tools._preflight"

    @classmethod
    def parser(cls) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog=cls.PROG,
            description="Check a tool's sources and clean its stale cache.")

        which = parser.add_mutually_exclusive_group()
        which.add_argument(
            "--tool", metavar="NAME",
            help="the tool directory under tools/ to work on")
        which.add_argument(
            "--all", action="store_true",
            help="every tool that declares sources")
        which.add_argument(
            "--list", action="store_true",
            help="list the tools that declare sources, and exit")

        stage = parser.add_mutually_exclusive_group()
        stage.add_argument("--check", action="store_true",
                           help="check only; touch no cache")
        stage.add_argument("--janitor", action="store_true",
                           help="check and clean, the default")

        parser.add_argument("--allow-flaky", action="store_true",
                            help="treat an unreachable source as passable")
        parser.add_argument("--dry-run", action="store_true",
                            help="report what would be cleaned, change nothing")
        parser.add_argument("--json", action="store_true",
                            help="machine-readable output, for the scheduler")
        parser.add_argument("--quiet", action="store_true",
                            help="print nothing; the exit code is the answer")
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
                print(JsonReport.render(report, flight.registry, actions,
                                        schedule=flight.schedule))
            else:
                print(TextReport.render(report, flight.registry, actions,
                                       dry_run=flight.dry_run,
                                       schedule=flight.schedule))
                if wrote:
                    print(f"  lock updated: "
                          f"{Layout.lock_path(tool).relative_to(Layout.TOOLS_DIR.parent)}")

        return flight.code(report, allow_flaky=args.allow_flaky)

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
                print("no tool under tools/ declares sources", file=sys.stderr)
                return Exit.REGISTRY
        elif args.tool:
            tools = [args.tool]
        else:
            # Neither named: running over everything is a decision, not a
            # default. A tool whose cache is 20 MB should not be touched
            # because somebody typed the command with no arguments.
            cls.parser().error("name a tool with --tool, or pass --all")
            return Exit.REGISTRY                  # unreachable; parser exits

        worst = Exit.OK
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


# ========================= the front door's step 3 =========================

class Dispatcher:
    """`python -m tools <tool> [args]`: check, clean, then run.

    Lives here rather than in `tools/__main__.py` so that file stays a door
    and nothing else, matching the contract every tool follows.
    """

    PROG: ClassVar[str] = "python -m tools"

    #: Flags the dispatcher consumes; everything else is the tool's.
    NO_PREFLIGHT: ClassVar[str] = "--no-preflight"
    ALLOW_FLAKY: ClassVar[str] = "--allow-flaky"
    #: A tool run with no network cannot be preceded by a network check, so
    #: this implies --no-preflight rather than contradicting it.
    OFFLINE: ClassVar[str] = "--offline"

    @classmethod
    def usage(cls) -> str:
        tools = ", ".join(Layout.tools()) or "(none)"
        return (
            f"usage: {cls.PROG} <tool> [{cls.NO_PREFLIGHT}] [{cls.ALLOW_FLAKY}] "
            f"[tool arguments...]\n"
            f"\n"
            f"Checks the tool's sources and cleans its stale cache, then runs it.\n"
            f"Each step is conditional on the one before it.\n"
            f"\n"
            f"tools with a source registry: {tools}\n"
            f"\n"
            f"  {cls.NO_PREFLIGHT}   skip the check and the cleaning\n"
            f"  {cls.ALLOW_FLAKY}    proceed past a source that could not be reached\n"
            f"  {cls.OFFLINE}        passed to the tool, and implies "
            f"{cls.NO_PREFLIGHT}\n")

    @classmethod
    def main(cls, argv: Sequence[str] | None = None) -> int:
        argv = list(sys.argv[1:] if argv is None else argv)

        if not argv or argv[0] in ("-h", "--help"):
            print(cls.usage())
            return Exit.OK if argv else Exit.REGISTRY

        tool, rest = argv[0], argv[1:]
        if tool not in Layout.tools():
            print(f"no tool {tool!r} with a source registry under tools/\n\n"
                  f"{cls.usage()}", file=sys.stderr)
            return Exit.REGISTRY

        skip = cls.NO_PREFLIGHT in rest or cls.OFFLINE in rest
        allow_flaky = cls.ALLOW_FLAKY in rest
        tool_argv = [a for a in rest
                     if a not in (cls.NO_PREFLIGHT, cls.ALLOW_FLAKY)]

        if not skip:
            code = cls._preflight(tool, allow_flaky=allow_flaky)
            if code is not None:
                return code

        return cls._run(tool, tool_argv)

    # --- steps 1 and 2 ----------------------------------------------------

    @classmethod
    def _preflight(cls, tool: str, *, allow_flaky: bool) -> int | None:
        """None when the run may continue; an exit code when it may not."""

        started = time.monotonic()
        try:
            flight = Preflight(tool)
        except RegistryError as exc:
            print(exc, file=sys.stderr)
            return Exit.REGISTRY

        report = flight.check()
        actions = flight.clean(report)
        flight.record(report, actions, time.monotonic() - started)

        print(TextReport.render(report, flight.registry, actions,
                               schedule=flight.schedule))

        if not report.may_proceed(allow_flaky=allow_flaky):
            return flight.code(report, allow_flaky=allow_flaky)
        return None

    # --- step 3 -----------------------------------------------------------

    @classmethod
    def _run(cls, tool: str, tool_argv: list[str]) -> int:
        """Launch the tool through its own door, as a module.

        `runpy` rather than an import: the tool is reached exactly as
        `python -m tools.<tool>` reaches it, so there is one code path and the
        tool cannot tell the difference.
        """

        module = f"tools.{tool}"
        argv = sys.argv
        sys.argv = [f"{sys.executable} -m {module}", *tool_argv]
        try:
            runpy.run_module(module, run_name="__main__", alter_sys=True)
        except SystemExit as exc:
            return cls._exit_code(exc.code)
        finally:
            sys.argv = argv
        return Exit.OK

    @staticmethod
    def _exit_code(code: object) -> int:
        """What the interpreter itself would do with a `SystemExit` argument.

        A tool is entitled to `raise SystemExit("the cache is missing")`, and
        Python prints that message and exits 1. Coercing it with `int()`
        instead raised a `ValueError`, so the tool's own explanation was
        replaced by a traceback from the launcher.
        """

        if code is None:
            return Exit.OK
        if isinstance(code, int):
            return int(code)                      # bool is an int; 1, not True
        print(code, file=sys.stderr)
        return Exit.DEAD
