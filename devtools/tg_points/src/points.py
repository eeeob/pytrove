"""The sources, the merge, and the file the tool writes."""

from __future__ import annotations as _annotations

import json
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from .cache import Cache

#: One point: a user id and the UTC day its account was registered.
Point = tuple[int, str]


class Points:
    """Merge every published point into `tg_points.json`.

    The base is WizardLoop's file, the one the library first shipped with.
    LyAdminBot's `observations` add to it; its `constraints` never do, because
    a constraint is only a day the account was seen alive -- an upper bound on
    the registration, not the registration -- and merging one as a point would
    pull every estimate around it earlier.

    Nothing is ever chosen between two sources. An exact duplicate is kept
    once; an id two sources date differently is kept twice, because the
    library averages the dates of a repeated id when it loads the file.
    """

    WIZARDLOOP_URL: ClassVar[str] = (
        "https://raw.githubusercontent.com/WizardLoop/CreationDate/main/data/tg_points.json"
    )
    WIZARDLOOP_FILE: ClassVar[str] = "wizardloop_points.json"
    LYADMINBOT_URL: ClassVar[str] = (
        "https://raw.githubusercontent.com/LyoSU/LyAdminBot/master/"
        "tools/account-age-calibrate/sources.json"
    )
    LYADMINBOT_FILE: ClassVar[str] = "lyadminbot_sources.json"

    DATA_DIR: ClassVar[Path] = Path(__file__).resolve().parents[3] / "pytrove" / "data"
    OUT_FILE: ClassVar[str] = "tg_points.json"

    #: Telegram's launch day. No account is older, so an earlier date is a
    #: broken row, as is one later than the day of the build.
    FIRST_DAY: ClassVar[str] = "2013-08-14"
    #: Past this many days without a newer point, LyAdminBot has likely not
    #: been refreshed either: a block opened since then is missing, and its
    #: ids are dated inside the last known one. The run says so.
    STALE_DAYS: ClassVar[int] = 180
    DAY: ClassVar[re.Pattern[str]] = re.compile(r"\d{4}-\d{2}-\d{2}")

    def __init__(self, cache: Cache, data_dir: Path = DATA_DIR) -> None:
        """Read the sources through `cache` and write into `data_dir`."""
        self.cache = cache
        self.data_dir = data_dir

    # --- sources -----------------------------------------------------------

    def load(self, name: str, url: str) -> Any:
        """Return the cache entry `name` as JSON, stopping the build when it is not."""
        try:
            return json.loads(self.cache.fetch(name, url))
        except ValueError as exc:
            msg = f"{name} is not JSON ({exc})"
            raise SystemExit(msg) from exc

    def base(self) -> list[Point]:
        """WizardLoop's points, each checked to be `[id, "YYYY-MM-DD"]`."""
        rows = self.load(self.WIZARDLOOP_FILE, self.WIZARDLOOP_URL)
        if not isinstance(rows, list):
            msg = f"{self.WIZARDLOOP_FILE}: expected a list of points"
            raise SystemExit(msg)
        return [self.point(row, self.WIZARDLOOP_FILE) for row in rows]

    def lyadminbot(self) -> dict[str, Any]:
        """LyAdminBot's whole calibration file, checked to be a JSON object."""
        payload = self.load(self.LYADMINBOT_FILE, self.LYADMINBOT_URL)
        if not isinstance(payload, dict):
            msg = f"{self.LYADMINBOT_FILE}: expected a JSON object"
            raise SystemExit(msg)
        return payload

    def groups(self, name: str) -> dict[str, list[Point]]:
        """LyAdminBot's `observations` or `constraints`, per key, each Unix time made a UTC day."""
        groups = self.lyadminbot().get(name)
        if not isinstance(groups, dict):
            msg = f"{self.LYADMINBOT_FILE}: no `{name}` object"
            raise SystemExit(msg)

        found: dict[str, list[Point]] = {}
        for key, rows in groups.items():
            where = f"{self.LYADMINBOT_FILE} {name}[{key!r}]"
            if not isinstance(rows, list):
                msg = f"{where}: expected a list of points"
                raise SystemExit(msg)
            found[key] = [self.observed(row, where) for row in rows]
        return found

    def point(self, row: object, where: str) -> Point:
        """Check one `[id, "YYYY-MM-DD"]` row and return it as a tuple."""
        match row:
            case [int() as uid, str() as day] if (
                not isinstance(uid, bool) and uid >= 0 and self.is_day(day)
            ):
                return uid, day
        msg = f"{where}: malformed point {row!r}"
        raise SystemExit(msg)

    def is_day(self, text: str) -> bool:
        """Whether `text` is a real calendar day written `YYYY-MM-DD`, not just its shape."""
        if not self.DAY.fullmatch(text):
            return False
        try:
            date.fromisoformat(text)
        except ValueError:
            return False
        return True

    def observed(self, row: object, where: str) -> Point:
        """Check one `[id, unix seconds]` row and return it as a UTC-day point."""
        match row:
            case [int() as uid, int() | float() as stamp] if (
                not isinstance(uid, bool) and not isinstance(stamp, bool) and uid >= 0
            ):
                try:
                    return uid, datetime.fromtimestamp(stamp, timezone.utc).date().isoformat()
                except (OverflowError, OSError, ValueError):
                    pass  # a time no calendar holds is as malformed as a wrong shape
        msg = f"{where}: malformed observation {row!r}"
        raise SystemExit(msg)

    def gather(self) -> dict[str, list[Point]]:
        """Every input point by where it came from: the base, then each observation key."""
        gathered = {"wizardloop": self.base()}
        for key, rows in self.groups("observations").items():
            gathered[f"lyadminbot/{key}"] = rows
        return gathered

    # --- the merge ---------------------------------------------------------

    def build(self, gathered: dict[str, list[Point]], today: date) -> list[Point]:
        """Merge `gathered` into the output rows, in date order.

        Raises:
            SystemExit: A point is dated before Telegram existed or after
                `today`. Nothing has been written by then.
        """
        rows = {row for points in gathered.values() for row in points}
        for uid, day in rows:
            if not self.FIRST_DAY <= day <= today.isoformat():
                msg = f"point {uid} is dated {day}, outside {self.FIRST_DAY}..{today}"
                raise SystemExit(msg)
        return sorted(rows, key=lambda row: (row[1], row[0]))

    def report(self, gathered: dict[str, list[Point]], rows: list[Point], today: date) -> None:
        """Print what the merge did, and how far the newest point lags behind."""
        for source, points in gathered.items():
            print(f"  {source}: {len(points)} points")

        total = sum(len(points) for points in gathered.values())
        print(f"  {total - len(rows)} exact duplicates dropped")

        twice = sorted(uid for uid, n in Counter(uid for uid, _ in rows).items() if n > 1)
        if twice:
            shown = ", ".join(map(str, twice[:5])) + (", ..." if len(twice) > 5 else "")
            print(f"  {len(twice)} ids dated differently by two sources, both kept: {shown}")

        previous = self.previous()
        added, removed = len(set(rows) - previous), len(previous - set(rows))
        print(f"  against the current file: +{added} -{removed}")

        newest = rows[-1][1]
        age = (today - date.fromisoformat(newest)).days
        print(f"  newest point {newest}, {age} days old")
        if age > self.STALE_DAYS:
            print(
                f"  warning: no point is newer than {self.STALE_DAYS} days, so a block opened\n"
                f"           since then may be missing. see docs/DEVELOPING.md"
            )

    def previous(self) -> set[Point]:
        """The points of the file this run replaces; empty when there is none."""
        path = self.data_dir / self.OUT_FILE
        if not path.is_file():
            return set()
        return {(uid, day) for uid, day in json.loads(path.read_text(encoding="utf-8"))}

    # --- output ------------------------------------------------------------

    def write(self, rows: list[Point]) -> None:
        """Write the points, one per line as the file has always been."""
        lines = ",\n".join(f'  [{uid}, "{day}"]' for uid, day in rows)
        out = self.data_dir / self.OUT_FILE
        out.write_text(f"[\n{lines}\n]\n", encoding="utf-8", newline="\n")
        print(f"tg_points: {len(rows)} points -> {out}")

    def collect(self, today: date) -> list[Point]:
        """Gather, merge and report; the caller writes once every file is ready."""
        gathered = self.gather()
        rows = self.build(gathered, today)
        self.report(gathered, rows, today)
        return rows
