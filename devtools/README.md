# devtools/

Development-only generators, and the machinery that keeps them honest.

Nothing here ships. `devtools/` is deliberately absent from `pyproject.toml`, so
installing the library pulls none of it, and the only dependency is a TOML
reader that Python 3.11 already has:

```sh
pip install -r devtools/requirements.txt    # installs nothing on 3.11+
```

Run everything from the repository root; `devtools` resolves as a namespace
package.

| path                | what it is                                             |
| ------------------- | ------------------------------------------------------ |
| `device_catalogs/`  | regenerates `pytrove/data/devices/*.json` — [guide](device_catalogs/docs/DEVELOPING.md) |
| `_preflight/`       | source checking and cache cleaning, shared by any tool |
| `__main__.py`       | the front door                                         |
| `requirements.txt`  | TOML reading, and only below 3.11                      |

---

## Three ways in

```sh
python -m devtools device_catalogs              # check, clean, then build
python -m devtools.device_catalogs --offline    # build alone, no network at all
python -m devtools._preflight --tool device_catalogs    # check and clean, no build
```

The first is the front door and the one to use by default. Arguments it does
not recognise are passed through to the tool, so
`python -m devtools device_catalogs --only web` works.

The front door consumes three flags of its own:

| flag              | effect                                                       |
| ----------------- | ------------------------------------------------------------ |
| `--no-preflight`  | skip the check and the cleaning                              |
| `--allow-flaky`   | proceed past a source that could not be reached              |
| `--offline`       | passed on to the tool, and implies `--no-preflight`          |

Its exit code is the tool's own, unless preflight refused to let the tool
start — then it is preflight's.

### `python -m devtools._preflight`

| flag             | effect                                                    |
| ---------------- | --------------------------------------------------------- |
| `--tool NAME`    | the tool directory under `devtools/` to work on           |
| `--all`          | every tool that declares sources                          |
| `--list`         | list those tools and exit                                 |
| `--check`        | check only; touch no cache                                |
| `--janitor`      | check and clean — the default                             |
| `--allow-flaky`  | treat an unreachable source as passable                   |
| `--dry-run`      | report what would be cleaned, change nothing              |
| `--json`         | machine-readable output                                   |
| `--quiet`        | print nothing; the exit code is the answer                |

Naming a tool is required. Running over everything is a decision, not a
default: one of these caches is 20 MB and 5,700 requests to rebuild, and it
should not be touched because somebody typed the command bare.

### Exit codes

The exit code is the whole verdict; nothing parses a report to second-guess
it.

| code | meaning                                                                   | response       |
| ---- | ------------------------------------------------------------------------- | -------------- |
| 0    | nothing moved                                                             | nothing        |
| 1    | a source is gone, reshaped, or has failed every run for three runs        | a developer    |
| 2    | sources are healthy, but something moved                                  | a rebuild      |
| 3    | could not be reached this once (not returned under `--allow-flaky`)       | retry          |
| 4    | a declaration file is malformed                                           | a developer    |

Over `--all`, the worst code across the tools is returned, not the first
non-zero one.

---

## The tool folder contract

A tool's root holds named sections and a single `__main__.py` door. Any other
`.py` at that level is a structural mistake, visible at a glance.

```
devtools/<tool>/
  __main__.py       the door. imports from src/ and nothing else
  src/              the logic
  sources/          sources.toml, sources.lock.json
  schedule/         schedule.toml
  ported/           citations.toml
  config/           config.toml
  docs/             DEVELOPING.md
  .cache/           downloads + preflight.state.json  (gitignored)
```

A new tool implements that and gets everything in `_preflight` for free.
Nothing in `_preflight` names any tool: discovery is the glob
`devtools/*/sources/sources.toml`, which is also why `_preflight` — having no
sources of its own — is skipped without being special-cased, and why it keeps
its modules at its own root rather than under `src/`.

### Two directions that must not reverse

**A tool never depends on `_preflight`.** No import, no call, no awareness. It
runs perfectly with preflight absent, which is why `python -m devtools.<tool>`
remains a real way in. The one thing a tool learns is a filename convention: a
cache set aside for merging appears as `<name>.prev<ext>`, and if it never
appears, nothing accumulates and nothing breaks.

**`_preflight` never imports a tool.** It reads declarations, all of them
TOML, so a malformed tool cannot break the checker and the checker cannot be
blamed for a tool's imports.

---

## Three kinds of promise

Each costs something different when broken, which is why they are separate
files rather than one list.

| declaration    | file                  | what it is                                              | when it breaks |
| -------------- | --------------------- | ------------------------------------------------------- | -------------- |
| `[[source]]`   | `sources/sources.toml`| fetched, cached and parsed on every build               | fatal — the tool has bespoke handling for each, so it needs a code change |
| `[[derived]]`  | `sources/sources.toml`| a cache the tool produces from one or more sources      | cleaned by policy when an input moves |
| `[[citation]]` | `ported/citations.toml`| a rule read once by a human and reimplemented here     | fatal — the port would keep emitting strings the client no longer produces |
| `[[watch]]`    | `config/config.toml`  | a value decided by hand, beside the number upstream can still be asked for | never gates anything; reported every run until a human revisits the decision |

A watch's baseline is its own declaration, not the lock, so a moved value keeps
being reported until somebody edits the file. The generator never reads a
watch's URL.

## The order, and why it cannot be rearranged

```
1. check the sources    a failure stops everything
2. clean the cache      only what the check proved stale
3. run the tool         reached only if both succeeded
```

Inside step 2 the janitor runs **before** the lock is rewritten. The lock
records what upstream looked like last time, and the cleaning is decided by
comparing against it; save it first and the evidence is gone, so every later
run concludes "unchanged" and the cache stays stale for ever.

That is the original defect this package exists to remove: a tool's own
`Cache.fetch` returns a cached file whenever one exists, even with a network
available, so without something cleaning from the outside a changed source is
never noticed.

The janitor only ever deletes a file or renames it aside. It never reads or
rewrites one, so it needs no knowledge of any format — which is what lets one
generic janitor serve every tool.

---

## Adding a source

```toml
[[source]]
id = "play_catalog"                  # stable; the lock is keyed by it
url = "https://example.org/devices.csv"
cache = "play_devices.csv"           # the file the tool reads, under .cache/
on_change = "delete"                 # delete | merge | keep | warn
consumed_by = "src/android.py :: AndroidBuilder.codes(); PLAY_URL, PLAY_FILE"
on_removal = """
What leaves the output if this source dies, in enough detail that the cost of
living without it is clear."""

  [source.contract]                  # is the body still valid
  kind = "csv"                       # csv | json_list | json_object | text | git_refs
  must_have_columns = ["Retail Branding", "Model"]
  min_rows = 1000

  [source.fingerprint]               # what the body is now
  kind = "csv_rows"                  # bytes_len | csv_rows | json_len |
                                     # regex_count | regex_max_int | git_head
```

`on_change` policies: `delete` (drop it, the next build refetches), `merge`
(rename it aside as `<name>.prev<ext>` for the tool to merge on its next
harvest), `keep` (never remove automatically — too expensive to rebuild),
`warn` (say so, touch nothing).

`regex_max_int` and `regex_count` also need a `pattern`. Optional keys:
`probe_url` (fetch something cheaper than the body to check), `notes`.

A cache the tool *produces* is a `[[derived]]` instead, which has no URL and
names its inputs:

```toml
[[derived]]
id = "firmware_records"
cache = "firmware_records.json"
derives_from = ["dumps_gitlab_api"]
on_change = "merge"
max_age_days = 30
record_max_age_days = 730            # for an accumulating cache
cost = "~126 dumps x 5 files"
consumed_by = "src/firmware.py :: FirmwareHarvest.records(); RECORDS_FILE"
```

## Adding a citation

Use one whenever code here reimplements a rule that lives in somebody else's
source. Anchors are **content**, never line numbers — the Android model line
moved 224 → 228 without changing.

```toml
[[citation]]
id = "telegram_android_identity"
url = "https://raw.githubusercontent.com/.../ConnectionsManager.java"
anchors = [
  'Build.MANUFACTURER + Build.MODEL',
  '"SDK " + Build.VERSION.SDK_INT',
]
ported_to = "src/android.py :: AndroidBuilder.MODEL_FORMAT"
on_drift = """
What to re-read, and what in this repository would then be wrong."""
```

## Adding a watch

Use one for a number that was decided by hand and has no mechanical source —
a weight, a ceiling, a hand-estimated share.

```toml
[[watch]]
id = "glibc_versions"
url = "https://example.org/glibc.json"
value = 43                           # what the decision currently assumes
used_by = "pytrove/tg_tools/_internal/catalog.py :: LIBC"
decision = """
Why this value, and what changing it would mean."""

  [watch.fingerprint]
  kind = "regex_max_int"
  pattern = '"version":\s*"2\.(\d+)"'
```

---

## The lock

`devtools/<tool>/sources/sources.lock.json` is tracked, and that is not an
accident: it is the checker's memory. It holds each source's fingerprint, the
day it last changed, its contract verdict, and the consecutive-failure counter
the escalation rule rests on. A CI runner is new every week, so unless the
lock goes back into the repository no counter ever reaches three and no source
is ever called dead.

Three consecutive failing runs make a source `DEAD` (exit 1), and
`--allow-flaky` does not waive that: the waiver covers a dropped connection,
not three weeks of one.

The ephemeral half lives in `.cache/preflight.state.json` — when the last check
ran, how long it took, what was pruned. It is gitignored, and a tool may read
the timestamp out of it to warn that its sources are stale (see
`device_catalogs/__main__.py`), which is the one piece of knowledge a tool is
allowed to have, since it is a file and not an import.

Because CI pushes the lock and a runner has no cache to clean, a change CI
recorded is a change no local janitor acted on. So a cache file must be at
least as new as the newest change anybody has recorded for its source,
measured in whole days; an older one is dropped on the next local run with the
reason printed.

---

## The weekly check

`.github/workflows/devtools-preflight.yml` runs `--all --allow-flaky` once a week
and on `workflow_dispatch`, uploads the report, commits the lock, and
translates the exit code. It never runs a generator: rebuilding a catalog
changes a file that ships in the wheel, and that is a decision with a human
behind it.

The cadence is declared **twice** — in the workflow's `cron` and in
`devtools/<tool>/schedule/schedule.toml`, which is the declaration of record —
because a trigger cannot be computed in Actions. `tests/devtools/preflight/test_preflight.py`
fails in both directions if the two drift apart, and the report derives
"about N days" from the cron rather than from a second hand-written number.

---

## `_preflight`, module by module

Each depends only on those above it. `enums.py`, `layout.py` and `models.py`
import nothing from the package, so any of them can be read first and alone.

```
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
```

A source's state is one of `new`, `ok`, `changed`, `flaky`, `contract_broken`
or `gone`; the last two are fatal, `flaky` is transient, the rest are clear.

## Tests

```sh
pytest tests/devtools/preflight/test_preflight.py          # the machinery and the folder contract
pytest tests/devtools/device_catalogs/test_device_catalogs.py    # the catalogs tool's own logic
pytest tests/tools/tg/test_devices_data.py       # the generated data, against its sources
```

`tests/devtools/preflight/test_preflight.py` also guards the structure itself: the layering above,
the one-door rule, the cron duplication, and that every tool carries a
`docs/DEVELOPING.md`. None of them need a network.

## Adding a tool

1. `mkdir -p devtools/<tool>/{src,sources,schedule,ported,config,docs}`
2. `devtools/<tool>/__main__.py` — the door, importing from `src/` and nothing
   else.
3. `sources/sources.toml` — a `[tool]` table, then one `[[source]]` per
   upstream and one `[[derived]]` per cache the tool writes.
4. `schedule/schedule.toml` — a cron, and the same line in the workflow.
5. `ported/citations.toml` and `config/config.toml` as soon as either applies.
6. `docs/DEVELOPING.md` — the per-tool guide.

`python -m devtools._preflight --list` should then name it, with no change
anywhere in `_preflight`.
