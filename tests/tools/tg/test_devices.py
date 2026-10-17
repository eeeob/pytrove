from __future__ import annotations as _annotations

import pytest

from pytrove import rand_tg_device
from pytrove.enums import PlatformDevice
from pytrove.models import DeviceInfo


@pytest.mark.parametrize("platform", list(PlatformDevice))
def test_rand_tg_device_works_for_every_platform(platform):
    device = rand_tg_device(platform)
    assert device.model and device.version


def test_rand_tg_device_pins_and_reproduces() -> None:
    device = rand_tg_device(PlatformDevice.IOS, unique_id="u")
    assert isinstance(device, DeviceInfo)
    assert device == rand_tg_device(PlatformDevice.IOS, unique_id="u")
    assert rand_tg_device(PlatformDevice.WEB, to_tuple=True, unique_id="u") == tuple(
        rand_tg_device(PlatformDevice.WEB, unique_id="u").to_dict().values()
    )


def test_device_info_is_immutable_and_prints_both_parts():
    device = DeviceInfo("model", "version")

    assert str(device) == "model version"
    assert device.to_dict() == {"device_model": "model", "system_version": "version"}

    with pytest.raises(AttributeError):
        device.model = "other"
