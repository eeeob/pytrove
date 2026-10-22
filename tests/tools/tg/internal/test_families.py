from __future__ import annotations as _annotations

import collections

import pytest

from pytrove.enums import PlatformDevice
from pytrove.models import DeviceInfo
from pytrove.tg_tools._internal.catalog import _catalog, _load, OS_SHARES
from pytrove.tg_tools._internal.families import (
    _DEVICES,
    AndroidDevice,
    DesktopDevice,
    SystemInfo,
    WebDevice,
    _rng,
    iOSDevice,
    random_family,
)

ALL_PLATFORMS = (DesktopDevice, AndroidDevice, iOSDevice, WebDevice)
IDS = [p.platform for p in ALL_PLATFORMS]

#: Telegram reports every desktop OS as "desktop"; macOS is deliberately not in the catalog.
DESKTOP_OSES = ("windows", "linux")


@pytest.fixture(scope="module", params=ALL_PLATFORMS, ids=IDS)
def platform(request: pytest.FixtureRequest) -> type[SystemInfo]:
    return request.param


# --- sampling --------------------------------------------------------------


def test_random_device_only_returns_pairs_the_catalog_allows(platform: type[SystemInfo]) -> None:
    allowed = {(d.model, v) for d in platform.catalog().devices for v in d.versions}

    for _ in range(200):
        device = platform.random_device()
        assert (device.model, device.version) in allowed


def test_same_unique_id_gives_the_same_device(platform: type[SystemInfo]) -> None:
    assert platform.random_device("user-42") == platform.random_device("user-42")


def test_different_unique_ids_spread_across_devices(platform: type[SystemInfo]) -> None:
    drawn = {platform.random_device(f"user-{i}").model for i in range(60)}
    assert len(drawn) > 1


def test_random_device_without_an_id_varies(platform: type[SystemInfo]) -> None:
    drawn = {platform.random_device() for _ in range(80)}
    assert len(drawn) > 1


@pytest.mark.parametrize("os", DESKTOP_OSES)
def test_pinning_an_os_only_draws_that_os(os: str) -> None:
    allowed = {
        (d.model, v) for d in DesktopDevice.catalog().by_os[os].devices for v in d.by_os[os][0]
    }

    for i in range(120):
        device = DesktopDevice.random_device(f"pin-{i}", os=os)
        assert (device.model, device.version) in allowed


def test_pinning_an_os_is_deterministic() -> None:
    assert DesktopDevice.random_device("abc", os="linux") == DesktopDevice.random_device(
        "abc", os="linux"
    )


def test_pinning_an_unknown_os_raises() -> None:
    with pytest.raises(ValueError, match="no 'haiku' devices"):
        DesktopDevice.random_device(os="haiku")

    with pytest.raises(ValueError, match="no 'windows' devices"):
        AndroidDevice.random_device(os="windows")


def test_desktop_draws_follow_the_os_shares() -> None:
    os_of = {v["version"]: v["os"] for v in _load("desktop")["versions"]}
    picks = collections.Counter(os_of[DesktopDevice.random_device().version] for _ in range(4000))
    total = sum(OS_SHARES.values())

    for name, share in OS_SHARES.items():
        assert abs(picks[name] / 4000 - share / total) < 0.05, (name, picks)


def test_newer_releases_are_drawn_more_often_than_the_oldest() -> None:
    versions = [iOSDevice.random_device().version for _ in range(600)]
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


# --- lookup and types ------------------------------------------------------


def test_find_device_matches_model_and_optional_version() -> None:
    device = AndroidDevice.catalog().devices[0]

    assert AndroidDevice.find_device(device.model) is not None
    assert AndroidDevice.find_device(device.model, device.versions[0]) == DeviceInfo(
        device.model, device.versions[0]
    )
    assert AndroidDevice.find_device(device.model, "SDK 1") is None
    assert AndroidDevice.find_device("no such model") is None


def test_models_and_versions_narrow_to_one_os() -> None:
    # Windows draws only the shared pool, Linux adds its own boards on top.
    assert set(DesktopDevice.models("windows")) < set(DesktopDevice.models())
    assert set(DesktopDevice.versions("windows")).isdisjoint(DesktopDevice.versions("linux"))
    assert sum(len(DesktopDevice.versions(os)) for os in DESKTOP_OSES) == len(
        DesktopDevice.versions()
    )


def test_single_os_platform_reports_no_oses() -> None:
    assert AndroidDevice.oses() == ()
    assert iOSDevice.oses() == ()
    assert DesktopDevice.oses() == DESKTOP_OSES


def test_unknown_platform_raises() -> None:
    class Nope(SystemInfo):
        platform = "nope"

    with pytest.raises(FileNotFoundError):
        Nope.random_device()


def test_families_and_rng() -> None:
    assert set(_DEVICES) == set(PlatformDevice)
    assert _rng("a").random() == _rng("a").random()
    assert _rng(5).random() == _rng("5").random()
    assert random_family(_DEVICES.values(), "a") is random_family(_DEVICES.values(), "a")


def test_rng_seeds_bytes_and_text_alike() -> None:
    assert _rng(b"a").random() == _rng("a").random()
    assert _rng(bytearray(b"a")).random() == _rng("a").random()


def test_rng_without_a_seed_differs_each_time() -> None:
    assert _rng().random() != _rng().random()


def test_devices_map_each_platform_to_its_family() -> None:
    assert _DEVICES == {
        PlatformDevice.ANDROID: AndroidDevice,
        PlatformDevice.IOS: iOSDevice,
        PlatformDevice.DESKTOP: DesktopDevice,
        PlatformDevice.WEB: WebDevice,
    }
    assert [f.platform_weight for f in ALL_PLATFORMS] == [26.0, 50.0, 19.0, 5.0]
    assert SystemInfo.platform_weight == 1.0


def test_catalog_is_the_cached_platform_catalog(platform: type[SystemInfo]) -> None:
    assert platform.catalog() is _catalog(platform.platform)


def test_devices_lists_every_model_and_version_pair(platform: type[SystemInfo]) -> None:
    pairs = platform.devices()

    assert pairs == tuple(
        DeviceInfo(d.model, v) for d in platform.catalog().devices for v in d.versions
    )
    assert all(isinstance(pair, DeviceInfo) for pair in pairs)


@pytest.mark.parametrize("os", DESKTOP_OSES)
def test_devices_narrowed_to_one_os_only_pairs_its_versions(os: str) -> None:
    pairs = DesktopDevice.devices(os)

    assert pairs and set(pairs) <= set(DesktopDevice.devices())
    assert {pair.version for pair in pairs} == set(DesktopDevice.versions(os))


def test_listing_an_unknown_os_raises() -> None:
    with pytest.raises(ValueError, match="desktop has no 'haiku' devices"):
        DesktopDevice.devices("haiku")

    with pytest.raises(ValueError, match=r"android has no 'linux' devices; known: \(\)"):
        AndroidDevice.models("linux")

    with pytest.raises(ValueError, match="no 'haiku' devices"):
        DesktopDevice.versions("haiku")
