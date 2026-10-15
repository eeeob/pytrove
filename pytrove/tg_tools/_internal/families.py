"""The device families `rand_tg_device` draws from; sampling policy is code, facts are data."""

from __future__ import annotations as _annotations

import hashlib
import os as _os
import random
from collections.abc import Iterable
from typing import Any, ClassVar, Final

from ...enums import PlatformDevice
from ...models.device_models import DeviceInfo
from .catalog import _catalog, _Catalog, _Device, OS_SHARES


class SystemInfo:
    """Base for one platform's device catalog.

    `random_device` draws a device and then an OS version it really runs,
    weighted towards current hardware and releases. A multi-OS platform draws
    the OS first, by `OS_SHARES`. A `unique_id` makes the draw reproducible.

    Attributes:
        platform: The catalog's name.
        platform_weight: Relative likelihood when no platform is requested.
    """

    platform: ClassVar[str]
    platform_weight: ClassVar[float] = 1.0

    @classmethod
    def catalog(cls) -> _Catalog:
        """Return this platform's catalog, loaded on first use.

        Returns:
            The catalog.
        """
        return _catalog(cls.platform)

    @classmethod
    def oses(cls) -> tuple[str, ...]:
        """Return every OS this platform covers.

        Returns:
            The OSes; empty for a single-OS platform.
        """
        return cls.catalog().oses

    @classmethod
    def _devices_for(cls, os: str | None) -> tuple[_Device, ...]:
        """Return the devices that can report an OS, or all of them.

        Args:
            os: The OS, or `None` for every device.

        Returns:
            The devices.

        Raises:
            ValueError: If the platform has no device for `os`.
        """
        catalog = cls.catalog()

        if os is None:
            return catalog.devices

        if (view := catalog.by_os.get(os)) is None:
            msg = f"{cls.platform} has no {os!r} devices; known: {catalog.oses or '()'}"
            raise ValueError(msg)

        return view.devices

    @classmethod
    def devices(cls, os: str | None = None) -> tuple[DeviceInfo, ...]:
        """Return every (model, version) pair this platform can report.

        Args:
            os: Restrict to one OS.

        Returns:
            The pairs.
        """
        return tuple(
            DeviceInfo(device.model, version)
            for device in cls._devices_for(os)
            for version in (device.by_os[os][0] if os else device.versions)
        )

    @classmethod
    def models(cls, os: str | None = None) -> tuple[str, ...]:
        """Return every model string.

        Args:
            os: Restrict to one OS.

        Returns:
            The models.
        """
        return tuple(device.model for device in cls._devices_for(os))

    @classmethod
    def versions(cls, os: str | None = None) -> tuple[str, ...]:
        """Return every distinct OS version, in first-seen order.

        Args:
            os: Restrict to one OS.

        Returns:
            The versions.
        """
        return tuple(dict.fromkeys(
            version
            for device in cls._devices_for(os)
            for version in (device.by_os[os][0] if os else device.versions)
        ))

    @classmethod
    def find_device(cls, model: str, version: str | None = None) -> DeviceInfo | None:
        """Look a model up, optionally with a version it must run.

        Args:
            model: The model string.
            version: A version to require; its first version when `None`.

        Returns:
            The device, or `None` when absent.
        """
        for device in cls.catalog().devices:
            if device.model != model:
                continue

            if version is None:
                return DeviceInfo(device.model, device.versions[0])

            if version in device.versions:
                return DeviceInfo(device.model, version)

        return None

    @classmethod
    def random_device(cls, unique_id: Any = None, os: str | None = None) -> DeviceInfo:
        """Draw a weighted device and a version it runs.

        Args:
            unique_id: Seeds the draw, so one identity always gets one device.
            os: Pin the OS on a multi-OS platform.

        Returns:
            The device.

        Raises:
            ValueError: If the platform has no device for `os`.
        """
        catalog = cls.catalog()
        rng = _rng(unique_id)

        if os is None and catalog.oses:
            os = rng.choices(catalog.oses, weights=[OS_SHARES.get(system, 1.0) for system in catalog.oses], k=1)[0]

        if os is None:
            device = rng.choices(catalog.devices, weights=catalog.weights, k=1)[0]
            names, version_weights = device.versions, device.version_weights
        else:
            if (view := catalog.by_os.get(os)) is None:
                msg = f"{cls.platform} has no {os!r} devices; known: {catalog.oses or '()'}"
                raise ValueError(msg)

            device = rng.choices(view.devices, weights=view.weights, k=1)[0]
            names, version_weights = device.by_os[os]

        return DeviceInfo(device.model, rng.choices(names, weights=version_weights, k=1)[0])


class DesktopDevice(SystemInfo):
    """Windows and Linux PCs, which Telegram reports as one platform, following Telegram Desktop."""

    platform = "desktop"
    platform_weight = 26.0


class WebDevice(SystemInfo):
    """Browsers running Telegram Web: the model is `navigator.userAgent`, the version `navigator.platform`."""

    platform = "web"
    platform_weight = 5.0


class AndroidDevice(SystemInfo):
    """Android phones: `Build.MANUFACTURER + Build.MODEL` and `SDK <level>`."""

    platform = "android"
    platform_weight = 50.0


class iOSDevice(SystemInfo):
    """iPhones, named as Telegram iOS names them, with a bare iOS version."""

    platform = "ios"
    platform_weight = 19.0


_DEVICES: Final[dict[PlatformDevice, type[SystemInfo]]] = {
    PlatformDevice.ANDROID: AndroidDevice,
    PlatformDevice.IOS: iOSDevice,
    PlatformDevice.DESKTOP: DesktopDevice,
    PlatformDevice.WEB: WebDevice,
}
"""The family for each platform. Defined after the classes it holds."""


def _rng(unique_id: Any = None) -> random.Random:
    """Build a generator seeded from `unique_id`, or from system entropy.

    Args:
        unique_id: Any value; the same value always gives the same stream.

    Returns:
        The generator.
    """
    if unique_id is None:
        return random.Random(_os.urandom(32))

    if not isinstance(unique_id, (str, bytes, bytearray)):
        unique_id = str(unique_id)

    if isinstance(unique_id, str):
        unique_id = unique_id.encode("utf-8")

    return random.Random(int(hashlib.sha256(unique_id).hexdigest(), 16))


def random_family(families: Iterable[type[SystemInfo]], unique_id: Any = None) -> type[SystemInfo]:
    """Pick a platform, weighted by `platform_weight`.

    Args:
        families: The families to choose from.
        unique_id: Seeds the draw.

    Returns:
        The family.
    """
    families = tuple(families)
    return _rng(unique_id).choices(families, weights=[f.platform_weight for f in families], k=1)[0]


__all__ = (
    "AndroidDevice",
    "DesktopDevice",
    "SystemInfo",
    "WebDevice",
    "iOSDevice",
    "_rng",
    "random_family",
    "_DEVICES",
)
