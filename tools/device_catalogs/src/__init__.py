"""Regenerate pytrove/data/devices/*.json from public sources.

Run it when the catalogs go stale -- new phones, new OS releases, new browsers:

    python -m tools.device_catalogs                 # download + rebuild
    python -m tools.device_catalogs --offline        # rebuild from the cache
    python -m tools.device_catalogs --only android   # one platform

Run it from the repository root; `tools` resolves as a namespace package.
`python -m tools device_catalogs` is the front door: it checks every source
and cleans the stale cache first (tools/_preflight), then runs this. The form
above skips both and builds from whatever the cache holds.

This directory is the tool's `src/`. Beside it sit the sections that are not
logic -- `sources/`, `schedule/`, `ported/`, `config/`, `docs/` -- and
`.cache/`, which holds the downloads and is gitignored. Only the four JSON
files under pytrove/data/devices are written, so the library code never
changes with the data.

Sources, all public:

  appledb.dev            iPhone identifiers, release dates
  api.ipsw.me            every iOS firmware actually released per iPhone
  MTApiEnvironment.m     the exact model strings Telegram iOS sends
  Google Play catalog    the authoritative list of Android model codes
  endoflife.date         release and support-end dates per phone family
  miui-updates-tracker   newest shipped Android version per Xiaomi device
  source.android.com     API level release dates (inlined below)
  dumps.tadiphone.dev    stock firmware: the manufacturer casing everywhere,
                         and the model codes and Android ceilings for the
                         brands endoflife.date does not track
  linuxhw/DMI            real dmidecode output, for Windows/Linux models
  desktop-app/lib_base   the string formats Telegram Desktop reports
  versionhistory.google  released Chrome versions per platform
  mozilla product-details  released Firefox versions
  edgeupdates.microsoft  released Edge versions per platform

No API keys and no authentication: the DMI step reads the repository over the
git protocol (a blobless shallow clone) and the probe files over the raw CDN,
so nothing here is rate limited the way the GitHub API is.

Every network step caches its download, so a first run is slow (the DMI step
reads a few thousand probe files) and `--offline` afterwards is instant and
produces byte-identical output.

One module per responsibility, each owning the constants only it needs
(all of them in this `src/` directory):

    shared.py     paths, the schema number, the small helpers
    cache.py      Cache -- the only thing that touches the network
    catalog.py    Catalog -- the output contract and the key order
    libbase.py    LibBase -- a port of the client's model-string rules
    builder.py    Builder -- the base class of a platform step

    ios.py        IOSBuilder
    android.py    AndroidBuilder, and its API level table
    desktop.py    DesktopBuilder
    web.py        WebBuilder

    firmware.py   FirmwareHarvest -- phone firmware, for the Chinese brands
    dmi.py        DmiHarvest -- PC firmware, for Windows and Linux models

    cli.py        which builders exist, and the argument parsing
"""
from __future__ import annotations as _annotations

from .cli import BUILDERS, main

__all__ = ("BUILDERS", "main")
