"""Source checking and cache cleaning for every tool under tools/.

Machinery, not a tool: it has no sources of its own, no config and no
schedule, so it keeps its modules at its own root rather than under `src/`,
and the discovery glob -- `tools/*/sources/sources.toml` -- never finds it
without anything being special-cased by name.

    python -m tools device_catalogs          # check, clean, then build
    python -m tools._preflight --tool X      # check and clean, nothing else
    python -m tools._preflight --tool X --check
    python -m tools._preflight --all
    python -m tools._preflight --list

Naming a tool is required. Running over everything is a decision, not a
default: one of these caches is 20 MB and 5,700 requests to rebuild, and it
should not be touched because somebody typed the command bare.


The tool folder contract
------------------------

A tool's root holds named sections and a single `__main__.py` door. Any other
`.py` at that level is a structural mistake, visible at a glance:

    tools/<tool>/
      __main__.py       the door. imports from src/ and nothing else
      src/              the logic
      sources/          sources.toml, sources.lock.json   (this package)
      config/           config.toml                       (later phase)
      ported/           citations.toml, values.py         (later phase)
      schedule/         schedule.toml                     (later phase)
      docs/             DEVELOPING.md
      .cache/           downloads + preflight.state.json  (gitignored)

A new tool implements that and gets everything here for free. Nothing in this
package names any tool.


Two directions that must not reverse
------------------------------------

**The tool never depends on this package.** No import, no call, no awareness.
It runs perfectly with preflight absent, which is also why `python -m
tools.<tool>` remains a real way in. The one thing a tool learns is a
filename convention: a cache set aside for merging appears as
`<name>.prev<ext>`, and if it never appears, nothing accumulates and nothing
breaks.

**This package never imports a tool.** It reads declarations -- TOML, and in
a later phase one Python file of constants -- so a malformed tool cannot
break the checker and the checker cannot be blamed for a tool's imports.


The order, and why it cannot be rearranged
------------------------------------------

    1. check the sources   a failure stops everything
    2. clean the cache      only what the check proved stale
    3. run the tool         reached only if both succeeded

Inside step 2, the janitor runs **before** the lock is rewritten. The lock
records what upstream looked like last time and the cleaning is decided by
comparing against it; save it first and the evidence is gone, so every later
run concludes "unchanged" and the cache stays stale forever. That is the
original defect this package exists to remove: `Cache.fetch` in a tool
returns a cached file whenever one exists, even with a network available, so
without something cleaning from the outside a changed source is never noticed.


One module per responsibility
-----------------------------

    model.py        the types a registry parses into, and the state names
    registry.py     reading sources.toml; the folder contract as code
    probe.py        the network, and classifying what an answer means
    contract.py     is this body still valid                 (pure)
    fingerprint.py  what is this body now                    (pure)
    lock.py         the tracked lock and the ephemeral run state
    check.py        comparing a probe against the lock
    janitor.py      applying each cache entry's policy
    report.py       rendering, for a terminal and for a workflow
    cli.py          the command line, the gated order, the dispatcher
"""

from .cli import Dispatcher, Exit, Preflight, main

__all__ = ("Dispatcher", "Exit", "Preflight", "main")
