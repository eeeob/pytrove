"""The gated order, which is the whole point of this package.

    1. check the sources   -- a failure stops everything
    2. clean the cache     -- only what the check proved stale
    3. run the tool        -- reached only if both succeeded

Steps 1 and 2 are here. Step 3 belongs to whoever asked: the front door runs
the tool, and `python -m devtools._preflight` stops after step 2.

The critical ordering is inside step 2: **the janitor runs before the lock is
rewritten.** The lock records what upstream looked like last time and the
cleaning is decided by comparing against it -- save it first and the evidence
is gone, so every later run concludes "unchanged" and the cache stays stale
forever. That is the original defect this package exists to remove: a tool's
cache layer returns a cached file whenever one exists, even with a network
available, so without something cleaning from the outside a changed source is
never noticed.
"""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

from .check import Checker
from .janitor import Janitor
from .layout import Layout
from .lock import Lock, RunState
from .registry import find_schedule, load

if TYPE_CHECKING:
    from .models import Action, Registry, Report, Schedule

# ============================== one tool ==============================

class Preflight:
    """One tool's check and clean, in the order that keeps them meaningful."""

    def __init__(self, tool: str, *, dry_run: bool = False) -> None:
        self.tool = tool
        self.dry_run = dry_run
        self.registry: Registry = load(tool)
        self.schedule: Schedule | None = find_schedule(tool)
        self.lock = Lock(Layout.lock_path(tool))
        self.state = RunState(Layout.state_path(tool))

    # --- step 1 -----------------------------------------------------------

    def check(self) -> Report:
        return Checker(self.registry, self.lock).run()

    # --- step 2 -----------------------------------------------------------

    def clean(self, report: Report) -> list[Action]:
        """Runs before the lock is saved, deliberately. See the module docstring."""
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
