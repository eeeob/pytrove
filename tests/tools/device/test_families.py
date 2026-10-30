from __future__ import annotations as _annotations

import collections
import dataclasses
import json
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, cast

import pytest

from pytrove.enums import PlatformDevice
from pytrove.models import DeviceInfo
from pytrove.device_tools._internal import catalog as catalog_module
from pytrove.device_tools._internal.catalog import _build_catalog, _load, GROUP_SHARES, OS_SHARES
from pytrove.device_tools._internal.rng import _rng
from pytrove.device_tools.draw import get_device_catalog
from pytrove.device_tools.families import DeviceCatalog, random_family

if TYPE_CHECKING:
    from pathlib import Path

DESKTOP = get_device_catalog(PlatformDevice.DESKTOP)
ANDROID = get_device_catalog(PlatformDevice.ANDROID)
IOS = get_device_catalog(PlatformDevice.IOS)
WEB = get_device_catalog(PlatformDevice.WEB)

ALL_PLATFORMS = (DESKTOP, ANDROID, IOS, WEB)
IDS = [p.platform.value for p in ALL_PLATFORMS]

#: Telegram reports every desktop OS as "desktop"; macOS is deliberately not in the catalog.
DESKTOP_OSES = ("windows", "linux")


@pytest.fixture(scope="module", params=ALL_PLATFORMS, ids=IDS)
def platform(request: pytest.FixtureRequest) -> DeviceCatalog:
    return request.param


def _fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **data: Any) -> DeviceCatalog:
    """Return a fresh catalog whose data is `data`, written to `tmp_path` as `fake.json`."""
    monkeypatch.setattr(catalog_module, "DEVICE_CATALOGS_DIR", tmp_path)
    data.setdefault("schema", catalog_module._SCHEMA)
    (tmp_path / "fake.json").write_text(json.dumps(data), encoding="utf-8")
    return DeviceCatalog(cast("PlatformDevice", "fake"))


# --- sampling --------------------------------------------------------------


def test_random_device_only_returns_pairs_the_catalog_allows(platform: DeviceCatalog) -> None:
    allowed = {(d.model, v) for d in platform._data.devices for v in d.versions}

    for _ in range(200):
        device = platform.random_device()
        assert device.to_tuple() in allowed


def test_same_unique_id_gives_the_same_device(platform: DeviceCatalog) -> None:
    assert platform.random_device("user-42") == platform.random_device("user-42")


def test_different_unique_ids_spread_across_devices(platform: DeviceCatalog) -> None:
    drawn = {platform.random_device(f"user-{i}").device_model for i in range(60)}
    assert len(drawn) > 1


def test_random_device_without_an_id_varies(platform: DeviceCatalog) -> None:
    drawn = {platform.random_device() for _ in range(80)}
    assert len(drawn) > 1


@pytest.mark.parametrize("os", DESKTOP_OSES)
def test_pinning_an_os_only_draws_that_os(os: str) -> None:
    allowed = {(d.model, v) for d in DESKTOP._data.by_os[os].devices for v in d.by_os[os][0]}

    for i in range(120):
        device = DESKTOP.random_device(f"pin-{i}", os=os)
        assert device.to_tuple() in allowed


def test_pinning_an_os_is_deterministic() -> None:
    assert DESKTOP.random_device("abc", os="linux") == DESKTOP.random_device("abc", os="linux")


def test_pinning_an_unknown_os_raises() -> None:
    with pytest.raises(ValueError, match="no 'haiku' devices"):
        DESKTOP.random_device(os="haiku")

    with pytest.raises(ValueError, match="no 'windows' devices"):
        ANDROID.random_device(os="windows")


def test_desktop_draws_follow_the_os_shares() -> None:
    os_of = {v["version"]: v["os"] for v in _load("desktop")["versions"]}
    picks = collections.Counter(os_of[DESKTOP.random_device().system_version] for _ in range(4000))
    total = sum(OS_SHARES.values())

    for name, share in OS_SHARES.items():
        assert abs(picks[name] / 4000 - share / total) < 0.05, (name, picks)


def test_os_shares_apply_on_the_next_draw(monkeypatch: pytest.MonkeyPatch) -> None:
    DESKTOP.oses()  # already loaded: `OS_SHARES` is still read per draw
    monkeypatch.setitem(OS_SHARES, "linux", 0.0)
    linux = set(DESKTOP.versions(os="linux"))

    assert not any(DESKTOP.random_device(f"os-{i}").system_version in linux for i in range(300))


def test_an_os_missing_from_os_shares_weighs_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(OS_SHARES, "windows", 3.0)
    fake = _fake(
        monkeypatch,
        tmp_path,
        versions=[{"version": "W", "os": "windows"}, {"version": "B", "os": "beos"}],
        devices=[{"model": "PC", "os": ["windows", "beos"]}],
    )
    picks = collections.Counter(fake.random_device(f"b-{i}").system_version for i in range(4000))

    assert abs(picks["B"] / 4000 - 0.25) < 0.03, picks


def test_newer_releases_are_drawn_by_their_recency_weight(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    today = date.today()
    fake = _fake(
        monkeypatch,
        tmp_path,
        versions=[
            {"version": "new", "released": today.isoformat()},
            {"version": "old", "released": (today - timedelta(days=730)).isoformat()},
        ],
        devices=[{"model": "A"}],
    )
    picks = collections.Counter(fake.random_device(f"r-{i}").system_version for i in range(3000))

    # Weights 1.0 and 0.5: two thirds new.
    assert abs(picks["new"] / 3000 - 2 / 3) < 0.03, picks


def test_device_and_version_weights_drive_the_draw(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _fake(
        monkeypatch,
        tmp_path,
        versions=[{"version": "rare", "weight": 1}, {"version": "common", "weight": 1e9}],
        devices=[{"model": "Rare", "weight": 1}, {"model": "Common", "weight": 1e9}],
    )

    assert {fake.random_device(f"w-{i}") for i in range(200)} == {DeviceInfo("Common", "common")}


def test_os_view_weights_drive_an_os_pinned_draw(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _fake(
        monkeypatch,
        tmp_path,
        versions=[{"version": "W", "os": "windows"}, {"version": "L", "os": "linux"}],
        devices=[
            {"model": "Rare", "os": ["windows"], "weight": 1},
            {"model": "Common", "os": ["windows", "linux"], "weight": 1e9},
        ],
    )

    assert {fake.random_device(f"v-{i}", os="windows") for i in range(200)} == {
        DeviceInfo("Common", "W")
    }


def test_group_shares_apply_when_a_catalog_is_first_built(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data: dict[str, Any] = {
        "versions": [{"version": "1"}],
        "devices": [{"model": "A", "brand": "acme"}, {"model": "B", "brand": "zeta"}],
    }
    monkeypatch.setitem(GROUP_SHARES, "acme", 3.0)
    monkeypatch.setitem(GROUP_SHARES, "zeta", 1.0)
    loaded = _fake(monkeypatch, tmp_path, **data)

    assert loaded._data.weights == (3.0, 1.0)

    monkeypatch.setitem(GROUP_SHARES, "acme", 9.0)

    # The loaded catalog keeps what it built; a fresh one reads the new share.
    assert loaded._data.weights == (3.0, 1.0)
    assert _fake(monkeypatch, tmp_path, **data)._data.weights == (9.0, 1.0)


def test_random_family_is_weighted_towards_mobile() -> None:
    picks = collections.Counter(random_family(ALL_PLATFORMS).platform for _ in range(3000))

    assert picks["android"] > picks["desktop"] > picks["ios"] / 2
    assert set(picks) == {p.platform for p in ALL_PLATFORMS}


def test_random_family_is_deterministic_with_a_unique_id() -> None:
    assert random_family(ALL_PLATFORMS, "abc") is random_family(ALL_PLATFORMS, "abc")


def test_random_family_follows_each_catalogs_weight() -> None:
    never = DeviceCatalog(PlatformDevice.IOS, 0.0)
    always = DeviceCatalog(PlatformDevice.WEB, 1.0)

    assert all(random_family([never, always], f"w-{i}") is always for i in range(50))


def test_random_family_pick_is_pinned_per_unique_id() -> None:
    # Golden values: a change here reassigns stored accounts to other platforms.
    picks = [random_family(ALL_PLATFORMS, f"g-{i}").platform.value for i in range(4)]

    assert picks == ["desktop", "android", "android", "android"]


def test_random_family_accepts_any_iterable_once() -> None:
    assert random_family(c for c in (IOS,)) is IOS


@pytest.mark.parametrize(
    "catalogs",
    [[], [DeviceCatalog(PlatformDevice.IOS, 0.0), DeviceCatalog(PlatformDevice.WEB, 0.0)]],
    ids=["empty", "all-zero"],
)
def test_random_family_refuses_catalogs_with_no_positive_weight(
    catalogs: list[DeviceCatalog],
) -> None:
    with pytest.raises(ValueError, match="at least one catalog with a positive weight"):
        random_family(catalogs)


# --- lookup and types ------------------------------------------------------


def test_find_device_matches_model_and_optional_version() -> None:
    device = ANDROID._data.devices[0]

    assert ANDROID.find_device(device.model) == DeviceInfo(device.model, device.versions[0])
    assert ANDROID.find_device(device.model, device.versions[0]) == DeviceInfo(
        device.model, device.versions[0]
    )
    assert ANDROID.find_device(device.model, "SDK 1") is None
    assert ANDROID.find_device("no such model") is None
    assert ANDROID.find_device(
        device_model=device.model, system_version=device.versions[-1]
    ) == DeviceInfo(device.model, device.versions[-1])


def test_models_and_versions_narrow_to_one_os() -> None:
    # Windows draws only the shared pool, Linux adds its own boards on top.
    assert set(DESKTOP.models(os="windows")) < set(DESKTOP.models())
    assert set(DESKTOP.versions(os="windows")).isdisjoint(DESKTOP.versions(os="linux"))
    assert sum(len(DESKTOP.versions(os=os)) for os in DESKTOP_OSES) == len(DESKTOP.versions())


def test_models_and_versions_keep_catalog_order_and_drop_repeats(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _fake(
        monkeypatch,
        tmp_path,
        versions=[{"version": "1"}, {"version": "2"}, {"version": "3"}],
        devices=[
            {"model": "Z", "versions": ["3", "1"]},
            {"model": "A", "versions": ["1", "2"]},
        ],
    )

    assert fake.models() == ("Z", "A")
    assert fake.versions() == ("3", "1", "2")
    assert fake.devices() == (
        DeviceInfo("Z", "3"),
        DeviceInfo("Z", "1"),
        DeviceInfo("A", "1"),
        DeviceInfo("A", "2"),
    )


def test_single_os_platform_reports_no_oses() -> None:
    assert ANDROID.oses() == ()
    assert IOS.oses() == ()
    assert DESKTOP.oses() == DESKTOP_OSES


def test_unknown_platform_raises_on_first_use() -> None:
    nope = DeviceCatalog(cast("PlatformDevice", "nope"))

    with pytest.raises(FileNotFoundError):
        nope.random_device()

    with pytest.raises(FileNotFoundError):
        nope.oses()


# --- the object ------------------------------------------------------------


def test_catalog_fields_and_default_weight() -> None:
    catalog = DeviceCatalog(PlatformDevice.WEB)

    assert catalog.platform is PlatformDevice.WEB
    assert catalog.weight == 1.0
    assert DeviceCatalog(PlatformDevice.WEB, 5.0).weight == 5.0


@pytest.mark.parametrize("weight", [-1.0, float("nan"), float("inf"), float("-inf")])
def test_catalog_refuses_a_weight_no_draw_can_use(weight: float) -> None:
    with pytest.raises(ValueError, match="finite and not negative"):
        DeviceCatalog(PlatformDevice.WEB, weight)


def test_catalog_accepts_a_zero_weight() -> None:
    assert DeviceCatalog(PlatformDevice.WEB, 0.0).weight == 0.0


def test_catalog_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        DeviceCatalog(PlatformDevice.WEB).weight = 2.0


def test_catalog_compares_by_its_fields_not_its_loaded_data() -> None:
    IOS.oses()  # loads `_data` on the shared instance
    fresh = DeviceCatalog(PlatformDevice.IOS, IOS.weight)

    assert fresh == IOS
    assert hash(fresh) == hash(IOS)
    assert fresh != DeviceCatalog(PlatformDevice.IOS, IOS.weight + 1)


def test_catalog_data_is_built_on_first_use_and_kept_on_the_instance() -> None:
    catalog = DeviceCatalog(PlatformDevice.IOS)
    assert "_data" not in catalog.__dict__

    data = catalog._data

    assert catalog.__dict__["_data"] is data
    assert catalog._data is data
    assert data == _build_catalog("ios")


def test_os_is_keyword_only_on_the_listings() -> None:
    for listing in (DESKTOP.devices, DESKTOP.models, DESKTOP.versions):
        with pytest.raises(TypeError):
            listing("linux")


def test_devices_lists_every_model_and_version_pair(platform: DeviceCatalog) -> None:
    pairs = platform.devices()

    assert pairs == tuple(
        DeviceInfo(d.model, v) for d in platform._data.devices for v in d.versions
    )
    assert all(isinstance(pair, DeviceInfo) for pair in pairs)


@pytest.mark.parametrize("os", DESKTOP_OSES)
def test_devices_narrowed_to_one_os_only_pairs_its_versions(os: str) -> None:
    pairs = DESKTOP.devices(os=os)

    assert pairs and set(pairs) <= set(DESKTOP.devices())
    assert {pair.system_version for pair in pairs} == set(DESKTOP.versions(os=os))


def test_listing_an_unknown_os_raises() -> None:
    with pytest.raises(ValueError, match="desktop has no 'haiku' devices"):
        DESKTOP.devices(os="haiku")

    with pytest.raises(ValueError, match=r"android has no 'linux' devices; known: \(\)"):
        ANDROID.models(os="linux")

    with pytest.raises(ValueError, match="no 'haiku' devices"):
        DESKTOP.versions(os="haiku")


@pytest.mark.parametrize("catalog", [DESKTOP, ANDROID], ids=["desktop", "android"])
def test_an_empty_os_is_an_unknown_os(catalog: DeviceCatalog) -> None:
    for call in (catalog.devices, catalog.models, catalog.versions):
        with pytest.raises(ValueError, match="has no '' devices"):
            call(os="")

    with pytest.raises(ValueError, match="has no '' devices"):
        catalog.random_device("x", os="")


def test_view_returns_the_os_view_or_raises() -> None:
    assert DESKTOP._view("linux") is DESKTOP._data.by_os["linux"]

    for os in ("haiku", ""):
        with pytest.raises(ValueError, match="has no"):
            DESKTOP._view(os)


def test_devices_for_returns_every_device_or_one_os_view() -> None:
    assert DESKTOP._devices_for(None) is DESKTOP._data.devices
    assert DESKTOP._devices_for("linux") == DESKTOP._data.by_os["linux"].devices


def test_draw_continues_the_stream_it_is_given() -> None:
    assert DESKTOP._draw(_rng("x"), None) == DESKTOP.random_device("x")

    advanced, twin = _rng("x"), _rng("x")
    advanced.random()
    twin.random()
    assert DESKTOP._draw(advanced, None) == DESKTOP._draw(twin, None)

    # A draw that restarted the stream would match the fresh draw for every id.
    shifted = []
    for i in range(20):
        rng = _rng(f"d-{i}")
        rng.random()
        shifted.append(DESKTOP._draw(rng, None) != DESKTOP.random_device(f"d-{i}"))
    assert any(shifted)


def test_draw_refuses_an_os_the_platform_lacks() -> None:
    with pytest.raises(ValueError, match="has no 'linux' devices"):
        IOS._draw(_rng("x"), "linux")
