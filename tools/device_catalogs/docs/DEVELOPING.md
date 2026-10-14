# device_catalogs

Regenerates the four device catalogs the library ships:

```
pytrove/data/devices/ios.json
pytrove/data/devices/android.json
pytrove/data/devices/desktop.json
pytrove/data/devices/web.json
```

Those four files are the **only** thing it writes, which is the point: the data
goes stale constantly — new phones, new OS releases, new browsers — and none of
the library code has to change when it does. `pytrove/_devices.py` reads them
and samples from them; see [the sampling split](#sampling-is-code-facts-are-data).

> Read `src/__init__.py` first. It lists every module and every source, and it
> is the map this document assumes.

---

## Running it

```sh
python -m tools device_catalogs                 # check sources, clean, rebuild
python -m tools device_catalogs --only android  # one platform
python -m tools.device_catalogs --offline       # rebuild from the cache alone
```

`--only` takes `ios`, `android`, `desktop` or `web` and is repeatable. The
first form is the front door and checks every source first — see
[`tools/README.md`](../../README.md).

**A first run is slow.** The DMI step reads one probe per distinct model
folder, 420 per vendor, over 16 threads — a few thousand requests, the heaviest
step in the tool by far. Afterwards `--offline` is instant and produces
byte-identical output, which is the property to lean on: if a rebuild from an
unchanged cache changes a file, something is non-deterministic and that is a
bug.

Running the tool's own door (`python -m tools.device_catalogs`) prints a
warning once the sources have not been checked in 10 days. It reads a timestamp
out of `.cache/preflight.state.json` and imports nothing, so the tool stays
unaware that preflight exists.

---

## `src/`, module by module

Every module owns the constants only it needs — including the prose written
into the catalog. Each builder owns its own `MODEL_FORMAT`, `VERSION_FORMAT`,
`SOURCES` and `NOTES` (desktop owns `WINDOWS_DOC` and `LINUX_DOC` instead,
since it documents per OS), every URL, every cache filename and every regex.
`build()` only assembles them, so changing a source or a note is one edit in
one place and never a search through a function body.

| module        | what it owns                                                   |
| ------------- | -------------------------------------------------------------- |
| `shared.py`   | paths, the schema number, the small helpers. Imports nothing.  |
| `cache.py`    | `Cache` — the only thing that touches the network              |
| `catalog.py`  | `Catalog` — the output contract and the key order               |
| `libbase.py`  | `LibBase` — a port of Telegram Desktop's model-string rules     |
| `builder.py`  | `Builder` — the base of a platform step: `key`, `build()`       |
| `ios.py`      | `IOSBuilder`                                                    |
| `android.py`  | `AndroidBuilder`, and the API level table                       |
| `desktop.py`  | `DesktopBuilder`                                                |
| `web.py`      | `WebBuilder`                                                    |
| `firmware.py` | `FirmwareHarvest` — phone firmware, for the Chinese brands      |
| `dmi.py`      | `DmiHarvest` — PC firmware, for Windows and Linux models        |
| `cli.py`      | which builders exist, and the argument parsing                  |

`libbase.py` imports nothing from the package on purpose, so
`tests/tools/tg/test_devices_data.py` can load it alone and feed the shipped data back
through the client's own rules.

A new platform is a `Builder` subclass with a `key`, a `platform` and a
`build()` returning its `Catalog` list, plus one line in `cli.BUILDERS`.

---

## The output contract

`Catalog`'s field order **is** the key order in the file, so a rebuild of
unchanged data produces an unchanged file and a real change shows up as a small
diff. Files are written with `newline="\n"` explicitly: without it the same
cache would produce CRLF on Windows and LF elsewhere, and "a rebuild is
byte-identical" would hold only per platform.

A platform that runs one OS documents itself with four flat fields
(`model_format`, `version_format`, `sources`, `notes`). A platform that runs
several — desktop, where the same PC reports Windows or Linux — fills an `os`
block instead, with those keys per OS, because the formats and caveats are
genuinely different and flattening them would lose that.

`shared.SCHEMA` is 1 and must equal `pytrove/_devices.py::_SCHEMA`. Bump both
together, and only when the JSON layout itself changes.

---

## What the data has to be

Every string is something a real Telegram client could send, and every pairing
is one a real device could produce. A session row that could not have come from
real hardware is worse than a missing one — that is the rule the whole tool is
arranged around.

**Formats are taken from client source and verified, never invented.**

| platform | model                                                     | version |
| -------- | --------------------------------------------------------- | ------- |
| android  | `Build.MANUFACTURER + Build.MODEL`, no separator (`samsungSM-S928B`) | `"SDK " + Build.VERSION.SDK_INT` |
| ios      | the `MTApiEnvironment.platformString` table, not Apple's marketing name | `[UIDevice systemVersion]`, bare |
| desktop  | Telegram Desktop's `DeviceModelPretty` chain over real DMI | `Windows 11 x64` / `Linux ubuntu GNOME Wayland glibc 2.39` |
| web      | `navigator.userAgent` verbatim                             | `navigator.platform` (`Win32`, `MacIntel`, uname on Linux) |

Two consequences worth knowing before editing anything:

- **The server rewrites what Android sends**, so the catalog is also the display
  name. Measured over MTProto: `samsungSM-S918B` is stored as
  `Samsung Galaxy S23 Ultra` and `SDK 34` as `14 (34)`. The device name is
  Google's `Retail Branding + Marketing Name`, which is exactly this catalog's
  `brand` + `name`, and the version mapping is `AndroidBuilder.API_LEVELS` — so
  the server independently confirms both. Every code must still resolve to a
  real device; `tests/tools/tg/test_devices_data.py` checks that against the cached Play
  catalog when it is present.
- **Three identity fields are not ours to generate.** `platform`, `app_name` and
  `official_app` are read by the server from the `api_id`'s registration and
  cannot be sent at all; `lang_pack` is documented as for official apps only;
  `app_version` belongs to whoever registered the `api_id`. The catalogs
  generate exactly the two fields that are the device's own.

### Deliberately out of scope

Each of these is a decision with evidence behind it, not an omission to fill
in:

- **macOS**, because Telegram's two Mac clients disagree on the version string
  (`26.1` vs `macOS 26.1`) and a bare number matches no client's icon rules.
  Apple *hardware* still appears: a Mac booted into Linux reports
  `MacBookPro13,1` through DMI, so those are Linux rows and they stay.
- **Safari**, because its `Version/x.y Safari/605.1.15` suffix has no
  machine-readable feed, so the numbers would have to be invented.
- **Mobile web**, which would need its own verified tokens and
  `navigator.platform` values.
- **Unigram**, the other official Windows client: it reports an uncleaned,
  uncapped product name plus a bare `Windows 11`, so modelling it as well would
  put two mutually exclusive formats in one pool.
- **Tablets, for every Android brand alike** (`AndroidBuilder.SKIP`). A slate
  reports its model exactly as a phone does, but Google's catalog lists far
  more Xiaomi and Redmi tablets than Samsung ones, so filtering one brand's
  slates and not another's silently redistributes group share.
- **Huawei and Honor**: Huawei has no Android 13+ firmware at all, and the Honor
  dumps are GSI or enterprise images reporting `manufacturer=unknown`. Neither
  can yield a retail string, so do not add them from a secondary source.
- **ARM Windows**: reachable in the format, but linuxhw/DMI contributes no ARM
  Windows hardware, so the string could only sit on an x86 model number.

---

## The two harvesters

### `FirmwareHarvest` — the Chinese brands

endoflife.date carries no Chinese phone family and Google's catalog has codes
but no dates, so OPPO, realme, vivo (and Xiaomi, through its own tracker) are
dated from stock firmware: a dump's branch name carries the Android release and
the build timestamp, and the retail `Build.MANUFACTURER`/`Build.MODEL` come out
of the partitions in the device's own `ro.product.property_source_order`.

OPPO and realme need one more step — their partitions hold placeholders
(`manufacturer=oplus`, an internal codename for `model`) and the real values sit
in `odm/etc/<prjname>/build.<flag>.prop`, selected by the bootloader per project
and region, so the numbered directory is listed and every `build.*.prop` in it
is read. Measured casings: `OPPO` upper, `realme` and `vivo` lower.

**This is the one cache that accumulates**, and the reason the `merge` policy
exists. The harvest sees the newest `MAX_PAGES` pages per brand, so as dumps
pile up older devices scroll out of the window and would silently leave the
catalog. The janitor renames the cache to `firmware_records.prev.json`, the
harvest merges it back, each `(brand, code)` keeps a `last_seen` stamp, records
expire after `RECORD_MAX_AGE_DAYS` (730), and the `android` field is a **ceiling
that never moves down**. The tool learns nothing about preflight from this — only
the `.prev` filename.

A dump proves a ceiling but no launch date, and no public feed carries one for
these brands, so each of these devices lists **exactly that one API level**
(`FIRMWARE_BACK` and `XIAOMI_BACK` are both 0). A range below the measured level
would offer a phone a release it may never have run.

### `DmiHarvest` — Windows and Linux models

linuxhw/DMI folder names are that project's own labels, not what a machine
reports, so the builder samples one real `dmidecode` probe per distinct model
and runs the `libbase.py` port of `SimplifyDeviceModel` /
`SimplifyGoodDeviceModel` / `ProductNameToDeviceModel` over it, keeping only
what the client would actually emit. Keep that port in step with
`base_platform_info.cpp`.

The path list comes from a blobless shallow clone, not the GitHub API, which
caps anonymous callers at 60 requests an hour and truncates large trees.

`MIN_READ = 0.90`: sixteen threads against `raw.githubusercontent` gets
throttled, and a silently dropped probe once made a cold rebuild write a
slightly different catalog every time (eleven of 821 models differed between
two builds of an identical commit). The loss cannot be removed — it is somebody
else's rate limit — but a badly throttled run now stops instead of quietly
producing a thinner catalog.

Its cache policy is `keep`, and that is not a preference: the repository takes
commits daily, so `delete` would trigger the whole harvest weekly. PC hardware
turns over slowly and the per-vendor cap means a re-harvest rotates about 1% of
the pool. Delete `dmi_records.json` by hand when you want it rebuilt.

---

## Sampling is code, facts are data

The catalogs state what exists; `pytrove/_devices.py` decides how often each
thing is drawn. Keep that line:

- `_HALF_LIFE_DAYS` weights devices and versions by recency.
- `GROUP_SHARES` splits a group's slice across its own devices — a phone brand,
  a PC vendor, or a browser-and-OS pair like `Chrome on Windows`, because a
  browser's share on Windows says nothing about its share on Linux. Counting
  rows instead would skew the mix: Google lists every regional Samsung variant
  and one Pixel.
- `platform_weight` picks the platform.
- On a multi-OS platform the **OS is drawn first**, by `OS_SHARES`, and only then
  a device that can report it. Letting device weights decide would tie the
  Windows/Linux mix to how many models each OS happens to list.
- `unique_id` seeds a `random.Random`, so a draw is reproducible per identity
  while staying weighted — never modulo-indexed.

Every group named in the data needs an explicit share, and
`tests/tools/tg/test_devices_data.py` fails if one is missing.

---

## The declarations beside `src/`

| section     | file               | what it declares                                        |
| ----------- | ------------------ | ------------------------------------------------------- |
| `sources/`  | `sources.toml`     | every upstream, its contract, its fingerprint, its cache policy |
| `sources/`  | `sources.lock.json`| what the last check saw. Tracked — it is the memory      |
| `ported/`   | `citations.toml`   | the client rules this tool reimplements, by content anchor |
| `config/`   | `config.toml`      | values decided by hand, beside the number upstream can be asked for |
| `schedule/` | `schedule.toml`    | the check cadence, declared again in the workflow        |

The syntax and the full key lists are in [`tools/README.md`](../../README.md).
What belongs here is the judgement: a new third-party rule that gets
reimplemented needs a `[[citation]]` in the same commit, and a hand-chosen
number needs a `[[watch]]`, or the next person has no way to learn it went
stale.

---

## Tests

```sh
pytest tests/tools/tg/test_devices_data.py      # the shipped data, against its sources
pytest tests/devtools/device_catalogs/test_device_catalogs.py   # this tool's own logic
```

`tests/tools/tg/test_devices_data.py` is the one to read before changing a format. It
asserts the string shapes per OS, the `os` tagging, that no device lists an
unknown version or a version of an OS it does not report, that pinning an OS
only draws that OS, that the realised OS mix matches `OS_SHARES`, and that
every draw is an allowed pair. Two of its checks are structural rather than
cosmetic:

- `test_every_desktop_model_is_a_fixed_point_of_lib_bases_own_rules` feeds each
  stored model back through the port as a `product_name` and requires it to come
  back unchanged, so the data and the rules cannot drift apart silently.
- `test_every_android_code_exists_in_googles_catalog` runs against the cached
  Play catalog, so a refresh that invents a code fails immediately.

---

## Known limitations

Stated rather than hidden, because both are decisions rather than fixes:

- **Motorola has no support window in any public feed.** endoflife.date
  publishes `support` and `eol` separately — the support window and the security
  window, which runs about two years past it — and Motorola gets neither
  `support` nor any alternative, so 105 of its 114 rows rest on
  `MAX_OS_UPGRADES` alone while its entry tier really receives one or two
  upgrades. Correcting it needs a hand-maintained per-tier table or dropping the
  low end.
- **The Pixel 7 generation overshoots for the same reason.** Google's `support`
  date is the 5-year security end, not the 3-year OS-upgrade promise, so
  `Pixel 7a` and `Pixel Fold` reach SDK 37 where SDK 36 is their real ceiling.
  Pixel 8 and later carry a 7-year OS commitment, so their ranges are right.
- **Desktop and iOS strings were not measured over MTProto.** A desktop string
  observed in a real session list was unchanged, but the probe's `platform`
  comes from the `api_id`, so testing those properly needs an `api_id`
  registered as that kind of app.
