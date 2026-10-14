"""The front door: `python -m tools <tool> [arguments]`.

Checks the tool's sources, cleans whatever the check proved stale, then runs
the tool -- each step conditional on the one before it. The flow itself lives
in `tools._preflight.cli.Dispatcher`; this file is only the door, which is the
same shape every tool's own `__main__.py` has.

A tool can still be run on its own, with no check and no cleaning:

    python -m tools.<tool> --offline
"""

from __future__ import annotations

from ._preflight.cli import Dispatcher

raise SystemExit(Dispatcher.main())
