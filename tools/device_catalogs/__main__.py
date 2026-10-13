"""The tool's door: `python -m tools.device_catalogs`.

The only file in this directory. Everything else is a named section --
`src/` for the logic, `sources/`, `config/`, `ported/`, `schedule/` and
`docs/` for the declarations, `.cache/` for the downloads -- so a stray
module at this level is a structural mistake visible at a glance.

This runs the tool and nothing else. Source checking and cache cleaning
live in `tools/_preflight`, which the front door invokes before getting
here:

    python -m tools device_catalogs        # check, clean, then build
    python -m tools.device_catalogs        # build alone, no network checks
"""

from __future__ import annotations

from .src.cli import main

raise SystemExit(main())
