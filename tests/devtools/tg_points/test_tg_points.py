"""Tests for the generator under devtools/tg_points.

`devtools/` is development-only and ships in no wheel, so these tests skip
entirely when it is absent. Nothing here touches the network: every source is
written into a `Cache` pointed at a temporary directory and read `--offline`,
and the one network test replaces `urlopen`.
"""

from __future__ import annotations as _annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import NoReturn
from urllib.error import URLError

import pytest

TOOLS = Path(__file__).resolve().parents[3] / "devtools"
TOOL = TOOLS / "tg_points"

pytestmark = pytest.mark.skipif(not TOOL.is_dir(), reason="devtools/ is not installed")

if TOOLS.parent.as_posix() not in [p.replace("\\", "/") for p in sys.path]:
    sys.path.insert(0, str(TOOLS.parent))

from devtools.tg_points.src import cache as _cache  # noqa: E402
from devtools.tg_points.src import cli as _cli  # noqa: E402
from devtools.tg_points.src.cache import Cache  # noqa: E402
from devtools.tg_points.src.points import Points  # noqa: E402

TODAY = date(2026, 11, 1)
BASE = [[0, "2013-08-14"], [2768409, "2013-11-01"], [7679610, "2013-12-31"]]


def _unix(day: str, clock: str = "12:00:00") -> int:
    return int(datetime.fromisoformat(f"{day}T{clock}+00:00").timestamp())


def _sources(
    tmp_path: Path,
    *,
    base: object = BASE,
    observations: object = None,
    constraints: object = None,
) -> Points:
    """A `Points` reading the given sources offline and writing into `tmp_path / "data"`."""
    cache_dir, data_dir = tmp_path / "cache", tmp_path / "data"
    cache_dir.mkdir()
    data_dir.mkdir()
    (cache_dir / Points.WIZARDLOOP_FILE).write_text(json.dumps(base), encoding="utf-8")
    payload = {
        "observations": {"k": []} if observations is None else observations,
        "constraints": constraints or {},
        "randomizedBlocks": [],
    }
    (cache_dir / Points.LYADMINBOT_FILE).write_text(json.dumps(payload), encoding="utf-8")
    return Points(Cache(cache_dir, offline=True), data_dir)


def _out(points: Points) -> Path:
    return points.data_dir / Points.OUT_FILE


# --- the cache --------------------------------------------------------------


def test_the_cache_returns_a_cached_file_without_the_network(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_bytes(b"[]")
    assert Cache(tmp_path).fetch("a.json", "https://unused.invalid/") == b"[]"


def test_the_cache_refuses_a_missing_file_offline(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="--offline"):
        Cache(tmp_path, offline=True).fetch("a.json", "https://unused.invalid/")


def test_a_source_that_does_not_answer_stops_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_answer(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "502"
        raise URLError(msg)

    monkeypatch.setattr(_cache.urllib.request, "urlopen", no_answer)
    with pytest.raises(SystemExit, match="did not answer"):
        Cache(tmp_path).fetch("a.json", "https://example.invalid/a.json")
    assert not (tmp_path / "a.json").exists()


# --- the sources ------------------------------------------------------------


def test_an_observation_is_dated_by_its_utc_day(tmp_path: Path) -> None:
    late = _unix("2026-03-01", "23:59:59")
    points = _sources(tmp_path, observations={"k": [[8_800_000_000, late]]})
    assert points.observations() == {"k": [(8_800_000_000, "2026-03-01")]}


@pytest.mark.parametrize(
    "row",
    [[1, "2013-8-14"], [1, "2013-02-30"], ["1", "2013-08-14"], [True, "2013-08-14"], [1], -1],
)
def test_a_malformed_base_point_stops_the_build(tmp_path: Path, row: object) -> None:
    points = _sources(tmp_path, base=[*BASE, row])
    with pytest.raises(SystemExit, match="malformed point"):
        points.base()


@pytest.mark.parametrize(
    "row", [[1, "2026-01-01"], [1, True], [-1, 1_700_000_000], [1], [1, 1e20], [1, float("nan")]]
)
def test_a_malformed_observation_stops_the_build(tmp_path: Path, row: object) -> None:
    points = _sources(tmp_path, observations={"k": [row]})
    with pytest.raises(SystemExit, match="malformed observation"):
        points.observations()


@pytest.mark.parametrize("base", [{"not": "a list"}, "text"])
def test_a_base_that_is_not_a_list_stops_the_build(tmp_path: Path, base: object) -> None:
    with pytest.raises(SystemExit, match="expected a list"):
        _sources(tmp_path, base=base).base()


def test_observations_must_be_an_object_of_lists(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="expected a list"):
        _sources(tmp_path, observations={"k": {"not": "a list"}}).observations()

    (tmp_path / "again").mkdir()
    with pytest.raises(SystemExit, match="no `observations`"):
        _sources(tmp_path / "again", observations=[]).observations()


def test_a_source_that_is_not_json_stops_the_build(tmp_path: Path) -> None:
    points = _sources(tmp_path)
    (points.cache.directory / Points.WIZARDLOOP_FILE).write_text("<html>", encoding="utf-8")
    with pytest.raises(SystemExit, match="is not JSON"):
        points.base()


# --- the merge --------------------------------------------------------------


def test_the_merge_keeps_an_exact_duplicate_once_and_a_disputed_id_twice(
    tmp_path: Path,
) -> None:
    observations = {"a": [[2768409, _unix("2013-11-01")], [7679610, _unix("2014-01-02")]]}
    points = _sources(tmp_path, observations=observations)
    rows = points.build(points.gather(), TODAY)
    assert rows == [
        (0, "2013-08-14"),
        (2768409, "2013-11-01"),
        (7679610, "2013-12-31"),
        (7679610, "2014-01-02"),
    ]


def test_a_constraint_never_becomes_a_point(tmp_path: Path) -> None:
    constraints = {"seen": [[9_000_000_000, _unix("2026-10-01")]]}
    points = _sources(tmp_path, constraints=constraints)
    assert 9_000_000_000 not in {uid for uid, _ in points.build(points.gather(), TODAY)}


def test_the_rows_are_in_date_order_then_id_order(tmp_path: Path) -> None:
    observations = {"a": [[5, _unix("2013-11-01")], [3, _unix("2013-11-01")]]}
    points = _sources(tmp_path, observations=observations)
    days = [(day, uid) for uid, day in points.build(points.gather(), TODAY)]
    assert days == sorted(days)


@pytest.mark.parametrize("day", ["2013-08-13", "2026-11-02"])
def test_a_point_outside_telegrams_lifetime_stops_the_build(tmp_path: Path, day: str) -> None:
    points = _sources(tmp_path, base=[*BASE, [1, day]])
    with pytest.raises(SystemExit, match="outside"):
        points.build(points.gather(), TODAY)


# --- the report -------------------------------------------------------------


def test_the_report_counts_every_source_and_what_the_merge_did(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    observations = {"a": [[2768409, _unix("2013-11-01")], [7679610, _unix("2014-01-02")]]}
    points = _sources(tmp_path, observations=observations)
    _out(points).write_text(json.dumps([[0, "2013-08-14"], [1, "2013-09-01"]]), encoding="utf-8")
    gathered = points.gather()
    points.report(gathered, points.build(gathered, TODAY), TODAY)

    printed = capsys.readouterr().out
    assert "wizardloop: 3 points" in printed
    assert "lyadminbot/a: 2 points" in printed
    assert "1 exact duplicates dropped" in printed
    assert "1 ids dated differently by two sources, both kept: 7679610" in printed
    assert "against the current file: +3 -1" in printed


def test_the_report_warns_once_the_newest_point_is_stale(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    points = _sources(tmp_path)
    gathered = points.gather()
    rows = points.build(gathered, TODAY)

    fresh = date(2014, 1, 1)
    points.report(gathered, rows, fresh)
    assert "warning" not in capsys.readouterr().out

    points.report(gathered, rows, TODAY)
    printed = capsys.readouterr().out
    assert "newest point 2013-12-31" in printed
    assert "warning: no point is newer than 180 days" in printed


def test_the_report_has_nothing_to_compare_without_a_current_file(tmp_path: Path) -> None:
    assert _sources(tmp_path).previous() == set()


# --- the output -------------------------------------------------------------


def test_the_output_keeps_the_files_one_point_per_line_layout(tmp_path: Path) -> None:
    points = _sources(tmp_path)
    points.run(TODAY)
    assert _out(points).read_bytes() == (
        b'[\n  [0, "2013-08-14"],\n  [2768409, "2013-11-01"],\n  [7679610, "2013-12-31"]\n]\n'
    )


def test_a_rebuild_from_the_same_cache_is_byte_identical(tmp_path: Path) -> None:
    observations = {"a": [[9, _unix("2020-01-01")]], "b": [[8, _unix("2019-01-01")]]}
    points = _sources(tmp_path, observations=observations)
    points.run(TODAY)
    first = _out(points).read_bytes()
    points.run(TODAY)
    assert _out(points).read_bytes() == first


def test_a_build_that_stops_writes_nothing(tmp_path: Path) -> None:
    points = _sources(tmp_path, base=[*BASE, [1, "2099-01-01"]])
    with pytest.raises(SystemExit):
        points.run(TODAY)
    assert list(points.data_dir.iterdir()) == []


# --- the command line -------------------------------------------------------


def test_the_cli_exits_0_when_the_points_are_written(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[date] = []
    monkeypatch.setattr(_cli.Points, "run", lambda _self, today: ran.append(today))
    assert _cli.main([]) == 0
    assert ran == [date.today()]


def test_the_cli_exits_1_and_says_why_when_it_cannot_build(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def stop(_self: Points, _today: date) -> NoReturn:
        msg = "the source did not answer\nretry later"
        raise SystemExit(msg)

    monkeypatch.setattr(_cli.Points, "run", stop)
    assert _cli.main(["--offline"]) == 1
    printed = capsys.readouterr().out
    assert "not built: the source did not answer\n  retry later" in printed
    assert "the data was left as it was" in printed
