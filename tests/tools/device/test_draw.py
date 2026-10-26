from __future__ import annotations as _annotations

import pytest

from pytrove import get_device_catalog, is_known_device, random_device
from pytrove.enums import PlatformDevice
from pytrove.models import DeviceInfo
from pytrove.device_tools.draw import _DEVICES
from pytrove.device_tools.families import DeviceCatalog, random_family


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


def test_get_device_catalog_refuses_an_unknown_platform() -> None:
    with pytest.raises(KeyError):
        get_device_catalog("nope")


# --- random_device ---------------------------------------------------------


@pytest.mark.parametrize("platform", list(PlatformDevice))
def test_random_device_works_for_every_platform(platform: PlatformDevice) -> None:
    device = random_device(platform)
    assert device.device_model and device.system_version


def test_random_device_pins_and_reproduces() -> None:
    device = random_device(PlatformDevice.IOS, unique_id="u")
    assert isinstance(device, DeviceInfo)
    assert device == random_device(PlatformDevice.IOS, unique_id="u")
    assert random_device(PlatformDevice.WEB, to_tuple=True, unique_id="u") == (
        random_device(PlatformDevice.WEB, unique_id="u").to_tuple()
    )


@pytest.mark.parametrize("platform", list(PlatformDevice))
def test_random_device_pinned_draws_only_from_that_platform(platform: PlatformDevice) -> None:
    catalog = _DEVICES[platform]
    allowed = set(catalog.devices())

    for i in range(20):
        assert random_device(platform, unique_id=f"pin-{i}") in allowed


def test_random_device_unpinned_picks_the_catalog_from_the_unique_id() -> None:
    catalog = random_family(_DEVICES.values(), "acc-1")

    assert random_device(unique_id="acc-1") == catalog.random_device("acc-1")
    assert random_device(unique_id="acc-1") == random_device(unique_id="acc-1")


def test_random_device_without_a_unique_id_varies() -> None:
    assert len({random_device() for _ in range(50)}) > 1


def test_random_device_to_tuple_is_model_then_version() -> None:
    device = random_device(PlatformDevice.ANDROID, unique_id="t")
    model, version = random_device(PlatformDevice.ANDROID, to_tuple=True, unique_id="t")

    assert (model, version) == device.to_tuple()


def test_random_device_to_dict_is_the_device_dict() -> None:
    assert random_device(PlatformDevice.WEB, to_dict=True, unique_id="u") == (
        random_device(PlatformDevice.WEB, unique_id="u").to_dict()
    )


def test_random_device_refuses_both_shapes() -> None:
    with pytest.raises(TypeError, match="cannot both be True"):
        random_device(to_tuple=True, to_dict=True)


def test_random_device_pinning_an_os_draws_only_platforms_that_report_it() -> None:
    allowed = set(get_device_catalog(PlatformDevice.DESKTOP).devices(os="linux"))

    for i in range(30):
        assert random_device(unique_id=f"os-{i}", os="linux") in allowed


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


def test_is_known_device_refuses_an_unknown_platform() -> None:
    with pytest.raises(KeyError):
        is_known_device(("model", "1.0"), "nope")
