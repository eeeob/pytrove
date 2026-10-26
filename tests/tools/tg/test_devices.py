from __future__ import annotations as _annotations

from pytrove import device_tools, tg_tools
from pytrove.tg_tools import devices


def test_rand_tg_device_is_random_device() -> None:
    assert tg_tools.rand_tg_device is device_tools.random_device


def test_devices_exports_only_the_telegram_name() -> None:
    assert devices.__all__ == ("rand_tg_device",)
    assert "random_device" not in tg_tools.__all__
