from __future__ import annotations as _annotations

import dataclasses

import pytest

from pytrove.models import DeviceInfo


def test_device_info_prints_the_model_then_the_version() -> None:
    assert str(DeviceInfo("Pixel 9", "SDK 35")) == "Pixel 9 SDK 35"


def test_device_info_to_dict_uses_the_init_connection_names() -> None:
    assert DeviceInfo("Pixel 9", "SDK 35").to_dict() == {"device_model": "Pixel 9", "system_version": "SDK 35"}


def test_device_info_is_frozen_and_compares_by_value() -> None:
    device = DeviceInfo("model", "version")

    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(device, "model", "other")  # noqa: B010 - plain assignment to a frozen field fails `ty`

    assert device == DeviceInfo("model", "version")
    assert hash(device) == hash(DeviceInfo("model", "version"))
