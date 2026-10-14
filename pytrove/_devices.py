from __future__ import annotations as _annotations

from dataclasses import dataclass, field
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any, ClassVar, Final, Iterable

import hashlib
import os as _os
import random

from .files_tools import load_json


# One file per platform under data/devices, so a catalog can be refreshed
# without touching code. Bump _SCHEMA only when the layout changes.
_DATA_DIR: Final = Path(__file__).parent / "data" / "devices"
_SCHEMA: Final = 1

# Recency decay. A device or OS version loses half its weight every
# `_HALF_LIFE_DAYS`, which is what keeps a freshly released phone far more
# likely than a six-year-old one without ever excluding the old one.
_HALF_LIFE_DAYS: Final[float] = 730.0
_MIN_WEIGHT: Final[float] = 1e-4

# Shares used to balance groups that the catalogs over- or under-represent:
# Google lists every regional variant of a Samsung phone and only one of a
# Pixel, so counting rows would make Samsung dominate far beyond its real
# share. Each group's share is split across its own devices instead.
#
# These are approximate installed-base shares, not measurements. Override
# `GROUP_SHARES` to change the mix.
GROUP_SHARES: dict[str, float] = {
    # Android retail brands
    "samsung": 34.0, "xiaomi": 12.0, "redmi": 8.0, "poco": 4.0,
    "motorola": 8.0, "oneplus": 4.0, "google": 4.0,
    "oppo": 11.0, "vivo": 9.0, "realme": 5.0,
    # Desktop vendors
    "Lenovo": 25.0, "HP": 22.0, "Dell": 17.0, "ASUS": 9.0, "Acer": 7.0,
    "MSI": 4.0, "Gigabyte": 3.0, "ASRock": 2.0, "Other": 11.0,
    # Web: the browser and the operating system together, because a browser's
    # share on Windows says nothing about its share on Linux. Safari is absent
    # from the catalog, so macOS is under-weighted here by exactly its share.
    "Chrome on Windows": 50.0, "Chrome on macOS": 7.0, "Chrome on Linux": 4.0,
    "Edge on Windows": 14.0, "Edge on macOS": 1.0, "Edge on Linux": 1.0,
    "Firefox on Windows": 5.0, "Firefox on macOS": 1.0, "Firefox on Linux": 2.0,
}

# Telegram reports every desktop OS as one platform, so `DesktopDevice` holds
# them and the OS is drawn here. Shares are relative within a platform.
OS_SHARES: dict[str, float] = {"windows": 20.0, "linux": 3.0}


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """One plausible device: the model string and an OS version it can run."""

    model: str
    version: str

    def __str__(self) -> str:
        return f"{self.model} {self.version}"

    def to_dict(self) -> dict[str, str]:
        return {"device_model": self.model, "system_version": self.version}


@dataclass(frozen=True, slots=True)
class _Device:
    model: str
    versions: tuple[str, ...]
    version_weights: tuple[float, ...]
    weight: float
    #: The operating systems this model can report, empty on single-OS
    #: platforms where the question does not arise.
    oses: tuple[str, ...] = ()
    #: os -> (versions of that os, their weights). Only filled when the
    #: platform has more than one.
    by_os: dict[str, tuple[tuple[str, ...], tuple[float, ...]]] = field(
        default_factory=dict, compare=False)


@dataclass(frozen=True, slots=True)
class _OsView:
    """The devices that can report one OS, with their weights."""

    devices: tuple[_Device, ...]
    weights: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class _Catalog:
    platform: str
    updated: str
    devices: tuple[_Device, ...]
    weights: tuple[float, ...] = field(compare=False)
    #: Every OS this platform covers, empty when it covers one.
    oses: tuple[str, ...] = ()
    by_os: dict[str, _OsView] = field(default_factory=dict, compare=False)

    def version_count(self) -> int:
        return len({v for d in self.devices for v in d.versions})


def _age_weight(released: str | None, today: date) -> float:
    """Recency weight for an ISO date: 1.0 when brand new, halving every
    `_HALF_LIFE_DAYS`. An unknown date is treated as neutral."""

    if not released:
        return 1.0

    try:
        age = (today - date.fromisoformat(released[:10])).days
    except ValueError:
        return 1.0

    return max(_MIN_WEIGHT, 0.5 ** (max(age, 0) / _HALF_LIFE_DAYS))


def _load(platform: str) -> dict[str, Any]:
    path = _DATA_DIR / f"{platform}.json"

    if not path.is_file():
        raise FileNotFoundError(
            f"no device catalog for {platform!r}: {path} is missing"
        )

    data = load_json(path)

    if data.get("schema") != _SCHEMA:
        raise ValueError(
            f"{platform}.json: unsupported schema {data.get('schema')!r}, expected {_SCHEMA}"
        )

    return data


@cache
def _catalog(platform: str) -> _Catalog:
    """Load a platform's catalog and resolve every weight once.

    Each device ends up with the versions it can actually run: the explicit
    list from the data when it has one (iOS firmwares, Android SDK ranges),
    or every version belonging to an OS the device reports
    (any PC runs any Windows build), or the whole platform list when the data
    draws no such distinction.
    """

    data = _load(platform)
    today = date.today()

    versions = {v["version"]: v for v in data["versions"]}
    all_versions = tuple(versions)
    os_of = {name: entry.get("os") for name, entry in versions.items()}
    oses = tuple(dict.fromkeys(o for o in os_of.values() if o))

    def version_weight(name: str) -> float:
        entry = versions.get(name, {})
        weight = entry.get("weight")
        return (float(weight) if weight is not None
                else _age_weight(entry.get("released"), today))

    def device_versions(raw: dict[str, Any], device_oses: tuple[str, ...]) -> tuple[str, ...]:
        explicit = raw.get("versions")
        if explicit:
            return tuple(explicit)
        if device_oses:
            return tuple(n for n in all_versions if os_of.get(n) in device_oses)
        return all_versions

    def group_of(raw: dict[str, Any]) -> str | None:
        return raw.get("brand") or raw.get("vendor")

    # Recency totals per group, so a group's share can be split across its own
    # devices by how recent each one is. Without this, a brand that happens to
    # list more new variants would drift past the share it was given.
    group_totals: dict[str, float] = {}
    for raw in data["devices"]:
        group = group_of(raw)
        if group:
            group_totals[group] = group_totals.get(group, 0.0) + _age_weight(
                raw.get("released"), today
            )

    devices, weights = [], []
    for raw in data["devices"]:
        device_oses = tuple(sorted(raw.get("os") or ()))
        names = device_versions(raw, device_oses)
        if not names:
            continue

        weight = raw.get("weight")
        if weight is None:
            weight = _age_weight(raw.get("released"), today)
            group = group_of(raw)
            if group and group_totals.get(group):
                # The group keeps exactly its share; inside it, newer devices
                # take more of that share than older ones.
                weight *= GROUP_SHARES.get(group, 1.0) / group_totals[group]
        weight = max(float(weight), _MIN_WEIGHT)

        version_weights = tuple(version_weight(n) for n in names)

        # Split the device's versions by OS, so a draw can pick the OS first
        # and keep each one's share exact instead of letting the per-device
        # version mix decide it.
        by_os: dict[str, tuple[tuple[str, ...], tuple[float, ...]]] = {}
        if oses:
            for name, w in zip(names, version_weights):
                system = os_of.get(name)
                if not system:
                    continue
                current = by_os.get(system, ((), ()))
                by_os[system] = (current[0] + (name,), current[1] + (w,))

        devices.append(_Device(
            model=raw["model"],
            versions=names,
            version_weights=version_weights,
            weight=weight,
            oses=device_oses or tuple(sorted(by_os)),
            by_os=by_os,
        ))
        weights.append(weight)

    if not devices:
        raise ValueError(f"{platform}.json lists no usable devices")

    by_os_view: dict[str, _OsView] = {}
    for system in oses:
        members = [d for d in devices if system in d.by_os]
        if members:
            by_os_view[system] = _OsView(
                tuple(members), tuple(d.weight for d in members))

    return _Catalog(platform, data.get("updated", ""), tuple(devices), tuple(weights),
                    tuple(by_os_view), by_os_view)


def _rng(unique_id: Any = None) -> random.Random:
    """A generator seeded from `unique_id`, or from system entropy without one.

    The same id always yields the same stream, so one identity keeps getting
    the same device while the weighting below still applies.
    """

    if unique_id is None:
        return random.Random(_os.urandom(32))

    if not isinstance(unique_id, (str, bytes, bytearray)):
        unique_id = str(unique_id)
    if isinstance(unique_id, str):
        unique_id = unique_id.encode("utf-8")

    return random.Random(int(hashlib.sha256(unique_id).hexdigest(), 16))


class SystemInfo:
    """Base for the per-platform device catalogs below.

    random_device() draws a device and then an OS version that device can
    really run, both weighted towards what is actually in use: newer hardware
    and newer releases come up more often, and a brand's regional variants
    share one slice instead of multiplying it.

    A platform that covers several operating systems (`DesktopDevice`) draws
    the OS first, by `OS_SHARES`, then a device that can report it. Pass `os`
    to pin that choice.

    Passing `unique_id` makes the draw deterministic -- the same id always maps
    to the same device -- which is why it is still called random_device: the
    deterministic case is the opt-in one.
    """

    platform: ClassVar[str]
    #: Relative likelihood of this platform when no platform is requested.
    #: Approximate Telegram-client mix, mobile-heavy; override to change it.
    platform_weight: ClassVar[float] = 1.0

    @classmethod
    def catalog(cls) -> _Catalog:
        return _catalog(cls.platform)

    @classmethod
    def oses(cls) -> tuple[str, ...]:
        """Every OS this platform covers, empty when it covers only one."""

        return cls.catalog().oses

    @classmethod
    def _devices_for(cls, os: str | None) -> tuple[_Device, ...]:
        catalog = cls.catalog()
        if os is None:
            return catalog.devices

        view = catalog.by_os.get(os)
        if view is None:
            raise ValueError(
                f"{cls.platform} has no {os!r} devices; known: {catalog.oses or '()'}"
            )
        return view.devices

    @classmethod
    def devices(cls, os: str | None = None) -> tuple[DeviceInfo, ...]:
        """Every (model, version) pair this platform can report."""

        return tuple(
            DeviceInfo(device.model, version)
            for device in cls._devices_for(os)
            for version in (device.by_os[os][0] if os else device.versions)
        )

    @classmethod
    def models(cls, os: str | None = None) -> tuple[str, ...]:
        return tuple(device.model for device in cls._devices_for(os))

    @classmethod
    def versions(cls, os: str | None = None) -> tuple[str, ...]:
        seen = dict.fromkeys(
            version
            for device in cls._devices_for(os)
            for version in (device.by_os[os][0] if os else device.versions)
        )
        return tuple(seen)

    @classmethod
    def find_device(cls, model: str, version: str | None = None) -> DeviceInfo | None:
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
        catalog = cls.catalog()
        rng = _rng(unique_id)

        if os is None and catalog.oses:
            # Pick the OS by share first: letting device weights decide
            # would tie the OS mix to how many models each OS happens to
            # list, and a Linux-only board would then drag it around.
            os = rng.choices(
                catalog.oses,
                weights=[OS_SHARES.get(system, 1.0) for system in catalog.oses],
                k=1,
            )[0]

        if os is None:
            device = rng.choices(catalog.devices, weights=catalog.weights, k=1)[0]
            names, version_weights = device.versions, device.version_weights
        else:
            view = catalog.by_os.get(os)
            if view is None:
                raise ValueError(
                    f"{cls.platform} has no {os!r} devices; known: {catalog.oses or '()'}"
                )
            device = rng.choices(view.devices, weights=view.weights, k=1)[0]
            names, version_weights = device.by_os[os]

        version = rng.choices(names, weights=version_weights, k=1)[0]

        return DeviceInfo(device.model, version)


class DesktopDevice(SystemInfo):
    """Windows and Linux, which Telegram reports as one platform.

    The same PC appears once and can report either, so the hardware pool is
    stored once and tagged with both.

    Every string follows Telegram Desktop, which is the reference client here:
    its `lib_base` rules decide what a machine may report, and
    `tests/tools/tg/test_devices_data.py` checks each stored model against a port of
    them. Unigram is not modelled -- it reports the raw product name and a bare
    "Windows 11" -- and macOS is left out because its two official clients send
    different version strings, the native one's bare "26.1" matching no
    client's icon rules.
    """

    platform = "desktop"
    platform_weight = 26.0


class WebDevice(SystemInfo):
    """A browser running Telegram Web, which Telegram reports as its own
    platform (`PlatformDevice.WEB`).

    The model is the whole `navigator.userAgent` and the version is
    `navigator.platform`, because a browser has no device name to give -- both
    official web clients send those two values verbatim. Each user agent lists
    exactly one version: the two describe the same machine, so a UA claiming
    Windows cannot report "MacIntel".
    """

    platform = "web"
    platform_weight = 5.0


class AndroidDevice(SystemInfo):
    platform = "android"
    platform_weight = 50.0


class iOSDevice(SystemInfo):
    platform = "ios"
    platform_weight = 19.0


def random_family(
    families: Iterable[type[SystemInfo]],
    unique_id: Any = None,
) -> type[SystemInfo]:
    """Pick one platform out of `families`, weighted by `platform_weight`."""

    families = tuple(families)
    rng = _rng(unique_id)

    return rng.choices(families, weights=[f.platform_weight for f in families], k=1)[0]


__all__ = (
    "DeviceInfo",
    "SystemInfo",
    "DesktopDevice",
    "WebDevice",
    "AndroidDevice",
    "iOSDevice",
    "random_family",
)
