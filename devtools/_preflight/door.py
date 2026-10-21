"""`python -m devtools <tool>`: check, clean, then run the tool.

The front door, and step 3 of the gated order. It lives here rather than in
`devtools/__main__.py` so that file stays a door and nothing else, matching the
contract every tool folder follows.

The tool is launched through `runpy`, never imported: it is reached exactly as
`python -m devtools.<tool>` reaches it, so there is one code path and the tool
cannot tell the difference. That is the half of the no-reversing rule this
module has to keep -- a tool never learns that preflight exists.
"""

from __future__ import annotations as _annotations

import runpy
import sys
import time
from typing import ClassVar
from collections.abc import Sequence

from .enums import Exit
from .flight import Preflight
from .layout import Layout
from .registry import RegistryError
from .report import TextReport

# ============================== the door ==============================

class Dispatcher:
    """Argument routing for the front door."""

    PROG: ClassVar[str] = "python -m devtools"

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
            print(f"no tool {tool!r} with a source registry under devtools/\n\n"
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
            return report.exit_code(allow_flaky=allow_flaky)
        return None

    # --- step 3 -----------------------------------------------------------

    @classmethod
    def _run(cls, tool: str, tool_argv: list[str]) -> int:
        """Launch the tool through its own door, as a module."""
        module = f"devtools.{tool}"
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
