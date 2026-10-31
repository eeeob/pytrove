"""Source checking and cache cleaning for every tool under devtools/.

Machinery, not a tool: it has no sources of its own, no config and no
schedule, so it keeps its modules at its own root rather than under `src/`,
and the discovery glob -- `devtools/*/sources/sources.toml` -- never finds it
without anything being special-cased by name.

    python -m devtools device_catalogs          # check, clean, then build
    python -m devtools._preflight --tool X      # check and clean, nothing else
    python -m devtools._preflight --tool X --check
    python -m devtools._preflight --all
    python -m devtools._preflight --list

and once a week, over everything, from .github/workflows/devtools-preflight.yml.
That workflow is the reason any of this pays: a source that dies is otherwise
found by a build failing months later, for what looks like its own fault.

Naming a tool is required. Running over everything is a decision, not a
default: one of these caches is 20 MB and 5,700 requests to rebuild, and it
should not be touched because somebody typed the command bare.


The tool folder contract
------------------------

A tool's root holds named sections and a single `__main__.py` door. Any other
`.py` at that level is a structural mistake, visible at a glance:

    devtools/<tool>/
      __main__.py       the door. imports from src/ and nothing else
      src/              the logic
      sources/          sources.toml, sources.lock.json,  (this package)
                        sources.last_run.json
      schedule/         schedule.toml                     (this package)
      ported/           citations.toml                    (this package)
      config/           config.toml                       (this package)
      docs/             DEVELOPING.md                     (for people)
      .cache/           downloads + preflight.state.json  (gitignored)

A new tool implements that and gets everything here for free. Nothing in this
package names any tool.


Two directions that must not reverse
------------------------------------

**The tool never depends on this package.** No import, no call, no awareness.
It runs perfectly with preflight absent, which is also why `python -m
devtools.<tool>` remains a real way in. The one thing a tool learns is a
filename convention: a cache set aside for merging appears as
`<name>.prev<ext>`, and if it never appears, nothing accumulates and nothing
breaks.

**This package never imports a tool.** It reads declarations, all of them
TOML, so a malformed tool cannot break the checker and the checker cannot be
blamed for a tool's imports. Values stay on the classes that use them, where
every other constant in this project lives; what a declaration holds is the
part no code can state about itself -- the file a rule was ported from and
the lines it rests on, or the page a hand-kept number was read off.


Three kinds of promise, and what breaking one costs
---------------------------------------------------

    [[source]]    sources/sources.toml    fetched, cached, parsed on every
                  build. A dead or reshaped one stops everything: the tool
                  has bespoke handling for each, so it needs a code change.

    [[citation]]  ported/citations.toml   read once by a human and
                  reimplemented. Checked for the exact lines the port rests
                  on; a moved rule stops the build too, because the port
                  would otherwise keep emitting strings the client itself no
                  longer produces.

    [[watch]]     config/config.toml      decided by hand, next to the one
                  number upstream can still be asked for. Never gates
                  anything -- the generator does not read these URLs -- and a
                  difference is reported every run until somebody revisits
                  the decision, since the baseline is the declaration itself
                  rather than the lock.


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

Read down the list: each one depends only on those above it.

    enums.py        the vocabulary: every closed set of values
    layout.py       the tool folder contract: where anything lives
    models.py       the types -- declarations in, results out
    registry.py     parsing a tool's four .toml declarations
    probe.py        the network, and classifying what an answer means
    contract.py     is this body still valid                 (pure)
    fingerprint.py  what is this body now                    (pure)
    lock.py         the tracked lock and the ephemeral run state
    check.py        comparing an answer against its baseline
    janitor.py      applying each cache entry's policy
    report.py       rendering, for a terminal and for a workflow
    flight.py       steps 1 and 2, in the order that matters
    cli.py          python -m devtools._preflight
    door.py         python -m devtools <tool>: and then step 3

`enums.py`, `layout.py` and `models.py` import nothing from the package, so
any of them can be read first and alone.
"""

from __future__ import annotations as _annotations

from .cli import Cli, main
from .door import Dispatcher
from .enums import Exit
from .flight import Preflight

__all__ = ("Cli", "Dispatcher", "Exit", "Preflight", "main")
