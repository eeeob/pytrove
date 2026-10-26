from __future__ import annotations as _annotations

import json
import subprocess
import sys
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from pytrove.device_tools._internal import catalog
from pytrove.device_tools._internal.catalog import _Catalog, _Device, _OsView

if TYPE_CHECKING:
    from pathlib import Path

LAZY_PROBE = """
import pytrove
from pytrove.device_tools.draw import _DEVICES
from pytrove.enums import PlatformDevice
ios = pytrove.get_device_catalog(PlatformDevice.IOS)
android = pytrove.get_device_catalog(PlatformDevice.ANDROID)
assert not any("_data" in c.__dict__ for c in _DEVICES.values())
pytrove.random_device(PlatformDevice.IOS, unique_id="probe")
assert "_data" in ios.__dict__ and "_data" not in android.__dict__
android.oses()
assert "_data" in android.__dict__
"""

TODAY = date(2026, 1, 1)


def test_bundled_catalogs_are_read_on_first_use_and_not_at_import() -> None:
    subprocess.run([sys.executable, "-c", LAZY_PROBE], check=True)


def _write(directory: Path, platform: str, **data: Any) -> None:
    """Write a catalog file for `platform` into `directory`, schema 1 unless given."""
    data.setdefault("schema", catalog._SCHEMA)
    (directory / f"{platform}.json").write_text(json.dumps(data), encoding="utf-8")


def _resolve(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **data: Any) -> _Catalog:
    """Resolve a catalog written to `tmp_path` instead of a bundled one."""
    monkeypatch.setattr(catalog, "DEVICE_CATALOGS_DIR", tmp_path)
    _write(tmp_path, "fake", **data)
    return catalog._build_catalog("fake")


# --- constants -------------------------------------------------------------


def test_constants() -> None:
    assert catalog._SCHEMA == 1
    assert catalog._HALF_LIFE_DAYS == 730.0
    assert catalog._MIN_WEIGHT == 1e-4
    assert all(share > 0 for share in catalog.GROUP_SHARES.values())
    assert set(catalog.OS_SHARES) == {"windows", "linux"}


# --- _age_weight -----------------------------------------------------------


@pytest.mark.parametrize("released", [None, "", "not a date", "2024-13-40"])
def test_age_weight_of_an_unknown_or_unreadable_date_is_one(released: str | None) -> None:
    assert catalog._age_weight(released, TODAY) == 1.0


def test_age_weight_halves_every_half_life() -> None:
    one = (TODAY - timedelta(days=730)).isoformat()
    two = (TODAY - timedelta(days=1460)).isoformat()

    assert catalog._age_weight(TODAY.isoformat(), TODAY) == 1.0
    assert catalog._age_weight(one, TODAY) == pytest.approx(0.5)
    assert catalog._age_weight(two, TODAY) == pytest.approx(0.25)


def test_age_weight_reads_only_the_date_part() -> None:
    assert catalog._age_weight(f"{TODAY.isoformat()}T12:00:00Z", TODAY) == 1.0


def test_age_weight_of_a_future_date_is_one() -> None:
    assert catalog._age_weight("2030-01-01", TODAY) == 1.0


def test_age_weight_never_falls_below_the_floor() -> None:
    assert catalog._age_weight("1900-01-01", TODAY) == catalog._MIN_WEIGHT


# --- _load -----------------------------------------------------------------


def test_load_reads_a_bundled_catalog() -> None:
    assert catalog._load("ios")["platform"] == "ios"


def test_load_refuses_a_missing_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(catalog, "DEVICE_CATALOGS_DIR", tmp_path)

    with pytest.raises(FileNotFoundError, match="no device catalog for 'nope'"):
        catalog._load("nope")


@pytest.mark.parametrize("schema", [None, 0, 2, "1"])
def test_load_refuses_another_schema(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, schema: object
) -> None:
    monkeypatch.setattr(catalog, "DEVICE_CATALOGS_DIR", tmp_path)
    _write(tmp_path, "old", schema=schema, devices=[], versions=[])

    with pytest.raises(ValueError, match="unsupported schema"):
        catalog._load("old")


# --- _build_catalog --------------------------------------------------------


def test_build_catalog_builds_a_fresh_catalog_each_call() -> None:
    first = catalog._build_catalog("ios")

    assert first is not catalog._build_catalog("ios")
    assert first == catalog._build_catalog("ios")


def test_catalog_offers_explicit_versions_else_every_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    resolved = _resolve(
        monkeypatch,
        tmp_path,
        updated="2026-01-01",
        versions=[{"version": "1"}, {"version": "2"}],
        devices=[{"model": "A", "versions": ["2"]}, {"model": "B"}],
    )

    assert resolved.platform == "fake"
    assert resolved.updated == "2026-01-01"
    assert [(d.model, d.versions) for d in resolved.devices] == [("A", ("2",)), ("B", ("1", "2"))]
    assert resolved.oses == () and resolved.by_os == {}
    assert all(d.oses == () and d.by_os == {} for d in resolved.devices)


def test_catalog_without_an_update_date_reads_as_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    resolved = _resolve(
        monkeypatch, tmp_path, versions=[{"version": "1"}], devices=[{"model": "A"}]
    )

    assert resolved.updated == ""


def test_catalog_offers_a_device_the_versions_of_the_oses_it_reports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    resolved = _resolve(
        monkeypatch,
        tmp_path,
        versions=[{"version": "W", "os": "windows"}, {"version": "L", "os": "linux"}],
        devices=[{"model": "PC", "os": ["windows", "linux"]}, {"model": "Box", "os": ["linux"]}],
    )
    pc, box = resolved.devices

    assert pc.versions == ("W", "L") and pc.oses == ("linux", "windows")
    assert box.versions == ("L",) and set(box.by_os) == {"linux"}
    assert resolved.oses == ("windows", "linux")
    assert resolved.by_os["windows"] == _OsView((pc,), (pc.weight,))
    assert resolved.by_os["linux"].devices == (pc, box)


def test_catalog_keeps_a_version_without_an_os_out_of_the_os_views(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    resolved = _resolve(
        monkeypatch,
        tmp_path,
        versions=[{"version": "W", "os": "windows"}, {"version": "X"}],
        devices=[{"model": "PC", "versions": ["W", "X"]}],
    )
    (pc,) = resolved.devices

    assert pc.versions == ("W", "X")
    assert pc.by_os == {"windows": (("W",), (1.0,))}
    assert pc.oses == ("windows",)


def test_catalog_skips_a_device_with_no_version_to_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    resolved = _resolve(
        monkeypatch,
        tmp_path,
        versions=[{"version": "W", "os": "windows"}],
        devices=[{"model": "Mac", "os": ["macos"]}, {"model": "PC", "os": ["windows"]}],
    )

    assert [d.model for d in resolved.devices] == ["PC"]


def test_catalog_with_no_usable_device_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="fake.json lists no usable devices"):
        _resolve(
            monkeypatch,
            tmp_path,
            versions=[{"version": "W", "os": "windows"}],
            devices=[{"model": "Mac", "os": ["macos"]}],
        )


def test_catalog_uses_explicit_weights_raised_to_the_floor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    resolved = _resolve(
        monkeypatch,
        tmp_path,
        versions=[{"version": "1", "weight": 3}, {"version": "2", "weight": 0}],
        devices=[{"model": "A", "weight": 5}, {"model": "B", "weight": 0}],
    )

    assert resolved.weights == (5.0, catalog._MIN_WEIGHT)
    assert resolved.devices[0].version_weights == (3.0, 0.0)


def test_catalog_splits_a_group_share_by_recency(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    today = date.today()
    old = (today - timedelta(days=730)).isoformat()
    monkeypatch.setitem(catalog.GROUP_SHARES, "acme", 30.0)
    resolved = _resolve(
        monkeypatch,
        tmp_path,
        versions=[
            {"version": "1", "released": today.isoformat()},
            {"version": "0", "released": old},
        ],
        devices=[
            {"model": "New", "brand": "acme", "released": today.isoformat()},
            {"model": "Old", "vendor": "acme", "released": old},
            {"model": "Loner", "brand": "unlisted"},
        ],
    )

    new, aged, loner = resolved.weights
    assert new + aged == pytest.approx(30.0)
    assert new == pytest.approx(2 * aged)
    # A group missing from `GROUP_SHARES` gets a share of 1.0.
    assert loner == pytest.approx(1.0)
    assert resolved.devices[0].version_weights == pytest.approx((1.0, 0.5))


def test_catalog_version_count_counts_distinct_versions() -> None:
    device_a = _Device("A", ("1", "2"), (1.0, 1.0), 1.0)
    device_b = _Device("B", ("2", "3"), (1.0, 1.0), 1.0)

    assert _Catalog("p", "", (device_a, device_b), (1.0, 1.0)).version_count() == 3
    assert _Catalog("p", "", (), ()).version_count() == 0
