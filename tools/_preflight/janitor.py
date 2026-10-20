"""Removing the cache entries a check proved stale.

Two filesystem verbs, and nothing else: **delete a file, or rename it aside.**
That is the whole reason one generic janitor can serve every tool. It reads no
cache file, parses no format and knows no schema, so a tool can cache CSV,
YAML, Objective-C or its own JSON records and this module is indifferent.

Accumulation is the interesting case. A cache that must grow rather than be
refetched -- the firmware records, where a device scrolling out of the dump
window should not vanish from the catalog -- is renamed to `<name>.prev<ext>`.
The tool finds it on its next harvest and merges, because the code that wrote
those records is the only code that knows `(brand, code)` is their identity
and the Android release is the tie-break. Putting that knowledge here would
mean either a merge spec language or importing tool code, and both are worse.

The one thing the tool learns from preflight is a filename convention. No
import, no call, no awareness: when no `.prev` file exists, nothing
accumulates and nothing breaks.
"""

from __future__ import annotations

import os
import shutil
import stat
import time
from datetime import date
from pathlib import Path
from typing import ClassVar

from .enums import Policy, State, Verb
from .layout import Layout
from .models import Action, Registry, Report

# ============================== the janitor ==============================

class Janitor:
    """Applies each cache entry's declared policy."""

    #: Age checks use whole days, measured from the file's mtime.
    DAY: ClassVar[float] = 86400.0

    def __init__(self, registry: Registry, *, dry_run: bool = False) -> None:
        self.registry = registry
        self.dry_run = dry_run

    # --- the two verbs ----------------------------------------------------

    def _delete(self, path: Path) -> None:
        if self.dry_run or not path.exists():
            return
        if path.is_dir():
            shutil.rmtree(path, onerror=self._drop_readonly)
        else:
            path.unlink()

    def _rename_aside(self, path: Path) -> Path:
        """`firmware_records.json` -> `firmware_records.prev.json`.

        Where it goes is `Layout`'s business, not this module's: the name is
        the entire interface between a tool and this package, so it is
        defined once, beside every other path in the folder contract.
        """

        aside = Layout.aside(path)
        if not self.dry_run:
            self._delete(aside)                   # a stale .prev from a crash
            path.rename(aside)
        return aside

    @staticmethod
    def _drop_readonly(func, path, _exc):         # noqa: ANN001
        """git marks its objects read-only, which makes rmtree fail on Windows.

        `onerror` rather than `onexc`: the latter arrived in 3.12 and tools/
        still has to run on 3.10. It is soft-deprecated, not removed, and
        emits no warning as late as 3.14.
        """

        os.chmod(path, stat.S_IWRITE)
        func(path)

    # --- age --------------------------------------------------------------

    def _age_days(self, path: Path) -> float:
        try:
            return (time.time() - path.stat().st_mtime) / self.DAY
        except OSError:
            return 0.0

    # --- policies ---------------------------------------------------------

    def _apply(self, cache: str, policy: Policy, reason: str) -> Action:
        path = self.registry.cache_dir / cache
        if not path.exists():
            return Action(Verb.KEPT, cache, "not cached yet")

        if policy is Policy.KEEP:
            return Action(Verb.KEPT, cache, f"policy keep; {reason}")
        if policy is Policy.WARN:
            return Action(Verb.WARNED, cache, reason)
        if policy is Policy.MERGE:
            aside = self._rename_aside(path)
            return Action(Verb.RENAMED, cache, reason, aside.name)

        self._delete(path)
        return Action(Verb.DELETED, cache, reason)

    # --- the passes -------------------------------------------------------

    def _sources(self, report: Report) -> list[Action]:
        """Cached downloads whose upstream moved."""

        actions: list[Action] = []
        for verdict in report.verdicts:
            source = self.registry.source(verdict.source_id)
            if source is None or not source.is_cached:
                continue
            if verdict.state is not State.CHANGED:
                continue
            was, now = verdict.was, verdict.now
            moved = f"{was} -> {now}" if now is not None else "content changed"
            actions.append(self._apply(source.cache, source.on_change, moved))
        return actions

    def _overtaken(self, report: Report) -> list[Action]:
        """Cached bodies older than a change the lock already records.

        The scheduled workflow commits the lock, which is what lets the
        failure counter survive a fresh runner -- but a runner has no cache
        of its own to clean. So once it has recorded a move, every later run
        here compares against the new value, concludes `ok`, and leaves a
        body fetched *before* that move sitting in the cache. The report then
        says the sources are current while the build reads one that is not,
        which is the silent staleness this package exists to remove, arriving
        by a different door.

        The rule needs nothing new to be declared: a cache file must be at
        least as new as the newest change anybody has recorded for its
        source. Whole days, matching the lock's own granularity, so a body
        refetched on the day of the change is kept.
        """

        actions: list[Action] = []
        for verdict in report.verdicts:
            source = self.registry.source(verdict.source_id)
            if source is None or not source.is_cached:
                continue
            # A change this run found is the pass below; a failure must not
            # cost anybody a cache; a source that never moved has no date.
            if (verdict.state is State.CHANGED or not verdict.is_clear
                    or not verdict.recorded_change):
                continue

            path = self.registry.cache_dir / source.cache
            if not path.exists():
                continue
            fetched = date.fromtimestamp(path.stat().st_mtime).isoformat()
            if fetched < verdict.recorded_change:
                actions.append(self._apply(
                    source.cache, source.on_change,
                    f"cached {fetched}, but a run on "
                    f"{verdict.recorded_change} already recorded a change"))
        return actions

    def _derived(self, report: Report) -> list[Action]:
        """Produced caches, stale by dependency or by age.

        A produced file has no URL to revalidate -- one of them is built from
        5,700 requests -- so the only honest signals are "a source it was
        built from changed" and "it is simply old".
        """

        changed = {v.source_id for v in report.verdicts
                   if v.state is State.CHANGED}
        actions: list[Action] = []

        for entry in self.registry.derived:
            upstream = sorted(set(entry.derives_from) & changed)
            if upstream:
                actions.append(self._apply(
                    entry.cache, entry.on_change,
                    f"{', '.join(upstream)} changed"))
                continue

            if entry.max_age_days:
                path = self.registry.cache_dir / entry.cache
                age = self._age_days(path)
                if path.exists() and age > entry.max_age_days:
                    actions.append(self._apply(
                        entry.cache, entry.on_change,
                        f"{age:.0f} days old, limit {entry.max_age_days}"))
        return actions

    def _scratch(self) -> list[Action]:
        """Directories that must never survive a run.

        The DMI step clones a repository into the cache and wipes it when it
        is done; a run interrupted in between leaves it behind, and it is
        megabytes of git objects nothing will ever read again.
        """

        actions: list[Action] = []
        for name in self.registry.scratch:
            path = self.registry.cache_dir / name
            if path.exists():
                self._delete(path)
                actions.append(Action(Verb.SCRATCH, name, "left over from a run"))
        return actions

    def _orphans(self) -> list[Action]:
        """Cache files the registry does not account for.

        This is the check that keeps the registry honest: a file here that
        nothing declares is either a leftover from a renamed key or -- the one
        that matters -- a source somebody added to the tool and forgot to
        register, which would then never be checked at all.

        Orphans are reported, never deleted. Guessing that an unknown file is
        rubbish is how a 20 MB cache disappears.
        """

        if not self.registry.cache_dir.is_dir():
            return []

        declared = self.registry.declared_cache_files
        reserved = {Layout.STATE_FILE, *self.registry.scratch}
        actions: list[Action] = []

        for path in sorted(self.registry.cache_dir.iterdir()):
            name = path.name
            if name in declared or name in reserved:
                continue
            if Layout.is_aside(path):
                continue                          # a pending merge, not an orphan
            actions.append(Action(
                Verb.ORPHAN, name,
                "not declared in sources.toml -- a registered source, or stale?"))
        return actions

    # --- entry point ------------------------------------------------------

    def run(self, report: Report) -> list[Action]:
        """Clean up after one check. Order matters only for readability."""

        return [
            *self._scratch(),
            *self._sources(report),
            *self._overtaken(report),
            *self._derived(report),
            *self._orphans(),
        ]

    @staticmethod
    def removed(actions: list[Action]) -> list[str]:
        """What actually left the cache, for the run state file."""

        return [a.cache for a in actions if a.verb.removes]
