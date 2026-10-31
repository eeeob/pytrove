"""Tests for the generator under devtools/device_catalogs.

`devtools/` is development-only and ships in no wheel, so these tests skip
entirely when it is absent. Nothing here touches the network: every harvest
step that would is driven through a `Cache` pointed at a temporary directory,
which is the same thing `--offline` does.

What is tested is the one piece of the harvest that keeps state between runs.
`FirmwareHarvest` is cumulative because the dumps group is a window: it lists
the newest projects first and only four pages deep, so a phone scrolls out
from behind newer dumps and a run that cannot see it would otherwise take it
out of the catalog. The accumulation and the window it compensates for are
both invisible in the output -- the catalog looks the same either way -- so
they need checking here or nowhere.
"""

from __future__ import annotations as _annotations

import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import NoReturn
from urllib.error import URLError

import pytest

TOOLS = Path(__file__).resolve().parents[3] / "devtools"
CATALOGS = TOOLS / "device_catalogs"

pytestmark = pytest.mark.skipif(not CATALOGS.is_dir(), reason="devtools/ is not installed")

if TOOLS.parent.as_posix() not in [p.replace("\\", "/") for p in sys.path]:
    sys.path.insert(0, str(TOOLS.parent))

from devtools._preflight import registry as _registry  # noqa: E402
from devtools._preflight.enums import Policy  # noqa: E402
from devtools._preflight.layout import Layout  # noqa: E402
from devtools.device_catalogs.src.cache import Cache  # noqa: E402
from devtools.device_catalogs.src.firmware import FirmwareHarvest  # noqa: E402
from devtools.device_catalogs.src.shared import TODAY  # noqa: E402

WINDOW = FirmwareHarvest.RECORD_MAX_AGE_DAYS


def _days_ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def _record(
    code: str, *, brand: str = "vivo", android: int = 15, seen: str = TODAY
) -> dict[str, object]:
    return {
        "brand": brand,
        "manufacturer": brand,
        "code": code,
        "android": android,
        "date": "2025-06-01",
        "project": 1,
        "last_seen": seen,
    }


def _harvest(
    tmp_path: Path, *, offline: bool = False, aside: list[dict[str, object]] | None = None
) -> FirmwareHarvest:
    cache = Cache(directory=tmp_path, offline=offline)
    if aside is not None:
        cache.write_json(FirmwareHarvest.PREV_FILE, aside)
    return FirmwareHarvest(cache)


# ------------------------- the filename contract --------------------------


def test_the_set_aside_name_is_the_one_the_janitor_produces() -> None:
    # The two sides never import each other: the janitor renames a `merge`
    # cache to <name>.prev<ext> knowing nothing about what is in it, and the
    # harvest reads that name knowing nothing about the janitor. A filename is
    # the whole interface, so a typo in it would not fail anywhere -- the
    # harvest would simply never accumulate, and no run would say so.
    stem, _, ext = FirmwareHarvest.RECORDS_FILE.rpartition(".")

    assert FirmwareHarvest.PREV_FILE == f"{stem}{Layout.PREV}.{ext}"


def test_the_record_window_matches_what_the_registry_declares() -> None:
    # record_max_age_days is what the registry promises a reader, and
    # RECORD_MAX_AGE_DAYS is what actually expires a record. Only the second
    # one does anything, so they have to be checked against each other.
    registry = _registry.load("device_catalogs")
    entry = next(d for d in registry.derived if d.cache == FirmwareHarvest.RECORDS_FILE)

    assert entry.on_change is Policy.MERGE
    assert entry.record_max_age_days == WINDOW


# ----------------------------- the merge ----------------------------------


def test_a_device_the_dump_window_scrolled_past_stays_in_the_catalog(tmp_path: Path) -> None:
    # The case the whole mechanism exists for: OPPOCPH2579 left one run and
    # came back in the next, because four pages of dumps no longer reached it.
    harvest = _harvest(tmp_path, aside=[_record("CPH2579", brand="oppo", seen=_days_ago(30))])

    merged = harvest.merge([_record("V2401")])
    codes = sorted(r["code"] for r in merged)

    assert codes == ["CPH2579", "V2401"]


def test_a_carried_device_keeps_the_sighting_it_was_last_seen_on(tmp_path: Path) -> None:
    # Carrying must not re-stamp the record: a device that keeps being carried
    # would then never expire, and the window would be unbounded in practice.
    harvest = _harvest(tmp_path, aside=[_record("CPH2579", seen=_days_ago(400))])

    carried = next(r for r in harvest.merge([]) if r["code"] == "CPH2579")

    assert carried["last_seen"] == _days_ago(400)


def test_a_device_unseen_for_longer_than_the_window_is_dropped(tmp_path: Path) -> None:
    # The other half of carrying. Without an expiry the cache would only ever
    # grow, and a model the dumps genuinely stopped carrying -- because the
    # phone is gone -- would stay in the catalog for good.
    harvest = _harvest(
        tmp_path,
        aside=[
            _record("OLD", seen=_days_ago(WINDOW + 1)),
            _record("EDGE", seen=_days_ago(WINDOW - 1)),
        ],
    )

    codes = sorted(r["code"] for r in harvest.merge([]))

    assert codes == ["EDGE"]


def test_a_ceiling_a_dump_proved_never_moves_back_down(tmp_path: Path) -> None:
    # `android` is the newest release a dump ever proved this phone runs, and
    # AndroidBuilder turns it into the top of the device's version list. A run
    # that sees only an older regional dump of the same phone must not lower
    # it: that would take a release off a device that demonstrably shipped it.
    harvest = _harvest(tmp_path, aside=[_record("V2401", android=16, seen=_days_ago(30))])

    merged = harvest.merge([_record("V2401", android=15)])

    assert len(merged) == 1
    assert merged[0]["android"] == 16
    # Seen again today, though, so its clock restarts.
    assert merged[0]["last_seen"] == TODAY


def test_a_fresh_dump_raising_the_ceiling_wins(tmp_path: Path) -> None:
    harvest = _harvest(tmp_path, aside=[_record("V2401", android=15, seen=_days_ago(30))])

    merged = harvest.merge([_record("V2401", android=16)])

    assert [r["android"] for r in merged] == [16]


def test_the_same_code_under_two_brands_is_two_devices(tmp_path: Path) -> None:
    # The key is (brand, code), not code: OPPO and realme ship the same
    # hardware under different retail names and the catalog carries both.
    harvest = _harvest(tmp_path, aside=[_record("RMX3999", brand="realme", seen=_days_ago(10))])

    merged = harvest.merge([_record("RMX3999", brand="oppo")])

    assert len(merged) == 2


def test_nothing_set_aside_means_the_harvest_behaves_as_it_always_did(tmp_path: Path) -> None:
    # The accumulation has to be invisible when it is not in play, because
    # that is every run between two preflight cleanings.
    harvest = _harvest(tmp_path)
    fresh = [_record("V2401"), _record("CPH2579", brand="oppo")]

    assert harvest.merge(fresh) == fresh


# --------------------------- dating a carry -------------------------------


def test_a_harvest_from_before_the_merge_is_dated_by_its_own_file(tmp_path: Path) -> None:
    # Records written before the file accumulated carry no sighting date. They
    # cannot be dropped for that -- the first cleaning would then throw away
    # every device at once -- and they cannot be called current either, so the
    # file's own mtime stands in: that is genuinely when the harvest ran.
    harvest = _harvest(
        tmp_path,
        aside=[
            {
                "brand": "vivo",
                "manufacturer": "vivo",
                "code": "V2401",
                "android": 15,
                "date": "2025-06-01",
                "project": 1,
            }
        ],
    )
    written = _days_ago(10)
    when = time.mktime(date.fromisoformat(written).timetuple())
    os.utime(harvest.cache.path(FirmwareHarvest.PREV_FILE), (when, when))

    carried = harvest.carried()

    assert [r["last_seen"] for r in carried] == [written]


# ------------------------------ persistence --------------------------------


def test_the_set_aside_file_is_retired_once_it_has_been_merged(tmp_path: Path) -> None:
    # It has to go, or the next cleaning's rename would have nothing to
    # overwrite and a run that merged successfully would keep re-reading an
    # old generation, including the records it just expired.
    harvest = _harvest(tmp_path, aside=[_record("V2401")])

    harvest.store(harvest.merge([]))

    assert harvest.cache.has(FirmwareHarvest.RECORDS_FILE)
    assert not harvest.cache.has(FirmwareHarvest.PREV_FILE)


def test_what_is_written_is_ordered_by_brand_then_code(tmp_path: Path) -> None:
    # The cache is read back verbatim on the next run, so a stable order is
    # what keeps a rebuild from the same cache byte-identical.
    harvest = _harvest(tmp_path)

    harvest.store(
        [_record("V2401"), _record("CPH2579", brand="oppo"), _record("CPH2401", brand="oppo")]
    )
    out = harvest.cache.read_json(FirmwareHarvest.RECORDS_FILE)

    assert [(r["brand"], r["code"]) for r in out] == [
        ("oppo", "CPH2401"),
        ("oppo", "CPH2579"),
        ("vivo", "V2401"),
    ]


def test_an_offline_rebuild_falls_back_to_the_set_aside_file(tmp_path: Path) -> None:
    # A cleaning followed by an offline rebuild is a real sequence: preflight
    # renames the file, then somebody rebuilds with no network. The data is
    # right there, so refusing would be a worse answer than a harvest that
    # gains no new devices.
    harvest = _harvest(tmp_path, offline=True, aside=[_record("V2401")])

    out = harvest.records()

    assert [r["code"] for r in out] == ["V2401"]
    assert harvest.cache.has(FirmwareHarvest.RECORDS_FILE)


def test_an_offline_rebuild_with_nothing_cached_still_stops(tmp_path: Path) -> None:
    harvest = _harvest(tmp_path, offline=True)

    with pytest.raises(SystemExit, match="run once with network access"):
        harvest.records()


def test_a_cached_harvest_is_used_as_it_stands(tmp_path: Path) -> None:
    # The cache always wins over the network, even without --offline, and that
    # must not change now that a merge exists: a run with a records file does
    # not harvest, so it must not touch a set aside file either.
    harvest = _harvest(tmp_path, aside=[_record("CPH2579", brand="oppo")])
    harvest.cache.write_json(FirmwareHarvest.RECORDS_FILE, [_record("V2401")])

    assert [r["code"] for r in harvest.records()] == ["V2401"]
    assert harvest.cache.has(FirmwareHarvest.PREV_FILE)


# ----------------------- an API that does not answer ----------------------
#
# The outage this section exists for: dumps.tadiphone.dev answered 502 to
# every request, the listing read that as "no dumps", and a build from an
# empty cache wrote `[]` and took every OPPO, realme and vivo phone out of the
# catalog. A request that fails says nothing; only an answer is a harvest.


def _no_answer(url: str, *, timeout: int = 0) -> NoReturn:
    msg = f"HTTP Error 502: Bad Gateway ({url}, {timeout}s)"
    raise URLError(msg)


def test_a_failed_page_is_not_the_end_of_the_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Page one answers with a full page, page two fails: stopping there and
    # returning what page one held is how the outage went unnoticed.
    harvest = _harvest(tmp_path)

    def api(path: str) -> list[dict[str, object]]:
        if "&page=1&" in path:
            return [{"id": 1, "default_branch": "not-a-release"}]
        return _no_answer(path)

    monkeypatch.setattr(harvest, "api", api)

    with pytest.raises(URLError):
        harvest.dumps("vivo")


def test_an_unanswered_api_carries_the_last_harvest_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Treated as --offline: the devices stay, and their sightings are not
    # renewed, so RECORD_MAX_AGE_DAYS still expires them on time.
    harvest = _harvest(tmp_path, aside=[_record("CPH2579", brand="oppo", seen=_days_ago(40))])
    monkeypatch.setattr(harvest.cache, "download", _no_answer)

    out = harvest.records()

    assert [(r["code"], r["last_seen"]) for r in out] == [("CPH2579", _days_ago(40))]
    assert harvest.cache.read_json(FirmwareHarvest.RECORDS_FILE) == out


def test_an_unanswered_api_with_nothing_to_carry_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harvest = _harvest(tmp_path)
    monkeypatch.setattr(harvest.cache, "download", _no_answer)

    with pytest.raises(SystemExit, match="did not answer"):
        harvest.records()

    assert not harvest.cache.has(FirmwareHarvest.RECORDS_FILE)


def test_an_empty_listing_is_a_harvest_and_still_carries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other side of the line: an API that answers with no dumps is a
    # renewal that found nothing, merged like any other, so what an earlier
    # harvest proved is carried until its own window runs out.
    harvest = _harvest(tmp_path, aside=[_record("V2401", seen=_days_ago(40))])
    monkeypatch.setattr(harvest, "api", lambda path: [])

    assert [r["code"] for r in harvest.records()] == ["V2401"]


def test_an_empty_records_file_is_harvested_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # What the outage left behind. Read as it stands it would build a catalog
    # with none of these brands; read as missing it costs three listings.
    harvest = _harvest(tmp_path, aside=[_record("V2401")])
    harvest.cache.write_json(FirmwareHarvest.RECORDS_FILE, [])
    monkeypatch.setattr(harvest.cache, "download", _no_answer)

    assert [r["code"] for r in harvest.records()] == ["V2401"]
