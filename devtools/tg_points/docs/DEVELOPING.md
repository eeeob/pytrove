# tg_points

Regenerates the two files the library estimates a Telegram account's age
from:

```
pytrove/data/tg_points.json   known accounts and the day each was registered
pytrove/data/tg_blocks.json   the randomized id blocks and the day each opened
```

`tg_account_created_at` (`pytrove/tg_tools/accounts.py`) uses them in two
ways, split at the first block's lowest id (7e9):

- **Below it**, ids grew with time. The points are sorted by id, fitted so the
  date never goes down as the id grows, and the estimate is interpolated
  between the two points around the id.
- **From it on**, Telegram hands out ids at random inside a block, so an id
  says only which block it is in. The estimate is the middle of that block's
  window: from its opening to the next block's opening, or to now for the
  block still open.

Telegram publishes nothing of the kind. All of it comes from somebody's
observations, so this tool does not collect data; it gathers the published
observations.

> Read `src/__init__.py` first. It lists every module and every source.

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
date outside Telegram's lifetime, a block that cannot be dated) prints
`not built: <why>`, writes nothing and exits 1. `cli.build` collects both files
before it writes either, so the data on disk is always the old pair or a whole
new one. ssleg is the exception: it only feeds the cross-check, so without it
the run says `ssleg cross-check skipped` and goes on.

A run prints what it did:

```
  wizardloop: 212 points
  lyadminbot/v1-cross-bot-audit-2026-04: 122 points
  ...
  23 exact duplicates dropped
  19 ids dated differently by two sources, both kept: 11538514, ...
  against the current file: +0 -0
  newest point 2026-07-31, 93 days old
  8 randomized id blocks, the last opened 2026-05-12
    7.0-7.2e9  opened 2024-02-19  ssleg 2024-02-20 (+1d)
    ...
    8.8-9.0e9  opened 2026-05-12  ssleg: no pool
```

Past `Points.STALE_DAYS` (180) without a newer point it also warns that a block
opened since then may be missing: until LyAdminBot adds it, its ids are dated
inside the last known block.

## `src/`, module by module

| module   | what it owns |
|----------|--------------|
| `cache`  | `Cache.fetch`, the only network access. An outage stops the build; it is never read as an empty source. |
| `points` | `Points`: WizardLoop and LyAdminBot, the merge, the report, and `tg_points.json`. `groups()` reads LyAdminBot's `observations` or `constraints` for both modules. |
| `blocks` | `Blocks`: the bounds, the openings, ssleg's cross-check, and `tg_blocks.json`. |
| `cli`    | `build`, which writes both files or neither, and `main`: `--offline`, and the one place a `SystemExit` becomes exit 1. |

Every URL, file name and threshold is a `ClassVar` on the class that uses it.

## The output contract

- `tg_points.json`: a JSON list of `[int, "YYYY-MM-DD"]`, one point per line,
  in date order, then id order. An id can appear twice with different dates;
  that is deliberate, see the merge below.
- `tg_blocks.json`: a JSON list of `[low, high, "YYYY-MM-DD"]`, one block per
  line, in id order, back to back (each `high` is the next `low`), openings
  strictly increasing. The closing is not stored: it is the next block's
  opening, and a second copy could only disagree with it.
- LF line endings and a final newline on every platform (`.gitattributes`
  marks both files `-text`).
- `tests/tools/tg/internal/test_points.py` checks both shapes.

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
- 6 of its points below 7e9 are dated after the first block opened
  (2024-02-19). The library caps every point below the first block at that
  opening, so they cannot pull the line into the block era.

It stays the base anyway: nothing else MIT-licensed covers the sequential era.
These checks are not run on a build, because they would fail on most of the
base every time and a report that is always red is ignored.

### LyoSU/LyAdminBot — the part that is maintained

`tools/account-age-calibrate/sources.json`, the calibration data of a spam bot.
Its README says it is refreshed from the bot's own databases every one to two
months, that a refresh is a new key, and that old keys are never deleted. So
**every key is merged**, and a new key appears in the report.

The file holds three parts, and the tool treats each differently:

- `observations` are "registration-date estimates", `[id, unix seconds]`. Each
  becomes a point, dated by its UTC day.
- `constraints` are "hard upper bounds": the account was seen alive at that
  moment, so it was registered no later. They are **never** points: merging
  one would date an account by the day a bot first saw it. They do date
  blocks, below.
- `randomizedBlocks` are the block bounds, `[low, high]`, with no dates.

The phrases that say what each part means, and how a block is dated, are in
the source contract (`must_contain`): if the file stops saying them, the check
fails before the build trusts it.

### anton/tg_account_age (git.ssleg.tech) — the cross-check

`tg_account_age.py`, MIT, on a personal Gitea. Its `uid_dict` maps the highest
id of each pool to the first and last day ids in it were handed out. It holds
ranges, not points, so it is not data here; but its pools above 7e9 have
exactly LyAdminBot's block bounds, found independently, which makes it the
check on the openings. It is Python source, cached as `ssleg_pools.txt`, and
read as a syntax tree: only `uid_dict = {int: (date(y, m, d), date(...))}` is
accepted, and nothing in the file is ever run.

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

## The blocks

**How each is dated.** LyAdminBot's own rule, quoted in its contract: a block
opened on the earliest day any account inside it was seen, observation or
constraint alike, and closed when the next one opened. `Blocks.build` stops if
a block has no row inside it, if the bounds are not back to back, or if the
openings do not move strictly forward.

**Why the library trusts them.** Measured in October 2026:

- In our own points, the rank correlation between id and date is +0.99 below
  7e9, and +0.00, +0.32, +0.39 and +0.10 inside the four blocks that hold more
  than three points. Inside a block, a larger id is not a newer account.
- LyAdminBot and ssleg, which share no code and no data, cut the ids at the
  same eight places (7.0, 7.2, 7.5, 7.6, 8.2, 8.5, 8.6, 8.8e9), and their
  dates for each cut agree to within one to nine days.
- LyAdminBot reports that an envelope test over 28.7M users found allocation
  inside a block "uniform across the whole range from day one". That is its
  claim on private data; our points are consistent with it but too few to
  prove it.

**The cross-check.** Every run prints each opening beside the start of
ssleg's pool for the same ids. A gap of `Blocks.DRIFT_DAYS` (14) or more is
marked `!`. It never stops the build: ssleg is one person's server.

## Rejected sources

Checked in October 2026, so they need not be looked at again until something
changes:

| source | why not |
|--------|---------|
| HotaruProject/Hotaru | AGPL-3.0, and 211 of our 212 points verbatim |
| NextAlone/Nagram, Nnngram | GPL; its table is fitted (PAVA), not observed |
| komarugif/komarugram-go | a fitted table; the raw points are kept private |
| guidegram | proprietary, and our points with the dates moved |
| grammyjs/telegram.tools, materialgram, Cherrygram, OctoGram, tginfo/getids and the other client forks | hand-copied forks of one old table, mostly GPL or AGPL |
| Telegram's `registration_month` | per user, month precision, and only through a user session |

## Reminders

Nothing here can make the sources update; each is maintained by one person,
by hand. What the tool can do is notice:

- **The weekly preflight** (`schedule/schedule.toml`, run daily by
  `.github/workflows/devtools-preflight.yml`) compares each source with the
  sha256 in `sources/sources.lock.json`. A changed byte is exit 2 and a lock
  commit on `main`: rebuild. A new block appears this way, the day LyAdminBot
  appends it to `randomizedBlocks`.
- **The run itself** warns when the newest point is more than 180 days old,
  and the door warns when the sources have not been checked in 10 days.

No test depends on the calendar: one would start failing on a day nothing
changed, in a pull request about something else.

## The declarations beside `src/`

- `sources/sources.toml`: the three sources. No fingerprints, so the lock
  compares sha256 and an in-place date fix counts as a change. Default-branch
  URLs, not pinned commits: a pin never reports an update.
- `schedule/schedule.toml`: weekly.

## Tests

```sh
pytest tests/devtools/tg_points/test_tg_points.py   # this tool
pytest tests/devtools/preflight/test_preflight.py   # its declarations and folder
pytest tests/tools/tg                              # the shipped data, through the library
```

## Known limitations

- **An id past the last block's high bound** (9e9 today, not yet reached)
  counts as part of the last block. Telegram will have opened a new one by
  then; it reaches the data when LyAdminBot appends it.
- **The open block's window grows every day**, so the estimate for an id in it
  drifts later until the next block opens. That is the honest answer: such an
  account could have been made any day since the block opened.
- **No first-party source.** The only route to fresh, verified points would be
  collecting `registration_month` from a personal session, which is out of
  scope for a public build.
