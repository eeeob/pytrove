"""Looking up what the bundled device catalogs hold: OSes, models, versions and known pairs."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

from .families import _DEVICES

if TYPE_CHECKING:
    from ..enums import PlatformDevice
    from ..models.device_models import DeviceInfo


def device_oses(platform_device: PlatformDevice) -> tuple[str, ...]:
    """Return the OSes a platform's devices report: the values `os` accepts.

    Args:
        platform_device: The platform.

    Returns:
        The OSes, in catalog order; empty for a single-OS platform.

    Example:
        >>> from pytrove.enums import PlatformDevice
        >>> device_oses(PlatformDevice.DESKTOP)
        ('windows', 'linux')
        >>> device_oses(PlatformDevice.ANDROID)
        ()
    """
    return _DEVICES[platform_device].oses()


def device_models(platform_device: PlatformDevice, *, os: str | None = None) -> tuple[str, ...]:
    """Return every `device_model` a platform can report.

    Args:
        platform_device: The platform.
        os: Restrict to the devices that report this OS.

    Returns:
        The models, in catalog order.

    Raises:
        ValueError: If the platform has no device for `os`.
    """
    return _DEVICES[platform_device].models(os)


def system_versions(platform_device: PlatformDevice, *, os: str | None = None) -> tuple[str, ...]:
    """Return every distinct `system_version` a platform's devices run, in first-seen order.

    Args:
        platform_device: The platform.
        os: Restrict to this OS's versions.

    Returns:
        The versions.

    Raises:
        ValueError: If the platform has no device for `os`.
    """
    return _DEVICES[platform_device].versions(os)


def known_devices(
    platform_device: PlatformDevice, *, os: str | None = None
) -> tuple[DeviceInfo, ...]:
    """Return every `(device_model, system_version)` pair a platform can report.

    Args:
        platform_device: The platform.
        os: Restrict to this OS.

    Returns:
        The pairs, one per model and version that model runs.

    Raises:
        ValueError: If the platform has no device for `os`.
    """
    return _DEVICES[platform_device].devices(os)


def find_device(
    platform_device: PlatformDevice, device_model: str, system_version: str | None = None
) -> DeviceInfo | None:
    """Look a model up in a platform's catalog, optionally with a version it must run.

    Args:
        platform_device: The platform.
        device_model: The model string, exactly as the client reports it.
        system_version: A version the model must run; its first listed version when `None`.

    Returns:
        The device, or `None` when the model is absent or does not run that version.

    Example:
        >>> from pytrove.enums import PlatformDevice
        >>> find_device(PlatformDevice.ANDROID, "no such model") is None
        True
    """
    return _DEVICES[platform_device].find_device(device_model, system_version)


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
        >>> from pytrove import random_device
        >>> is_known_device(random_device(unique_id="acc-1"))
        True
        >>> is_known_device(("no such model", "SDK 35"))
        False
    """
    model, version = device if isinstance(device, tuple) else device.to_tuple()
    families = _DEVICES.values() if platform_device is None else (_DEVICES[platform_device],)
    return any(family.find_device(model, version) is not None for family in families)


__all__ = (
    "device_models",
    "device_oses",
    "find_device",
    "is_known_device",
    "known_devices",
    "system_versions",
)
