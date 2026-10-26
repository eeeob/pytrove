"""The per-platform device catalogs `random_device` draws from; sampling policy is code, facts are data."""

from __future__ import annotations as _annotations

import math
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING

from ..enums import PlatformDevice
from ..models.device_models import DeviceInfo
from ._internal import _Catalog, _Device, _OsView, _build_catalog, _rng, OS_SHARES

if TYPE_CHECKING:
    import random
    from collections.abc import Iterable


# `slots=True` is left out on purpose: `cached_property` stores the loaded catalog in `__dict__`.
@dataclass(frozen=True)
class DeviceCatalog:
    """One platform's device catalog, loaded from its bundled file on first use.

    `random_device` draws a device and then an OS version it really runs,
    weighted towards current hardware and releases. A multi-OS platform draws
    the OS first, by `OS_SHARES`. A `unique_id` makes the draw reproducible.

    The bundled platforms follow their official clients: Android reports
    `Build.MANUFACTURER + Build.MODEL` and `SDK <level>`; iOS an iPhone name
    and a bare iOS version; desktop a Windows or Linux PC, as Telegram Desktop
    does; web `navigator.userAgent` and `navigator.platform`.
    """

    platform: PlatformDevice
    """The platform, which names its bundled catalog file."""

    weight: float = 1.0
    """Relative likelihood when no platform is requested; finite and not negative."""

    def __post_init__(self) -> None:
        """Refuse a weight no draw can use.

        Raises:
            ValueError: If `weight` is negative, infinite or NaN.
        """
        if not (math.isfinite(self.weight) and self.weight >= 0):
            msg = f"DeviceCatalog weight must be finite and not negative, got {self.weight!r}"
            raise ValueError(msg)

    @cached_property
    def _data(self) -> _Catalog:
        """Return this platform's catalog, built on first use and then kept on the instance.

        Returns:
            The catalog.
        """
        return _build_catalog(self.platform)

    def oses(self) -> tuple[str, ...]:
        """Return the OSes this platform's devices report: the values `os` accepts.

        Returns:
            The OSes, in catalog order; empty for a single-OS platform.

        Example:
            >>> from pytrove import get_device_catalog
            >>> from pytrove.enums import PlatformDevice
            >>> get_device_catalog(PlatformDevice.DESKTOP).oses()
            ('windows', 'linux')
            >>> get_device_catalog(PlatformDevice.ANDROID).oses()
            ()
        """
        return self._data.oses

    def _view(self, os: str) -> _OsView:
        """Return the devices that can report an OS, with their weights.

        Args:
            os: The OS.

        Returns:
            The view.

        Raises:
            ValueError: If the platform has no device for `os`.
        """
        catalog = self._data

        if (view := catalog.by_os.get(os)) is None:
            msg = f"{self.platform} has no {os!r} devices; known: {catalog.oses or '()'}"
            raise ValueError(msg)

        return view

    def _devices_for(self, os: str | None) -> tuple[_Device, ...]:
        """Return the devices that can report an OS, or all of them.

        Args:
            os: The OS, or `None` for every device.

        Returns:
            The devices.

        Raises:
            ValueError: If the platform has no device for `os`.
        """
        return self._data.devices if os is None else self._view(os).devices

    def devices(self, *, os: str | None = None) -> tuple[DeviceInfo, ...]:
        """Return every `(device_model, system_version)` pair this platform can report.

        It pairs every model with every version that model runs, which on desktop is
        hundreds of thousands of pairs; to test one pair, use `find_device` or
        `is_known_device` instead.

        Args:
            os: Restrict to this OS.

        Returns:
            The pairs, one per model and version that model runs.

        Raises:
            ValueError: If the platform has no device for `os`.
        """
        return tuple(
            DeviceInfo(device.model, version)
            for device in self._devices_for(os)
            for version in device.os_versions(os)
        )

    def models(self, *, os: str | None = None) -> tuple[str, ...]:
        """Return every `device_model` this platform can report.

        Args:
            os: Restrict to the devices that report this OS.

        Returns:
            The models, in catalog order.

        Raises:
            ValueError: If the platform has no device for `os`.
        """
        return tuple(device.model for device in self._devices_for(os))

    def versions(self, *, os: str | None = None) -> tuple[str, ...]:
        """Return every distinct `system_version` this platform's devices run, in first-seen order.

        Args:
            os: Restrict to this OS's versions.

        Returns:
            The versions.

        Raises:
            ValueError: If the platform has no device for `os`.
        """
        return tuple(
            dict.fromkeys(
                version for device in self._devices_for(os) for version in device.os_versions(os)
            )
        )

    def find_device(
        self, device_model: str, system_version: str | None = None
    ) -> DeviceInfo | None:
        """Look a model up, optionally with a version it must run.

        Args:
            device_model: The model string, exactly as the client reports it.
            system_version: A version the model must run; its first listed version when `None`.

        Returns:
            The device, or `None` when the model is absent or does not run that version.

        Example:
            >>> from pytrove import get_device_catalog
            >>> from pytrove.enums import PlatformDevice
            >>> get_device_catalog(PlatformDevice.ANDROID).find_device("no such model") is None
            True
        """
        for device in self._data.devices:
            if device.model != device_model:
                continue

            if system_version is None:
                return DeviceInfo(device.model, device.versions[0])

            if system_version in device.versions:
                return DeviceInfo(device.model, system_version)

        return None

    def random_device(self, unique_id: object = None, os: str | None = None) -> DeviceInfo:
        """Draw a weighted device and a version it runs.

        Args:
            unique_id: Seeds the draw, so one identity always gets one device; bytes
                as they are, any other value by its `str`.
            os: Pin the OS on a multi-OS platform.

        Returns:
            The device.

        Raises:
            ValueError: If the platform has no device for `os`.
        """
        return self._draw(_rng(unique_id), os)

    def _draw(self, rng: random.Random, os: str | None) -> DeviceInfo:
        """Draw a device and a version it runs, continuing the stream `rng` is on.

        Args:
            rng: The generator; `random_device` may already have used it to pick this catalog.
            os: Pin the OS on a multi-OS platform.

        Returns:
            The device.

        Raises:
            ValueError: If the platform has no device for `os`.
        """
        catalog = self._data

        if os is None and catalog.oses:
            os = rng.choices(
                catalog.oses, weights=[OS_SHARES.get(system, 1.0) for system in catalog.oses], k=1
            )[0]

        if os is None:
            device = rng.choices(catalog.devices, weights=catalog.weights, k=1)[0]
            names, version_weights = device.versions, device.version_weights
        else:
            view = self._view(os)
            device = rng.choices(view.devices, weights=view.weights, k=1)[0]
            names, version_weights = device.by_os[os]

        return DeviceInfo(device.model, rng.choices(names, weights=version_weights, k=1)[0])


def random_family(catalogs: Iterable[DeviceCatalog], unique_id: object = None) -> DeviceCatalog:
    """Pick a platform's catalog, weighted by `weight`.

    Drawing from the picked catalog with the same `unique_id` reuses the same stream
    and correlates the two picks; for a seeded draw across platforms, use
    `random_device(unique_id=...)` instead.

    Args:
        catalogs: The catalogs to choose from; any iterable, read once.
        unique_id: Seeds the draw; bytes as they are, any other value by its `str`.

    Returns:
        The catalog.

    Raises:
        ValueError: If no catalog has a positive weight, an empty `catalogs` included.

    Example:
        >>> from pytrove import get_device_catalog
        >>> from pytrove.enums import PlatformDevice
        >>> ios = get_device_catalog(PlatformDevice.IOS)
        >>> random_family([ios]) is ios
        True
    """
    catalogs = tuple(catalogs)

    if not any(c.weight > 0 for c in catalogs):
        msg = "random_family: needs at least one catalog with a positive weight"
        raise ValueError(msg)

    return _rng(unique_id).choices(catalogs, weights=[c.weight for c in catalogs], k=1)[0]


__all__ = (
    "DeviceCatalog",
    "random_family",
)
