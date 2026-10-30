"""Drawing a device a real client could report, and the per-platform catalogs it is drawn from."""

from __future__ import annotations as _annotations

import random
from typing import TYPE_CHECKING, Final, overload

from ..enums import PlatformDevice
from .families import DeviceCatalog

if TYPE_CHECKING:
    from ..models.device_models import DeviceInfo
    from ..typings import _False, _True

_DEVICES: Final[dict[PlatformDevice, DeviceCatalog]] = {
    PlatformDevice.ANDROID: DeviceCatalog(PlatformDevice.ANDROID, 50.0),
    PlatformDevice.IOS: DeviceCatalog(PlatformDevice.IOS, 19.0),
    PlatformDevice.DESKTOP: DeviceCatalog(PlatformDevice.DESKTOP, 26.0),
    PlatformDevice.WEB: DeviceCatalog(PlatformDevice.WEB, 5.0),
}
"""Each platform's catalog, weighted by its share of real clients; each loads its data on first use."""

_MULTI_OS_PLATFORMS: Final[frozenset[PlatformDevice]] = frozenset({PlatformDevice.DESKTOP})
"""The platforms whose catalog reports OSes, so an `os` pin never loads the others' data."""


def get_device_catalog(platform_device: PlatformDevice) -> DeviceCatalog:
    """Return a platform's device catalog, the same object on every call.

    Args:
        platform_device: The platform.

    Returns:
        The catalog, whose methods list and look up what the platform can report.

    Raises:
        KeyError: If `platform_device` is not a `PlatformDevice` member.

    Example:
        >>> from pytrove.enums import PlatformDevice
        >>> get_device_catalog(PlatformDevice.DESKTOP).oses()
        ('windows', 'linux')
    """
    return _DEVICES[platform_device]


@overload
def random_device(
    platform_device: PlatformDevice | None = None,
    to_tuple: _False = False,
    *,
    to_dict: _False = False,
    os: str | None = None,
) -> DeviceInfo: ...
@overload
def random_device(
    platform_device: PlatformDevice | None,
    to_tuple: _True,
    *,
    to_dict: _False = False,
    os: str | None = None,
) -> tuple[str, str]: ...
@overload
def random_device(
    platform_device: PlatformDevice | None = None,
    *,
    to_tuple: _True,
    to_dict: _False = False,
    os: str | None = None,
) -> tuple[str, str]: ...
@overload
def random_device(
    platform_device: PlatformDevice | None = None,
    to_tuple: _False = False,
    *,
    to_dict: _True,
    os: str | None = None,
) -> dict[str, str]: ...
@overload
def random_device(
    platform_device: PlatformDevice | None = None,
    to_tuple: bool = False,
    *,
    to_dict: bool = False,
    os: str | None = None,
) -> DeviceInfo | tuple[str, str] | dict[str, str]: ...
def random_device(
    platform_device: PlatformDevice | None = None,
    to_tuple: bool = False,
    *,
    to_dict: bool = False,
    os: str | None = None,
) -> DeviceInfo | tuple[str, str] | dict[str, str]:
    """Draw a device a real Telegram client could report, with an OS version it runs.

    The platform is drawn by share of real clients unless pinned; the device
    and version come from the bundled catalogs (loaded on first use), weighted
    towards current hardware and releases. Every call draws anew: keep a drawn
    device (`to_dict()`) with the account it belongs to, and vet a stored one
    with `is_known_device`, rather than drawing again.

    Args:
        platform_device: Pin the platform.
        to_tuple: Whether to return `DeviceInfo.to_tuple()` instead of a `DeviceInfo`.
        to_dict: Whether to return `DeviceInfo.to_dict()` instead of a `DeviceInfo`.
        os: Pin the OS, one of `get_device_catalog(platform_device).oses()`; without a
            platform, only the platforms that report it are drawn.

    Returns:
        The device.

    Raises:
        TypeError: If `to_tuple` and `to_dict` are both set.
        KeyError: If `platform_device` is not a `PlatformDevice` member.
        ValueError: If no platform, or not the pinned one, reports `os`.

    Example:
        >>> from pytrove.enums import PlatformDevice
        >>> device = random_device(PlatformDevice.IOS)
        >>> is_known_device(device, PlatformDevice.IOS)
        True
        >>> linux = random_device(os="linux")
        >>> is_known_device(linux, PlatformDevice.DESKTOP)
        True
        >>> linux.system_version in get_device_catalog(PlatformDevice.DESKTOP).versions(os="linux")
        True
    """
    if to_tuple and to_dict:
        msg = "random_device: to_tuple and to_dict cannot both be True; pick one shape"
        raise TypeError(msg)

    if platform_device is not None:
        catalog = get_device_catalog(platform_device)
    else:
        catalogs = [
            candidate
            for platform, candidate in _DEVICES.items()
            if os is None or (platform in _MULTI_OS_PLATFORMS and os in candidate.oses())
        ]

        if not catalogs:
            msg = f"no platform reports the OS {os!r}"
            raise ValueError(msg)

        catalog = random.choices(catalogs, weights=[c.weight for c in catalogs], k=1)[0]

    device = catalog.random_device(os=os)
    if to_tuple:
        return device.to_tuple()

    return device.to_dict() if to_dict else device


def is_known_device(
    device: DeviceInfo | tuple[str, str], platform_device: PlatformDevice | None = None
) -> bool:
    """Tell whether the catalogs hold a pair, e.g. to vet a stored session's device.

    Args:
        device: A `DeviceInfo`, or a `(device_model, system_version)` tuple.
        platform_device: Check this platform only; every platform when `None`.

    Returns:
        Whether some platform lists that model running that version.

    Raises:
        KeyError: If `platform_device` is not a `PlatformDevice` member.
        ValueError: If `device` is a tuple of another length than two.

    Example:
        >>> is_known_device(random_device())
        True
        >>> is_known_device(("no such model", "SDK 35"))
        False
    """
    model, version = device if isinstance(device, tuple) else device.to_tuple()
    catalogs = _DEVICES.values() if platform_device is None else (_DEVICES[platform_device],)
    return any(catalog.find_device(model, version) is not None for catalog in catalogs)


__all__ = (
    "get_device_catalog",
    "is_known_device",
    "random_device",
)
