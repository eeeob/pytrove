"""Loading a bundled device catalog and resolving its weights; the data says what exists."""

from __future__ import annotations as _annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Final

from ...constants import DEVICE_CATALOGS_DIR
from ...files_tools import read_json

_SCHEMA: Final[int] = 1
"""The catalog layout version; must equal `devtools/device_catalogs/src/shared.py::SCHEMA`."""

_HALF_LIFE_DAYS: Final[float] = 730.0
"""Days over which a device's or version's recency weight halves."""

_MIN_WEIGHT: Final[float] = 1e-4
"""The floor every device and version weight is raised to, so nothing becomes impossible."""

_ISO_DATE: Final[re.Pattern[str]] = re.compile(r"\d{4}-\d{2}-\d{2}")
"""The one date form read alike on every Python; 3.11+ `date.fromisoformat` also takes others."""

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
variant is listed, one Pixel). Not `Final`: reassign entries to change the mix,
before a catalog's first draw or lookup. A catalog applies the shares once, when
it is built, and keeps the result, so a later edit does not reach a loaded one.
"""

OS_SHARES: dict[str, float] = {"windows": 20.0, "linux": 3.0}
"""Relative OS shares on a multi-OS platform, drawn before the device; a missing OS weighs 1.0.

Not `Final`: meant to be adjusted. Read on every draw, so an edit applies at once.
"""


@dataclass(frozen=True, slots=True)
class _Device:
    """One catalog device with its resolved weights."""

    model: str
    """The model string, as the client reports it."""

    versions: tuple[str, ...]
    """The OS versions it can run."""

    version_weights: tuple[float, ...]
    """One weight per entry of `versions`: explicit in the data, or by recency; floored."""

    weight: float
    """The device's own weight, scaled by its group share and floored at `_MIN_WEIGHT`."""

    oses: tuple[str, ...] = ()
    """The OSes it reports; empty on a single-OS platform."""

    by_os: dict[str, tuple[tuple[str, ...], tuple[float, ...]]] = field(
        default_factory=dict, compare=False
    )
    """Per OS, the subset of `versions` and their weights; empty on a single-OS platform."""

    def os_versions(self, os: str | None) -> tuple[str, ...]:
        """Return the versions it runs under `os`.

        Args:
            os: An OS in `by_os`, or `None` for every version.

        Returns:
            The versions.

        Raises:
            KeyError: If `os` is not in `by_os`.
        """
        return self.versions if os is None else self.by_os[os][0]


@dataclass(frozen=True, slots=True)
class _OsView:
    """The devices that can report one OS, with their weights."""

    devices: tuple[_Device, ...]
    """The devices whose `by_os` holds the OS."""

    weights: tuple[float, ...]
    """One weight per entry of `devices`, each device's own."""


@dataclass(frozen=True, slots=True)
class _Catalog:
    """One platform's catalog, weights resolved."""

    platform: str
    """The platform name, also the data file's stem."""

    devices: tuple[_Device, ...]
    """Every usable device."""

    weights: tuple[float, ...] = field(compare=False)
    """One weight per entry of `devices`, for a single draw across the platform."""

    oses: tuple[str, ...] = ()
    """The OSes covered, in the order the data lists them; empty for a single-OS platform."""

    by_os: dict[str, _OsView] = field(default_factory=dict, compare=False)
    """Per OS, the devices that can report it; only OSes with at least one device."""


def _age_weight(released: str | None, today: date) -> float:
    """Weigh by recency: 1.0 when new, halving every `_HALF_LIFE_DAYS`.

    Args:
        released: A `YYYY-MM-DD` date, optionally followed by a time, or `None`.
        today: The reference day.

    Returns:
        The weight; 1.0 for an unknown or unreadable date.
    """
    if not released or not _ISO_DATE.fullmatch(released[:10]):
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
        ValueError: If it is not a JSON object, or its schema is not `_SCHEMA`.
    """
    path = DEVICE_CATALOGS_DIR / f"{platform}.json"

    if not path.is_file():
        msg = f"no device catalog for {platform!r}: {path} is missing"
        raise FileNotFoundError(msg)

    data = read_json(path)

    if not isinstance(data, dict):
        msg = f"{platform}.json: expected a JSON object, got {type(data).__name__}"
        raise ValueError(msg)

    if data.get("schema") != _SCHEMA:
        msg = f"{platform}.json: unsupported schema {data.get('schema')!r}, expected {_SCHEMA}"
        raise ValueError(msg)

    return data


def _build_catalog(platform: str) -> _Catalog:
    """Load a platform's catalog and resolve every weight; `DeviceCatalog` keeps the result.

    A device runs its explicit version list, else every version of the OSes it
    reports, else every version; a device with none to run is skipped. Within a
    group, the kept devices without an explicit `weight` split the group's
    `GROUP_SHARES` slice, newer ones taking more. Versions are split per OS for
    OS-first draws.

    Args:
        platform: The platform name.

    Returns:
        The resolved catalog.

    Raises:
        KeyError: If the file lacks `versions` or `devices`, a version entry its
            `version`, or a device its `model`.
        ValueError: If the file is not a catalog `_load` accepts, or no device is usable.
    """
    data = _load(platform)
    today = date.today()
    versions = {v["version"]: v for v in data["versions"]}
    all_versions = tuple(versions)
    os_of = {name: entry.get("os") for name, entry in versions.items()}
    oses = tuple(dict.fromkeys(o for o in os_of.values() if o))

    def version_weight(name: str) -> float:
        """Return a version's weight: explicit in the data, or by recency, then floored.

        Args:
            name: The version.

        Returns:
            Its weight; 1.0 for a version the catalog does not describe.
        """
        entry = versions.get(name, {})
        weight = entry.get("weight")
        weight = float(weight) if weight is not None else _age_weight(entry.get("released"), today)
        return max(weight, _MIN_WEIGHT)

    # Each kept device: the raw entry, its versions, its OSes, its group (`None` when its
    # weight is explicit, which no share scales) and its unscaled weight.
    kept: list[tuple[dict[str, Any], tuple[str, ...], tuple[str, ...], str | None, float]] = []
    group_totals: dict[str, float] = {}

    for raw in data["devices"]:
        # Declared apart: `ty` solves `sorted(<Any> or ())` from the `()` arm alone and
        # would type `device_oses` as the always-empty `tuple[()]`.
        raw_oses: list[str] = raw.get("os") or []
        device_oses = tuple(sorted(raw_oses))
        names = (
            tuple(raw["versions"])
            if raw.get("versions")
            else tuple(n for n in all_versions if os_of.get(n) in device_oses)
            if device_oses
            else all_versions
        )

        if not names:
            continue

        explicit = raw.get("weight")
        group = None if explicit is not None else raw.get("brand") or raw.get("vendor")
        weight = (
            float(explicit) if explicit is not None else _age_weight(raw.get("released"), today)
        )
        kept.append((raw, names, device_oses, group, weight))

        if group:
            group_totals[group] = group_totals.get(group, 0.0) + weight

    devices, weights = [], []

    for raw, names, device_oses, group, own_weight in kept:
        weight = (
            own_weight * GROUP_SHARES.get(group, 1.0) / group_totals[group] if group else own_weight
        )
        weight = max(weight, _MIN_WEIGHT)
        version_weights = tuple(map(version_weight, names))
        by_os: dict[str, tuple[tuple[str, ...], tuple[float, ...]]] = {}

        if oses:
            for name, w in zip(names, version_weights, strict=True):
                if system := os_of.get(name):
                    current = by_os.get(system, ((), ()))
                    by_os[system] = (current[0] + (name,), current[1] + (w,))

        devices.append(
            _Device(
                raw["model"],
                names,
                version_weights,
                weight,
                device_oses or tuple(sorted(by_os)),
                by_os,
            )
        )
        weights.append(weight)

    if not devices:
        msg = f"{platform}.json lists no usable devices"
        raise ValueError(msg)

    by_os_view = {
        system: _OsView(tuple(members), tuple(d.weight for d in members))
        for system in oses
        if (members := [d for d in devices if system in d.by_os])
    }

    return _Catalog(platform, tuple(devices), tuple(weights), tuple(by_os_view), by_os_view)


__all__ = (
    "_Catalog",
    "_Device",
    "_OsView",
    "_age_weight",
    "_build_catalog",
    "_load",
    "_HALF_LIFE_DAYS",
    "_ISO_DATE",
    "_MIN_WEIGHT",
    "_SCHEMA",
    "GROUP_SHARES",
    "OS_SHARES",
)
