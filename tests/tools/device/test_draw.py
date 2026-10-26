from __future__ import annotations as _annotations

import pytest

from pytrove import random_device
from pytrove.enums import PlatformDevice
from pytrove.models import DeviceInfo
from pytrove.device_tools import DesktopDevice, known_devices
from pytrove.device_tools.families import _DEVICES, random_family


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
    family = _DEVICES[platform]
    allowed = set(family.devices())

    for i in range(20):
        assert random_device(platform, unique_id=f"pin-{i}") in allowed


def test_random_device_unpinned_picks_the_family_from_the_unique_id() -> None:
    family = random_family(_DEVICES.values(), "acc-1")

    assert random_device(unique_id="acc-1") == family.random_device("acc-1")
    assert random_device(unique_id="acc-1") == random_device(unique_id="acc-1")


def test_random_device_without_a_unique_id_varies() -> None:
    assert len({random_device() for _ in range(50)}) > 1


def test_random_device_to_tuple_is_model_then_version() -> None:
    device = random_device(PlatformDevice.ANDROID, unique_id="t")
    model, version = random_device(PlatformDevice.ANDROID, to_tuple=True, unique_id="t")

    assert (model, version) == device.to_tuple()


def test_random_device_pinning_an_os_draws_only_platforms_that_report_it() -> None:
    allowed = set(known_devices(PlatformDevice.DESKTOP, os="linux"))

    for i in range(30):
        assert random_device(unique_id=f"os-{i}", os="linux") in allowed


def test_random_device_pinning_an_os_matches_the_family_draw() -> None:
    expected = DesktopDevice.random_device("a", os="linux")

    assert random_device(PlatformDevice.DESKTOP, unique_id="a", os="linux") == expected
    assert random_device(unique_id="a", os="linux") == expected
    assert random_device(to_tuple=True, unique_id="a", os="linux") == expected.to_tuple()


def test_random_device_refuses_an_os_no_platform_reports() -> None:
    with pytest.raises(ValueError, match="no platform reports the OS 'haiku'"):
        random_device(os="haiku")


def test_random_device_refuses_an_os_the_pinned_platform_lacks() -> None:
    with pytest.raises(ValueError, match="android has no 'linux' devices"):
        random_device(PlatformDevice.ANDROID, os="linux")
