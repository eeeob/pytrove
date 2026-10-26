from __future__ import annotations as _annotations

import pytest

from pytrove import rand_tg_device
from pytrove.enums import PlatformDevice
from pytrove.models import DeviceInfo
from pytrove.tg_tools._internal.families import _DEVICES, random_family


@pytest.mark.parametrize("platform", list(PlatformDevice))
def test_rand_tg_device_works_for_every_platform(platform: PlatformDevice) -> None:
    device = rand_tg_device(platform)
    assert device.device_model and device.system_version


def test_rand_tg_device_pins_and_reproduces() -> None:
    device = rand_tg_device(PlatformDevice.IOS, unique_id="u")
    assert isinstance(device, DeviceInfo)
    assert device == rand_tg_device(PlatformDevice.IOS, unique_id="u")
    assert rand_tg_device(PlatformDevice.WEB, to_tuple=True, unique_id="u") == (
        rand_tg_device(PlatformDevice.WEB, unique_id="u").to_tuple()
    )


@pytest.mark.parametrize("platform", list(PlatformDevice))
def test_rand_tg_device_pinned_draws_only_from_that_platform(platform: PlatformDevice) -> None:
    family = _DEVICES[platform]
    allowed = set(family.devices())

    for i in range(20):
        assert rand_tg_device(platform, unique_id=f"pin-{i}") in allowed


def test_rand_tg_device_unpinned_picks_the_family_from_the_unique_id() -> None:
    family = random_family(_DEVICES.values(), "acc-1")

    assert rand_tg_device(unique_id="acc-1") == family.random_device("acc-1")
    assert rand_tg_device(unique_id="acc-1") == rand_tg_device(unique_id="acc-1")


def test_rand_tg_device_without_a_unique_id_varies() -> None:
    assert len({rand_tg_device() for _ in range(50)}) > 1


def test_rand_tg_device_to_tuple_is_model_then_version() -> None:
    device = rand_tg_device(PlatformDevice.ANDROID, unique_id="t")
    model, version = rand_tg_device(PlatformDevice.ANDROID, to_tuple=True, unique_id="t")

    assert (model, version) == device.to_tuple()
