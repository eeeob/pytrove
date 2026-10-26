"""Drawing a device a real client could report, with an OS version it runs."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, overload

from .families import random_family, _DEVICES

if TYPE_CHECKING:
    from ..enums import PlatformDevice
    from ..models.device_models import DeviceInfo
    from ..typings import _False, _True


@overload
def random_device(
    platform_device: PlatformDevice | None = None,
    to_tuple: _False = False,
    unique_id: str | None = None,
    *,
    os: str | None = None,
) -> DeviceInfo: ...
@overload
def random_device(
    platform_device: PlatformDevice | None,
    to_tuple: _True,
    unique_id: str | None = None,
    *,
    os: str | None = None,
) -> tuple[str, str]: ...
@overload
def random_device(
    platform_device: PlatformDevice | None = None,
    *,
    to_tuple: _True,
    unique_id: str | None = None,
    os: str | None = None,
) -> tuple[str, str]: ...
def random_device(
    platform_device: PlatformDevice | None = None,
    to_tuple: bool = False,
    unique_id: str | None = None,
    *,
    os: str | None = None,
) -> DeviceInfo | tuple[str, str]:
    """Draw a device a real Telegram client could report, with an OS version it runs.

    The platform is drawn by share of real clients unless pinned; the device
    and version come from the bundled catalogs (loaded on first use), weighted
    towards current hardware and releases.

    Args:
        platform_device: Pin the platform.
        to_tuple: Whether to return `DeviceInfo.to_tuple()` instead of a `DeviceInfo`.
        unique_id: Makes the draw reproducible, so one account keeps one device.
        os: Pin the OS, one of `device_oses(platform_device)`; without a platform, only the
            platforms that report it are drawn.

    Returns:
        The device.

    Raises:
        ValueError: If no platform, or not the pinned one, reports `os`.

    Example:
        >>> from pytrove import known_devices
        >>> from pytrove.enums import PlatformDevice
        >>> device = random_device(PlatformDevice.IOS, unique_id="acc-1")
        >>> device == random_device(PlatformDevice.IOS, unique_id="acc-1")
        True
        >>> random_device(os="linux") in known_devices(PlatformDevice.DESKTOP, os="linux")
        True
    """
    if platform_device is not None:
        family = _DEVICES[platform_device]
    else:
        families = [f for f in _DEVICES.values() if os is None or os in f.oses()]

        if not families:
            msg = f"no platform reports the OS {os!r}"
            raise ValueError(msg)

        family = random_family(families, unique_id)

    device = family.random_device(unique_id, os=os)
    return device.to_tuple() if to_tuple else device


__all__ = ("random_device",)
