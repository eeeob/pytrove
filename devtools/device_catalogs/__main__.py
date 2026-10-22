"""The tool's door: `python -m devtools.device_catalogs`.

The only file in this directory. Everything else is a named section --
`src/` for the logic, `sources/`, `schedule/`, `ported/`, `config/` and
`docs/` for the declarations, `.cache/` for the downloads -- so a stray
module at this level is a structural mistake visible at a glance.

This runs the tool and nothing else. Source checking and cache cleaning
live in `devtools/_preflight`, which the front door invokes before getting
here:

    python -m devtools device_catalogs        # check, clean, then build
    python -m devtools.device_catalogs        # build alone, no network checks
"""

from __future__ import annotations as _annotations

import datetime as dt
import json
from pathlib import Path

from .src.cli import main

#: Warn once when the sources have not been checked lately. This reads a
#: timestamp out of a JSON file and imports nothing: the tool stays unaware
#: that preflight exists, and works identically when it has never run.
_STATE = Path(__file__).parent / ".cache" / "preflight.state.json"
_STALE_DAYS = 10


def _nudge() -> None:
    try:
        stamp = json.loads(_STATE.read_text(encoding="utf-8"))["last_checked"]
        when = dt.datetime.fromisoformat(stamp)
    except Exception:                                 # noqa: BLE001 - advisory only
        return

    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    days = (dt.datetime.now(dt.timezone.utc) - when).days
    if days >= _STALE_DAYS:
        print(f"warning: the sources have not been checked in {days} days.\n"
              f"         run: python -m devtools device_catalogs")


_nudge()
raise SystemExit(main())
