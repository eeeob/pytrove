"""Drawing a device a real client could report, and the per-platform catalogs it is drawn from."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, Final, overload

from ..enums import PlatformDevice
from .families import DeviceCatalog, random_family

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


def get_device_catalog(platform_device: PlatformDevice) -> DeviceCatalog:
    """Return a platform's device catalog, the same object on every call.

    Args:
        platform_device: The platform.

    Returns:
        The catalog, whose methods list and look up what the platform can report.

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
    unique_id: str | None = None,
    *,
    to_dict: _False = False,
    os: str | None = None,
) -> DeviceInfo: ...
@overload
def random_device(
    platform_device: PlatformDevice | None,
    to_tuple: _True,
    unique_id: str | None = None,
    *,
    to_dict: _False = False,
    os: str | None = None,
) -> tuple[str, str]: ...
@overload
def random_device(
    platform_device: PlatformDevice | None = None,
    *,
    to_tuple: _True,
    unique_id: str | None = None,
    to_dict: _False = False,
    os: str | None = None,
) -> tuple[str, str]: ...
@overload
def random_device(
    platform_device: PlatformDevice | None = None,
    to_tuple: _False = False,
    unique_id: str | None = None,
    *,
    to_dict: _True,
    os: str | None = None,
) -> dict[str, str]: ...
def random_device(
    platform_device: PlatformDevice | None = None,
    to_tuple: bool = False,
    unique_id: str | None = None,
    *,
    to_dict: bool = False,
    os: str | None = None,
) -> DeviceInfo | tuple[str, str] | dict[str, str]:
    """Draw a device a real Telegram client could report, with an OS version it runs.

    The platform is drawn by share of real clients unless pinned; the device
    and version come from the bundled catalogs (loaded on first use), weighted
    towards current hardware and releases.

    Args:
        platform_device: Pin the platform.
        to_tuple: Whether to return `DeviceInfo.to_tuple()` instead of a `DeviceInfo`.
        unique_id: Makes the draw reproducible, so one account keeps one device.
        to_dict: Whether to return `DeviceInfo.to_dict()` instead of a `DeviceInfo`.
        os: Pin the OS, one of `get_device_catalog(platform_device).oses()`; without a
            platform, only the platforms that report it are drawn.

    Returns:
        The device.

    Raises:
        TypeError: If `to_tuple` and `to_dict` are both set.
        ValueError: If no platform, or not the pinned one, reports `os`.

    Example:
        >>> from pytrove.enums import PlatformDevice
        >>> device = random_device(PlatformDevice.IOS, unique_id="acc-1")
        >>> device == random_device(PlatformDevice.IOS, unique_id="acc-1")
        True
        >>> desktop = get_device_catalog(PlatformDevice.DESKTOP)
        >>> random_device(os="linux") in desktop.devices(os="linux")
        True
    """
    if to_tuple and to_dict:
        msg = "random_device: to_tuple and to_dict cannot both be True; pick one shape"
        raise TypeError(msg)

    if platform_device is not None:
        catalog = get_device_catalog(platform_device)
    else:
        catalogs = [c for c in _DEVICES.values() if os is None or os in c.oses()]

        if not catalogs:
            msg = f"no platform reports the OS {os!r}"
            raise ValueError(msg)

        catalog = random_family(catalogs, unique_id)

    device = catalog.random_device(unique_id, os=os)
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

    Example:
        >>> is_known_device(random_device(unique_id="acc-1"))
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
