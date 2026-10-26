from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

import pytest

from pytrove import (
    device_models,
    device_oses,
    find_device,
    is_known_device,
    known_devices,
    random_device,
    system_versions,
)
from pytrove.device_tools.families import _DEVICES, AndroidDevice, DesktopDevice
from pytrove.enums import PlatformDevice
from pytrove.models import DeviceInfo

if TYPE_CHECKING:
    from collections.abc import Callable

LISTERS = [device_models, system_versions, known_devices]


@pytest.mark.parametrize("platform", list(PlatformDevice))
def test_device_oses_is_the_family_oses(platform: PlatformDevice) -> None:
    assert device_oses(platform) == _DEVICES[platform].oses()


def test_device_oses_names_the_desktop_oses_only() -> None:
    assert device_oses(PlatformDevice.DESKTOP) == ("windows", "linux")
    assert device_oses(PlatformDevice.ANDROID) == ()
    assert device_oses(PlatformDevice.IOS) == ()


@pytest.mark.parametrize("platform", list(PlatformDevice))
def test_listers_match_the_family_methods(platform: PlatformDevice) -> None:
    family = _DEVICES[platform]

    assert device_models(platform) == family.models()
    assert system_versions(platform) == family.versions()
    assert known_devices(platform) == family.devices()


@pytest.mark.parametrize("os", ["windows", "linux"])
def test_listers_narrow_to_one_os(os: str) -> None:
    assert device_models(PlatformDevice.DESKTOP, os=os) == DesktopDevice.models(os)
    assert system_versions(PlatformDevice.DESKTOP, os=os) == DesktopDevice.versions(os)
    assert known_devices(PlatformDevice.DESKTOP, os=os) == DesktopDevice.devices(os)


@pytest.mark.parametrize("lister", LISTERS)
def test_listers_refuse_an_unknown_os(lister: Callable[..., object]) -> None:
    with pytest.raises(ValueError, match="no 'haiku' devices"):
        lister(PlatformDevice.DESKTOP, os="haiku")


@pytest.mark.parametrize("lister", [device_oses, *LISTERS, find_device])
def test_lookups_refuse_an_unknown_platform(lister: Callable[..., object]) -> None:
    args = ("nope", "model") if lister is find_device else ("nope",)

    with pytest.raises(KeyError):
        lister(*args)


def test_find_device_matches_the_family_lookup() -> None:
    device = AndroidDevice._get_catalog().devices[0]

    assert find_device(PlatformDevice.ANDROID, device.model) == DeviceInfo(
        device.model, device.versions[0]
    )
    assert find_device(PlatformDevice.ANDROID, device.model, device.versions[-1]) == DeviceInfo(
        device.model, device.versions[-1]
    )
    assert find_device(PlatformDevice.ANDROID, device.model, "SDK 1") is None
    assert find_device(PlatformDevice.ANDROID, "no such model") is None


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
