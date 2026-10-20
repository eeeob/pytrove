"""Drawing a device a real Telegram client could report."""

from __future__ import annotations as _annotations

from typing import overload

from ..enums import PlatformDevice
from ..models.device_models import DeviceInfo
from ..typings import _False, _True
from ._internal.families import _DEVICES, random_family


@overload
def rand_tg_device(
    platform_device: PlatformDevice | None = ..., to_tuple: _False = False, unique_id: str | None = ...,
) -> DeviceInfo: ...
@overload
def rand_tg_device(
    platform_device: PlatformDevice | None = ..., *, to_tuple: _True, unique_id: str | None = ...,
) -> tuple[str, str]: ...
def rand_tg_device(
    platform_device: PlatformDevice | None = None, to_tuple: bool = False, unique_id: str | None = None,
) -> DeviceInfo | tuple[str, str]:
    """Draw a device a real Telegram client could report, with an OS version it runs.

    The platform is drawn by share of real clients unless pinned; the device
    and version come from the bundled catalogs (loaded on first use), weighted
    towards current hardware and releases.

    Args:
        platform_device: Pin the platform.
        to_tuple: Whether to return `(model, version)` instead of a `DeviceInfo`.
        unique_id: Makes the draw reproducible, so one account keeps one device.

    Returns:
        The device.
    """
    family = random_family(_DEVICES.values(), unique_id) if platform_device is None else _DEVICES[platform_device]
    device = family.random_device(unique_id)
    return (device.model, device.version) if to_tuple else device


__all__ = ("rand_tg_device",)
