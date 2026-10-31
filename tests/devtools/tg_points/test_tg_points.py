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
from devtools.tg_points.src.blocks import Blocks  # noqa: E402
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
    blocks: object = (),
    ssleg: str | None = None,
) -> Points:
    """A `Points` reading the given sources offline and writing into `tmp_path / "data"`."""
    cache_dir, data_dir = tmp_path / "cache", tmp_path / "data"
    cache_dir.mkdir()
    data_dir.mkdir()
    (cache_dir / Points.WIZARDLOOP_FILE).write_text(json.dumps(base), encoding="utf-8")
    payload = {
        "observations": {"k": []} if observations is None else observations,
        "constraints": constraints or {},
        "randomizedBlocks": blocks,
    }
    (cache_dir / Points.LYADMINBOT_FILE).write_text(json.dumps(payload), encoding="utf-8")
    if ssleg is not None:
        (cache_dir / Blocks.SSLEG_FILE).write_text(ssleg, encoding="utf-8")
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
    assert points.groups("observations") == {"k": [(8_800_000_000, "2026-03-01")]}


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
        points.groups("observations")


@pytest.mark.parametrize("base", [{"not": "a list"}, "text"])
def test_a_base_that_is_not_a_list_stops_the_build(tmp_path: Path, base: object) -> None:
    with pytest.raises(SystemExit, match="expected a list"):
        _sources(tmp_path, base=base).base()


def test_observations_must_be_an_object_of_lists(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="expected a list"):
        _sources(tmp_path, observations={"k": {"not": "a list"}}).groups("observations")

    (tmp_path / "again").mkdir()
    with pytest.raises(SystemExit, match="no `observations`"):
        _sources(tmp_path / "again", observations=[]).groups("observations")


@pytest.mark.parametrize("payload", ["[]", '"text"', "1"])
def test_a_lyadminbot_file_that_is_not_an_object_stops_the_build(
    tmp_path: Path, payload: str
) -> None:
    points = _sources(tmp_path)
    (points.cache.directory / Points.LYADMINBOT_FILE).write_text(payload, encoding="utf-8")
    with pytest.raises(SystemExit, match="expected a JSON object"):
        points.groups("observations")


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
    points.write(points.collect(TODAY))
    assert _out(points).read_bytes() == (
        b'[\n  [0, "2013-08-14"],\n  [2768409, "2013-11-01"],\n  [7679610, "2013-12-31"]\n]\n'
    )


def test_a_rebuild_from_the_same_cache_is_byte_identical(tmp_path: Path) -> None:
    observations = {"a": [[9, _unix("2020-01-01")]], "b": [[8, _unix("2019-01-01")]]}
    points = _sources(tmp_path, observations=observations)
    points.write(points.collect(TODAY))
    first = _out(points).read_bytes()
    points.write(points.collect(TODAY))
    assert _out(points).read_bytes() == first


# --- the blocks -------------------------------------------------------------

#: Two back-to-back blocks and the rows that date them: 120 is the earliest
#: row in the first (a constraint), 250 the only row in the second.
BLOCKS = [[100, 200], [200, 300]]
OBSERVED = {"o": [[150, _unix("2024-03-01")]]}
SEEN = {"c": [[120, _unix("2024-02-20")], [250, _unix("2024-06-01")]]}
POOLS = """\
import datetime
uid_dict = {200: (date(2024, 2, 23), date(2024, 5, 31)),
            300: (date(2024, 6, 25), date(2024, 9, 1))}
"""


def _blocks(
    tmp_path: Path,
    *,
    observations: object = OBSERVED,
    constraints: object = SEEN,
    blocks: object = BLOCKS,
    ssleg: str | None = None,
) -> Blocks:
    """A `Blocks` over `_sources`, dated by `OBSERVED` and `SEEN` unless told otherwise."""
    points = _sources(
        tmp_path, observations=observations, constraints=constraints, blocks=blocks, ssleg=ssleg
    )
    return Blocks(points)


def test_a_block_opens_on_the_earliest_observation_or_constraint_inside_it(
    tmp_path: Path,
) -> None:
    assert _blocks(tmp_path).build(TODAY) == [(100, 200, "2024-02-20"), (200, 300, "2024-06-01")]


@pytest.mark.parametrize(
    ("blocks", "why"),
    [
        ([], "non-empty list"),
        ([[100]], "malformed range"),
        ([[200, 100]], "malformed range"),
        ([[True, 200]], "malformed range"),
        ([[0, True], [1, 300]], "malformed range"),
        ([[100, 200], [250, 300]], "not back to back"),
        ([[100, 200], [200, 300], [300, 400]], "holds no observation or constraint"),
    ],
)
def test_blocks_that_cannot_be_dated_stop_the_build(
    tmp_path: Path, blocks: object, why: str
) -> None:
    with pytest.raises(SystemExit, match=why):
        _blocks(tmp_path, blocks=blocks).build(TODAY)


def test_openings_that_do_not_move_forward_stop_the_build(tmp_path: Path) -> None:
    seen = {"c": [[120, _unix("2024-06-01")], [250, _unix("2024-02-20")]]}
    with pytest.raises(SystemExit, match="not after the block before it"):
        _blocks(tmp_path, observations={"o": []}, constraints=seen).build(TODAY)


def test_an_opening_outside_telegrams_lifetime_stops_the_build(tmp_path: Path) -> None:
    seen = {"c": [[120, _unix("2099-01-01")], [250, _unix("2099-02-01")]]}
    with pytest.raises(SystemExit, match="outside Telegram's lifetime"):
        _blocks(tmp_path, observations={"o": []}, constraints=seen).build(TODAY)


def test_sslegs_pools_are_read_as_highest_id_and_first_day(tmp_path: Path) -> None:
    assert _blocks(tmp_path, ssleg=POOLS).pools() == {200: "2024-02-23", 300: "2024-06-25"}


def test_sslegs_file_is_parsed_and_never_run(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    hostile = f"open({str(marker)!r}, 'w').close()\n{POOLS}"
    assert _blocks(tmp_path, ssleg=hostile).pools() == {200: "2024-02-23", 300: "2024-06-25"}
    assert not marker.exists()


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("uid_dict = {200: (__import__('os').getcwd(), date(2024, 1, 1))}", "is not \\(date"),
        ("uid_dict = {'200': (date(2024, 1, 1), date(2024, 1, 2))}", "not an int literal"),
        ("uid_dict = {200: (date(2024, 2, 30), date(2024, 3, 1))}", "is not \\(date"),
        ("uid_dict = {**other}", "not an int literal"),
        ("pools = {}", "no `uid_dict"),
        ("uid_dict = {", "is not Python"),
        # a literal too large for C: OverflowError, not ValueError
        (
            "uid_dict = {200: (date(2024, 1, 99999999999999999999), date(2024, 1, 2))}",
            "is not \\(date",
        ),
    ],
)
def test_a_pool_table_of_any_other_shape_is_refused(tmp_path: Path, text: str, why: str) -> None:
    with pytest.raises(SystemExit, match=why):
        _blocks(tmp_path, ssleg=text).pools()


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(POOLS.encode("utf-8") + b"\xff", id="not-utf8"),
        pytest.param(POOLS.encode("utf-8") + b"\x00", id="nul-byte"),  # ValueError on 3.10/3.11
        pytest.param(b"x = " + b"(" * 100_000 + b")" * 100_000, id="nested-too-deep"),
    ],
)
def test_a_pool_file_that_cannot_be_parsed_stops_only_the_read(tmp_path: Path, raw: bytes) -> None:
    blocks = _blocks(tmp_path, ssleg="")
    (blocks.points.cache.directory / Blocks.SSLEG_FILE).write_bytes(raw)
    with pytest.raises(SystemExit, match="is not Python"):
        blocks.pools()


def test_the_cross_check_prints_each_opening_beside_its_pool(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocks = _blocks(tmp_path, ssleg=POOLS)
    blocks.cross_check(
        [(100, 200, "2024-02-20"), (200, 300, "2024-06-01"), (300, 400, "2024-10-01")]
    )

    printed = capsys.readouterr().out
    assert "opened 2024-02-20  ssleg 2024-02-23 (+3d)\n" in printed
    assert "opened 2024-06-01  ssleg 2024-06-25 (+24d)  !" in printed
    assert "opened 2024-10-01  ssleg: no pool" in printed


def test_the_cross_check_is_skipped_not_fatal_without_ssleg(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _blocks(tmp_path).cross_check([(100, 200, "2024-02-20")])
    assert "ssleg cross-check skipped: --offline but" in capsys.readouterr().out


def test_a_broken_pool_file_costs_the_cross_check_and_not_the_build(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    points = _blocks(tmp_path, ssleg="").points
    (points.cache.directory / Blocks.SSLEG_FILE).write_bytes(b"\xff")
    _cli.build(points.cache, TODAY, points.data_dir)

    assert "ssleg cross-check skipped" in capsys.readouterr().out
    assert sorted(p.name for p in points.data_dir.iterdir()) == [Blocks.OUT_FILE, Points.OUT_FILE]


def test_the_blocks_are_written_one_per_line_in_id_order(tmp_path: Path) -> None:
    blocks = _blocks(tmp_path, ssleg=POOLS)
    blocks.write(blocks.collect(TODAY))
    assert (blocks.points.data_dir / Blocks.OUT_FILE).read_bytes() == (
        b'[\n  [100, 200, "2024-02-20"],\n  [200, 300, "2024-06-01"]\n]\n'
    )


# --- the command line -------------------------------------------------------


def test_a_build_writes_both_files_or_neither(tmp_path: Path) -> None:
    (tmp_path / "good").mkdir()
    good = _blocks(tmp_path / "good", ssleg=POOLS).points
    _cli.build(good.cache, TODAY, good.data_dir)
    assert sorted(p.name for p in good.data_dir.iterdir()) == [Blocks.OUT_FILE, Points.OUT_FILE]

    # The points are fine and only the blocks fail: still nothing is written.
    (tmp_path / "bad").mkdir()
    bad = _blocks(tmp_path / "bad", blocks=[[100, 200], [250, 300]]).points
    with pytest.raises(SystemExit, match="not back to back"):
        _cli.build(bad.cache, TODAY, bad.data_dir)
    assert list(bad.data_dir.iterdir()) == []


def test_the_cli_exits_0_when_the_data_is_written(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[date] = []
    monkeypatch.setattr(_cli, "build", lambda _cache, today: ran.append(today))
    assert _cli.main([]) == 0
    assert ran == [date.today()]


def test_the_cli_exits_1_and_says_why_when_it_cannot_build(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def stop(_cache: Cache, _today: date) -> NoReturn:
        msg = "the source did not answer\nretry later"
        raise SystemExit(msg)

    monkeypatch.setattr(_cli, "build", stop)
    assert _cli.main(["--offline"]) == 1
    printed = capsys.readouterr().out
    assert "not built: the source did not answer\n  retry later" in printed
    assert "the data was left as it was" in printed
