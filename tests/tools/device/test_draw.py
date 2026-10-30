from __future__ import annotations as _annotations

import collections
import itertools
import subprocess
import sys

import pytest

from pytrove import get_device_catalog, is_known_device, random_device
from pytrove.enums import PlatformDevice
from pytrove.models import DeviceInfo
from pytrove.device_tools._internal.catalog import _load, OS_SHARES
from pytrove.device_tools.draw import _DEVICES, _MULTI_OS_PLATFORMS
from pytrove.device_tools.families import DeviceCatalog

OS_PIN_PROBE = """
from pytrove import random_device
from pytrove.device_tools.draw import _DEVICES
from pytrove.enums import PlatformDevice
random_device(unique_id="probe", os="linux")
loaded = {p for p, c in _DEVICES.items() if "_data" in c.__dict__}
assert loaded == {PlatformDevice.DESKTOP}, loaded
"""


# --- the platform catalogs -------------------------------------------------


def test_devices_hold_one_catalog_per_platform_at_its_share() -> None:
    assert set(_DEVICES) == set(PlatformDevice)
    assert all(catalog.platform is platform for platform, catalog in _DEVICES.items())
    assert {platform: catalog.weight for platform, catalog in _DEVICES.items()} == {
        PlatformDevice.ANDROID: 50.0,
        PlatformDevice.IOS: 19.0,
        PlatformDevice.DESKTOP: 26.0,
        PlatformDevice.WEB: 5.0,
    }


@pytest.mark.parametrize("platform", list(PlatformDevice))
def test_get_device_catalog_returns_the_same_object_each_call(platform: PlatformDevice) -> None:
    catalog = get_device_catalog(platform)

    assert isinstance(catalog, DeviceCatalog)
    assert catalog is _DEVICES[platform]
    assert catalog is get_device_catalog(platform)


def test_multi_os_platforms_are_exactly_those_whose_catalog_reports_oses() -> None:
    assert {p for p, c in _DEVICES.items() if c.oses()} == _MULTI_OS_PLATFORMS
    assert _MULTI_OS_PLATFORMS == frozenset({PlatformDevice.DESKTOP})


def test_get_device_catalog_refuses_an_unknown_platform() -> None:
    with pytest.raises(KeyError):
        get_device_catalog("nope")


# --- random_device ---------------------------------------------------------


@pytest.mark.parametrize("platform", list(PlatformDevice))
def test_random_device_works_for_every_platform(platform: PlatformDevice) -> None:
    assert is_known_device(random_device(platform), platform)


def test_random_device_pins_and_reproduces() -> None:
    device = random_device(PlatformDevice.IOS, unique_id="u")
    assert isinstance(device, DeviceInfo)
    assert device == random_device(PlatformDevice.IOS, unique_id="u")
    assert random_device(PlatformDevice.WEB, to_tuple=True, unique_id="u") == (
        random_device(PlatformDevice.WEB, unique_id="u").to_tuple()
    )


@pytest.mark.parametrize("platform", list(PlatformDevice))
def test_random_device_pinned_draws_only_from_that_platform(platform: PlatformDevice) -> None:
    for i in range(20):
        assert is_known_device(random_device(platform, unique_id=f"pin-{i}"), platform)


@pytest.mark.parametrize("platform", list(PlatformDevice))
def test_random_device_pinned_matches_the_catalog_draw(platform: PlatformDevice) -> None:
    assert random_device(platform, unique_id="same") == _DEVICES[platform].random_device("same")


def test_random_device_unpinned_is_reproducible_per_unique_id() -> None:
    assert random_device(unique_id="acc-1") == random_device(unique_id="acc-1")


def test_random_device_seeds_a_non_text_unique_id_by_its_str() -> None:
    assert random_device(unique_id=42) == random_device(unique_id="42")


def test_seeded_unpinned_draws_follow_every_share() -> None:
    # One stream picks platform, OS, device and version; reusing the first number for two
    # of them confined each platform to a slice of its catalog and skewed the OS mix.
    n = 5000
    platform_of = {d.model: p for p, c in _DEVICES.items() for d in c._data.devices}
    os_of = {v["version"]: v["os"] for v in _load("desktop")["versions"]}
    draws = [random_device(unique_id=f"acc-{i}") for i in range(n)]
    platforms = collections.Counter(platform_of[d.device_model] for d in draws)
    total = sum(c.weight for c in _DEVICES.values())

    for platform, catalog in _DEVICES.items():
        assert abs(platforms[platform] / n - catalog.weight / total) < 0.03, platforms

    desktop = [d for d in draws if platform_of[d.device_model] is PlatformDevice.DESKTOP]
    linux = sum(os_of[d.system_version] == "linux" for d in desktop) / len(desktop)
    assert abs(linux - OS_SHARES["linux"] / sum(OS_SHARES.values())) < 0.04

    android = _DEVICES[PlatformDevice.ANDROID]._data
    ends = list(itertools.accumulate(android.weights))
    lower = {d.model for d, end in zip(android.devices, ends, strict=True) if end <= ends[-1] / 2}
    expected = max(end for end in ends if end <= ends[-1] / 2) / ends[-1]
    drawn = [d for d in draws if platform_of[d.device_model] is PlatformDevice.ANDROID]
    observed = sum(d.device_model in lower for d in drawn) / len(drawn)
    assert abs(observed - expected) < 0.05, (observed, expected)


def test_random_device_without_a_unique_id_varies() -> None:
    assert len({random_device() for _ in range(50)}) > 1


def test_random_device_to_tuple_is_model_then_version() -> None:
    device = random_device(PlatformDevice.ANDROID, unique_id="t")
    model, version = random_device(PlatformDevice.ANDROID, to_tuple=True, unique_id="t")

    assert (model, version) == device.to_tuple()


def test_random_device_takes_to_tuple_positionally() -> None:
    assert random_device(PlatformDevice.IOS, True, "p") == (
        random_device(PlatformDevice.IOS, unique_id="p").to_tuple()
    )


@pytest.mark.parametrize("flag", [True, False])
def test_random_device_takes_a_runtime_bool_flag(flag: bool) -> None:
    device = random_device(PlatformDevice.IOS, unique_id="b")

    assert random_device(PlatformDevice.IOS, to_tuple=flag, unique_id="b") == (
        device.to_tuple() if flag else device
    )
    assert random_device(PlatformDevice.IOS, unique_id="b", to_dict=flag) == (
        device.to_dict() if flag else device
    )


def test_random_device_to_dict_is_the_device_dict() -> None:
    assert random_device(PlatformDevice.WEB, to_dict=True, unique_id="u") == (
        random_device(PlatformDevice.WEB, unique_id="u").to_dict()
    )


def test_random_device_refuses_both_shapes() -> None:
    with pytest.raises(TypeError, match="cannot both be True"):
        random_device(to_tuple=True, to_dict=True)


def test_random_device_pinning_an_os_draws_only_platforms_that_report_it() -> None:
    linux = set(get_device_catalog(PlatformDevice.DESKTOP).versions(os="linux"))

    for i in range(30):
        device = random_device(unique_id=f"os-{i}", os="linux")
        assert is_known_device(device, PlatformDevice.DESKTOP)
        assert device.system_version in linux


def test_random_device_pinning_an_os_loads_only_the_platforms_that_report_it() -> None:
    subprocess.run([sys.executable, "-c", OS_PIN_PROBE], check=True)


def test_random_device_pinning_an_os_matches_the_catalog_draw() -> None:
    expected = get_device_catalog(PlatformDevice.DESKTOP).random_device("a", os="linux")

    assert random_device(PlatformDevice.DESKTOP, unique_id="a", os="linux") == expected
    assert random_device(unique_id="a", os="linux") == expected
    assert random_device(to_tuple=True, unique_id="a", os="linux") == expected.to_tuple()
    assert random_device(to_dict=True, unique_id="a", os="linux") == expected.to_dict()


def test_random_device_refuses_an_os_no_platform_reports() -> None:
    with pytest.raises(ValueError, match="no platform reports the OS 'haiku'"):
        random_device(os="haiku")


def test_random_device_refuses_an_os_the_pinned_platform_lacks() -> None:
    with pytest.raises(ValueError, match="android has no 'linux' devices"):
        random_device(PlatformDevice.ANDROID, os="linux")


# --- is_known_device -------------------------------------------------------


def test_is_known_device_accepts_a_device_or_its_tuple() -> None:
    device = random_device(PlatformDevice.IOS, unique_id="known")

    assert is_known_device(device)
    assert is_known_device(device.to_tuple())
    assert is_known_device(device, PlatformDevice.IOS)


def test_is_known_device_rejects_an_unknown_or_misplaced_pair() -> None:
    device = random_device(PlatformDevice.IOS, unique_id="known")

    assert not is_known_device(("no such model", "SDK 35"))
    assert not is_known_device(DeviceInfo(device.device_model, "0.0"))
    assert not is_known_device(device, PlatformDevice.ANDROID)


def test_is_known_device_rejects_a_model_with_another_oss_version() -> None:
    desktop = get_device_catalog(PlatformDevice.DESKTOP)
    assert "KVM" in desktop.models(os="linux")
    assert "KVM" not in desktop.models(os="windows")
    assert "Windows 11 x64" in desktop.versions(os="windows")

    assert not is_known_device(("KVM", "Windows 11 x64"))
    assert not is_known_device(("KVM", "Windows 11 x64"), PlatformDevice.DESKTOP)


@pytest.mark.parametrize("device", [("model",), ("model", "1.0", "extra")])
def test_is_known_device_refuses_a_tuple_that_is_not_a_pair(device: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="values to unpack"):
        is_known_device(device)


def test_is_known_device_refuses_an_unknown_platform() -> None:
    with pytest.raises(KeyError):
        is_known_device(("model", "1.0"), "nope")
