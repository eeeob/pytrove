from __future__ import annotations as _annotations

import collections
import dataclasses
from typing import cast

import pytest

from pytrove.enums import PlatformDevice
from pytrove.models import DeviceInfo
from pytrove.device_tools._internal.catalog import _build_catalog, _load, OS_SHARES
from pytrove.device_tools.draw import get_device_catalog
from pytrove.device_tools.families import DeviceCatalog, random_family

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


def test_newer_releases_are_drawn_more_often_than_the_oldest() -> None:
    versions = [IOS.random_device().system_version for _ in range(600)]
    newest = sum(1 for v in versions if v.startswith("27"))
    oldest = sum(1 for v in versions if v.startswith("18"))

    assert newest > 0
    assert newest >= oldest / 2  # recency weighting, not a hard ordering


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


# --- lookup and types ------------------------------------------------------


def test_find_device_matches_model_and_optional_version() -> None:
    device = ANDROID._data.devices[0]

    assert ANDROID.find_device(device.model) is not None
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
