# tg_points

Regenerates the known account-creation points the library ships:

```
pytrove/data/tg_points.json
```

Each point is `[user id, "YYYY-MM-DD"]`: a real account and the UTC day it was
registered. `tg_account_created_at` (`pytrove/tg_tools/accounts.py`) sorts them
by id, fits the dates so they never go down as the id grows, and interpolates
between the two points around an id.

Telegram publishes nothing of the kind. Every point is somebody's observation,
so this tool does not collect data; it gathers the observations that are
published.

> Read `src/__init__.py` first. It lists every module and both sources.

---

## Running it

```sh
python -m devtools tg_points             # check the sources, clean, rebuild
python -m devtools.tg_points --offline   # rebuild from the cache alone
```

The cache always wins over the network, so a rebuild from the same cache is
byte-identical. Preflight drops a cached file when its source changes, and the
next run fetches it again.

A build that cannot finish (a source that does not answer, a malformed row, a
date outside Telegram's lifetime) prints `not built: <why>`, writes nothing and
exits 1. The data on disk is always the old file or a whole new one.

A run prints what it did:

```
  wizardloop: 212 points
  lyadminbot/v1-cross-bot-audit-2026-04: 122 points
  ...
  23 exact duplicates dropped
  19 ids dated differently by two sources, both kept: 11538514, ...
  against the current file: +132 -0
  newest point 2026-07-31, 93 days old
```

Past `Points.STALE_DAYS` (180) it also warns that every recent account is being
extrapolated.

## `src/`, module by module

| module   | what it owns |
|----------|--------------|
| `cache`  | `Cache.fetch`, the only network access. An outage stops the build; it is never read as an empty source. |
| `points` | `Points`: both sources, the merge, the report, and the file it writes. Every URL, file name and threshold is a `ClassVar` on it. |
| `cli`    | `main`: `--offline`, and the one place a `SystemExit` becomes exit 1. |

## The output contract

- A JSON list of `[int, "YYYY-MM-DD"]`, one point per line, in date order, then
  id order. `tests/tools/tg/internal/test_points.py` checks the shape and the
  order.
- LF line endings and a final newline on every platform (`.gitattributes`
  marks the file `-text`).
- An id can appear twice with different dates. That is deliberate: see the
  merge below.

## The sources, and how far each is trusted

### WizardLoop/CreationDate — the base

`data/tg_points.json`, 212 points from 2013-08-14 to 2025-11-11. These are the
points the library first shipped with; it was copied by hand before this tool
existed. The repository has one commit (2026-01-25) and has not changed since.
It is itself a copy of `Jobians/telegram-id-age`'s `dataset.json` (2025-11-22),
which gathered the points from "X joined Telegram" service messages and
declares MIT only in its `package.json`.

Its dates run **late**, measured against the two other sources:

- 106 of its 160 points below 7e9 are dated after a LyAdminBot constraint on an
  equal or higher id, which in the sequential era is impossible.
- 13 of its 52 points at or above 7e9 are dated after their block had already
  closed.
- 61 of its 212 points fall outside the date range ssleg's `tg_account_age`
  gives their id.

It stays the base anyway: nothing else MIT-licensed covers the sequential era.
These checks are not run on a build, because they would fail on most of the
base every time and a report that is always red is ignored.

### LyoSU/LyAdminBot — the part that is maintained

`tools/account-age-calibrate/sources.json`, the calibration data of a spam bot.
Its README says it is refreshed from the bot's own databases every one to two
months, that a refresh is a new key, and that old keys are never deleted. So
**every key is merged**, and a new key appears in the report.

The file holds two kinds of row, and the tool treats them differently:

- `observations` are "registration-date estimates", `[id, unix seconds]`. Each
  becomes a point, dated by its UTC day.
- `constraints` are "hard upper bounds": the account was seen alive at that
  moment, so it was registered no later. They are **never** points. Merging
  one would date an account by the day a bot first saw it, and pull every
  estimate around it earlier.

Both phrases are in the source contract (`must_contain`): if the file stops
saying what its halves mean, the check fails before the build trusts it.

### What the merge does

- An exact duplicate `(id, date)` is kept once. 23 are dropped today, most of
  them rows LyAdminBot's v1 audit shares with WizardLoop. A shared row is the
  same observation copied twice, not a second confirmation.
- An id the two sources date differently is kept **twice**. The library already
  averages the dates of a repeated id when it loads the file, so nothing is
  chosen here and nothing is thrown away.
- A row is never dropped silently. The only rows that stop a build are broken
  ones: not `[id, date]`, or dated before 2013-08-14 or after the day of the
  build.

## Rejected sources

Checked in October 2026, so they need not be looked at again until something
changes:

| source | why not |
|--------|---------|
| `anton/tg_account_age` (git.ssleg.tech) | MIT, maintained, but it holds date **ranges** per id pool, not points. Useful as a cross-check, not as data. |
| HotaruProject/Hotaru | AGPL-3.0, and 211 of our 212 points verbatim |
| NextAlone/Nagram, Nnngram | GPL; its table is fitted (PAVA), not observed |
| komarugif/komarugram-go | a fitted table; the raw points are kept private |
| guidegram | proprietary, and our points with the dates moved |
| grammyjs/telegram.tools, materialgram, Cherrygram, OctoGram, tginfo/getids and the other client forks | hand-copied forks of one old table, mostly GPL or AGPL |
| Telegram's `registration_month` | per user, month precision, and only through a user session |

## Reminders

Nothing here can make the sources update; both are maintained by one person,
by hand. What the tool can do is notice:

- **The weekly preflight** (`schedule/schedule.toml`, run daily by
  `.github/workflows/devtools-preflight.yml`) compares each source with the
  sha256 in `sources/sources.lock.json`. A changed byte is exit 2 and a lock
  commit on `main`: rebuild.
- **The run itself** warns when the newest point is more than 180 days old,
  and the door warns when the sources have not been checked in 10 days.

No test depends on the calendar: one would start failing on a day nothing
changed, in a pull request about something else.

## The declarations beside `src/`

- `sources/sources.toml`: both sources. No fingerprints, so the lock compares
  sha256 and an in-place date fix counts as a change. Default-branch URLs, not
  pinned commits: a pin never reports an update.
- `schedule/schedule.toml`: weekly.

## Tests

```sh
pytest tests/devtools/tg_points/test_tg_points.py   # this tool
pytest tests/devtools/preflight/test_preflight.py   # its declarations and folder
pytest tests/tools/tg                              # the shipped data, through the library
```

## Known limitations

- **Ids at or above 7e9 carry no date.** Since 2024-02 Telegram hands out ids
  at random inside blocks (7.0–7.2e9, 7.2–7.5e9, ... 8.8–9.0e9), so inside a
  block an id says only which block it is in. Both LyAdminBot's
  `randomizedBlocks` and ssleg's pools show the same boundaries. The library
  still interpolates there, which gives precision the data does not have.
- **No first-party source.** The only route to fresh, verified points would be
  collecting `registration_month` from a personal session, which is out of
  scope for a public build.
