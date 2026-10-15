"""Loading a bundled device catalog and resolving its weights; the data says what exists."""

from __future__ import annotations as _annotations

from dataclasses import dataclass, field
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any, Final

from ...files_tools import load_json

_DATA_DIR: Final[Path] = Path(__file__).parents[2] / "data" / "devices"
"""One JSON catalog per platform; read on first use only."""

_SCHEMA: Final[int] = 1
"""The catalog layout version; must equal `tools/device_catalogs/src/shared.py::SCHEMA`."""

_HALF_LIFE_DAYS: Final[float] = 730.0
"""Days over which a device's or version's recency weight halves."""

_MIN_WEIGHT: Final[float] = 1e-4
"""The floor every weight is raised to, so nothing becomes impossible."""

GROUP_SHARES: dict[str, float] = {
    # Android retail brands
    "samsung": 34.0, 
    "xiaomi": 12.0, 
    "redmi": 8.0, 
    "poco": 4.0, 
    "motorola": 8.0, 
    "oneplus": 4.0, 
    "google": 4.0, 
    "oppo": 11.0, 
    "vivo": 9.0, 
    "realme": 5.0, 
    # Desktop vendors
    "Lenovo": 25.0, 
    "HP": 22.0, 
    "Dell": 17.0, 
    "ASUS": 9.0, 
    "Acer": 7.0, 
    "MSI": 4.0, 
    "Gigabyte": 3.0, 
    "ASRock": 2.0, 
    "Other": 11.0, 
    # Web: browser and OS together, since a browser's share differs per OS; Safari is not in the catalog.
    "Chrome on Windows": 50.0, 
    "Chrome on macOS": 7.0, 
    "Chrome on Linux": 4.0, 
    "Edge on Windows": 14.0, 
    "Edge on macOS": 1.0, 
    "Edge on Linux": 1.0, 
    "Firefox on Windows": 5.0, 
    "Firefox on macOS": 1.0, 
    "Firefox on Linux": 2.0, 
}
"""Approximate installed-base share per brand, vendor or browser-on-OS, split across its own devices.

Counting catalog rows instead would skew the mix (every regional Samsung
variant is listed, one Pixel). Not `Final`: reassign entries to change the mix.
"""

OS_SHARES: dict[str, float] = {"windows": 20.0, "linux": 3.0}
"""Relative OS shares on a multi-OS platform, drawn before the device. Not `Final`: meant to be adjusted."""


@dataclass(frozen=True, slots=True)
class _Device:
    """One catalog device with its resolved weights.

    Attributes:
        model: The model string.
        versions: The OS versions it can run.
        version_weights: Their weights.
        weight: The device's own weight.
        oses: The OSes it reports; empty on a single-OS platform.
        by_os: Per OS, its versions and their weights.
    """

    model: str
    versions: tuple[str, ...]
    version_weights: tuple[float, ...]
    weight: float
    oses: tuple[str, ...] = ()
    by_os: dict[str, tuple[tuple[str, ...], tuple[float, ...]]] = field(default_factory=dict, compare=False)


@dataclass(frozen=True, slots=True)
class _OsView:
    """The devices that can report one OS, with their weights.

    Attributes:
        devices: The devices.
        weights: Their weights.
    """

    devices: tuple[_Device, ...]
    weights: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class _Catalog:
    """One platform's catalog, weights resolved.

    Attributes:
        platform: The platform name.
        updated: When the data was generated.
        devices: Every usable device.
        weights: Their weights.
        oses: The OSes covered; empty for a single-OS platform.
        by_os: Per OS, the devices that can report it.
    """

    platform: str
    updated: str
    devices: tuple[_Device, ...]
    weights: tuple[float, ...] = field(compare=False)
    oses: tuple[str, ...] = ()
    by_os: dict[str, _OsView] = field(default_factory=dict, compare=False)

    def version_count(self) -> int:
        """Count the distinct OS versions across all devices.

        Returns:
            The count.
        """
        return len({v for d in self.devices for v in d.versions})


def _age_weight(released: str | None, today: date) -> float:
    """Weigh by recency: 1.0 when new, halving every `_HALF_LIFE_DAYS`.

    Args:
        released: An ISO date, or `None`.
        today: The reference day.

    Returns:
        The weight; 1.0 for an unknown or unreadable date.
    """
    if not released:
        return 1.0

    try:
        age = (today - date.fromisoformat(released[:10])).days
    except ValueError:
        return 1.0

    return max(_MIN_WEIGHT, 0.5 ** (max(age, 0) / _HALF_LIFE_DAYS))


def _load(platform: str) -> dict[str, Any]:
    """Read one platform's catalog file.

    Args:
        platform: The platform name.

    Returns:
        The parsed catalog.

    Raises:
        FileNotFoundError: If the file is missing.
        ValueError: If its schema is not `_SCHEMA`.
    """
    path = _DATA_DIR / f"{platform}.json"

    if not path.is_file():
        msg = f"no device catalog for {platform!r}: {path} is missing"
        raise FileNotFoundError(msg)

    data = load_json(path)

    if data.get("schema") != _SCHEMA:
        msg = f"{platform}.json: unsupported schema {data.get('schema')!r}, expected {_SCHEMA}"
        raise ValueError(msg)

    return data


@cache
def _catalog(platform: str) -> _Catalog:
    """Load a platform's catalog on first use and resolve every weight once.

    A device runs its explicit version list, else every version of the OSes
    it reports, else every version. Within a group, newer devices take more of
    the group's `GROUP_SHARES` slice; versions are split per OS for OS-first draws.

    Args:
        platform: The platform name.

    Returns:
        The resolved catalog.

    Raises:
        ValueError: If no device is usable.
    """
    data = _load(platform)
    today = date.today()
    versions = {v["version"]: v for v in data["versions"]}
    all_versions = tuple(versions)
    os_of = {name: entry.get("os") for name, entry in versions.items()}
    oses = tuple(dict.fromkeys(o for o in os_of.values() if o))
    group_totals: dict[str, float] = {}

    def version_weight(name: str) -> float:
        """Return a version's weight: explicit in the data, or by recency.

        Args:
            name: The version.

        Returns:
            Its weight.
        """
        entry = versions.get(name, {})
        weight = entry.get("weight")
        return float(weight) if weight is not None else _age_weight(entry.get("released"), today)

    for raw in data["devices"]:
        if group := raw.get("brand") or raw.get("vendor"):
            group_totals[group] = group_totals.get(group, 0.0) + _age_weight(raw.get("released"), today)

    devices, weights = [], []

    for raw in data["devices"]:
        device_oses = tuple(sorted(raw.get("os") or ()))
        names = (
            tuple(raw["versions"]) if raw.get("versions")
            else tuple(n for n in all_versions if os_of.get(n) in device_oses) if device_oses
            else all_versions
        )

        if not names:
            continue

        weight = raw.get("weight")

        if weight is None:
            weight = _age_weight(raw.get("released"), today)
            group = raw.get("brand") or raw.get("vendor")

            if group and group_totals.get(group):
                weight *= GROUP_SHARES.get(group, 1.0) / group_totals[group]

        weight = max(float(weight), _MIN_WEIGHT)
        version_weights = tuple(version_weight(n) for n in names)
        by_os: dict[str, tuple[tuple[str, ...], tuple[float, ...]]] = {}

        if oses:
            for name, w in zip(names, version_weights):
                if system := os_of.get(name):
                    current = by_os.get(system, ((), ()))
                    by_os[system] = (current[0] + (name,), current[1] + (w,))

        devices.append(_Device(raw["model"], names, version_weights, weight, device_oses or tuple(sorted(by_os)), by_os))
        weights.append(weight)

    if not devices:
        msg = f"{platform}.json lists no usable devices"
        raise ValueError(msg)

    by_os_view = {
        system: _OsView(tuple(members), tuple(d.weight for d in members))
        for system in oses
        if (members := [d for d in devices if system in d.by_os])
    }

    return _Catalog(platform, data.get("updated", ""), tuple(devices), tuple(weights), tuple(by_os_view), by_os_view)


__all__ = (
    "_Catalog",
    "_Device",
    "_OsView",
    "_age_weight",
    "_catalog",
    "_load",
    "_DATA_DIR",
    "_HALF_LIFE_DAYS",
    "_MIN_WEIGHT",
    "_SCHEMA",
    "GROUP_SHARES",
    "OS_SHARES",
)
