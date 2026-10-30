from __future__ import annotations as _annotations

import collections
import itertools
import random
import subprocess
from typing import TYPE_CHECKING, Any
import sys

import pytest

from pytrove import get_device_catalog, is_known_device, random_device
from pytrove.enums import PlatformDevice
from pytrove.models import DeviceInfo
from pytrove.device_tools._internal.catalog import _load, OS_SHARES
from pytrove.device_tools.draw import _DEVICES, _MULTI_OS_PLATFORMS
from pytrove.device_tools.families import DeviceCatalog

if TYPE_CHECKING:
    from collections.abc import Iterator

OS_PIN_PROBE = """
from pytrove import random_device
from pytrove.device_tools.draw import _DEVICES
from pytrove.enums import PlatformDevice
random_device(os="linux")
loaded = {p for p, c in _DEVICES.items() if "_data" in c.__dict__}
assert loaded == {PlatformDevice.DESKTOP}, loaded
"""


@pytest.fixture(autouse=True)
def _restore_global_random() -> Iterator[None]:
    """Undo the seeding some tests do, so no other test inherits a fixed stream."""
    state = random.getstate()
    yield
    random.setstate(state)


def _seeded(*args: Any, **kwargs: Any) -> Any:
    """Call `random_device` on a freshly seeded global generator, so two calls compare."""
    random.seed(0)
    return random_device(*args, **kwargs)


# --- the platform catalogs -------------------------------------------------


def test_devices_hold_one_catalog_per_platform_at_its_share() -> None:
    assert set(_DEVICES) == set(PlatformDevice)
    assert all(catalog.platform is platform for platform, catalog in _DEVICES.items())
    assert {platform: catalog.weight for platform, catalog in _DEVICES.items()} == {
        PlatformDevice.ANDROID: 50.0,
        PlatformDevice.IOS: 19.0,
        PlatformDevice.DESKTOP: 26.0,
        PlatformDevice.WEB: 5.0,
    }


@pytest.mark.parametrize("platform", list(PlatformDevice))
def test_get_device_catalog_returns_the_same_object_each_call(platform: PlatformDevice) -> None:
    catalog = get_device_catalog(platform)

    assert isinstance(catalog, DeviceCatalog)
    assert catalog is _DEVICES[platform]
    assert catalog is get_device_catalog(platform)


def test_multi_os_platforms_are_exactly_those_whose_catalog_reports_oses() -> None:
    assert {p for p, c in _DEVICES.items() if c.oses()} == _MULTI_OS_PLATFORMS
    assert _MULTI_OS_PLATFORMS == frozenset({PlatformDevice.DESKTOP})


def test_get_device_catalog_refuses_an_unknown_platform() -> None:
    with pytest.raises(KeyError):
        get_device_catalog("nope")


# --- random_device ---------------------------------------------------------


@pytest.mark.parametrize("platform", list(PlatformDevice))
def test_random_device_works_for_every_platform(platform: PlatformDevice) -> None:
    assert is_known_device(random_device(platform), platform)


def test_random_device_returns_a_device_info_by_default() -> None:
    assert isinstance(random_device(PlatformDevice.IOS), DeviceInfo)


@pytest.mark.parametrize("platform", list(PlatformDevice))
def test_random_device_pinned_draws_only_from_that_platform(platform: PlatformDevice) -> None:
    for _ in range(20):
        assert is_known_device(random_device(platform), platform)


@pytest.mark.parametrize("platform", list(PlatformDevice))
def test_random_device_pinned_matches_the_catalog_draw(platform: PlatformDevice) -> None:
    random.seed(0)
    expected = _DEVICES[platform].random_device()

    assert _seeded(platform) == expected


def test_random_device_takes_no_unique_id() -> None:
    # A seed promised one device per account, but any edit to the bundled data moved most
    # accounts to another; a drawn device is stored instead.
    with pytest.raises(TypeError):
        random_device(unique_id="acc-1")  # ty: ignore[no-matching-overload]  # The removed parameter must fail.

    with pytest.raises(TypeError):
        random_device(PlatformDevice.IOS, False, "acc-1")  # ty: ignore[no-matching-overload]  # Nor positionally.


def test_unpinned_draws_follow_every_share() -> None:
    # Each pick (platform, OS, device, version) takes its own number; reusing one for two
    # of them would confine each platform to a slice of its catalog and skew the OS mix.
    random.seed(0)
    n = 5000
    platform_of = {d.model: p for p, c in _DEVICES.items() for d in c._data.devices}
    os_of = {v["version"]: v["os"] for v in _load("desktop")["versions"]}
    draws = [random_device() for _ in range(n)]
    platforms = collections.Counter(platform_of[d.device_model] for d in draws)
    total = sum(c.weight for c in _DEVICES.values())

    for platform, catalog in _DEVICES.items():
        assert abs(platforms[platform] / n - catalog.weight / total) < 0.03, platforms

    desktop = [d for d in draws if platform_of[d.device_model] is PlatformDevice.DESKTOP]
    linux = sum(os_of[d.system_version] == "linux" for d in desktop) / len(desktop)
    assert abs(linux - OS_SHARES["linux"] / sum(OS_SHARES.values())) < 0.04

    android = _DEVICES[PlatformDevice.ANDROID]._data
    ends = list(itertools.accumulate(android.weights))
    lower = {d.model for d, end in zip(android.devices, ends, strict=True) if end <= ends[-1] / 2}
    expected = max(end for end in ends if end <= ends[-1] / 2) / ends[-1]
    drawn = [d for d in draws if platform_of[d.device_model] is PlatformDevice.ANDROID]
    observed = sum(d.device_model in lower for d in drawn) / len(drawn)
    assert abs(observed - expected) < 0.05, (observed, expected)


def test_random_device_varies_between_calls() -> None:
    assert len({random_device() for _ in range(50)}) > 1


def test_random_device_to_tuple_is_model_then_version() -> None:
    device = _seeded(PlatformDevice.ANDROID)
    model, version = _seeded(PlatformDevice.ANDROID, to_tuple=True)

    assert (model, version) == device.to_tuple()


def test_random_device_takes_to_tuple_positionally() -> None:
    assert _seeded(PlatformDevice.IOS, True) == _seeded(PlatformDevice.IOS).to_tuple()


@pytest.mark.parametrize("flag", [True, False])
def test_random_device_takes_a_runtime_bool_flag(flag: bool) -> None:
    device = _seeded(PlatformDevice.IOS)

    assert _seeded(PlatformDevice.IOS, to_tuple=flag) == (device.to_tuple() if flag else device)
    assert _seeded(PlatformDevice.IOS, to_dict=flag) == (device.to_dict() if flag else device)


def test_random_device_to_dict_is_the_device_dict() -> None:
    assert _seeded(PlatformDevice.WEB, to_dict=True) == _seeded(PlatformDevice.WEB).to_dict()


def test_random_device_refuses_both_shapes() -> None:
    with pytest.raises(TypeError, match="cannot both be True"):
        random_device(to_tuple=True, to_dict=True)


def test_random_device_pinning_an_os_draws_only_platforms_that_report_it() -> None:
    linux = set(get_device_catalog(PlatformDevice.DESKTOP).versions(os="linux"))

    for _ in range(30):
        device = random_device(os="linux")
        assert is_known_device(device, PlatformDevice.DESKTOP)
        assert device.system_version in linux


def test_random_device_pinning_an_os_loads_only_the_platforms_that_report_it() -> None:
    subprocess.run([sys.executable, "-c", OS_PIN_PROBE], check=True)


def test_random_device_pinning_an_os_returns_every_shape() -> None:
    expected = _seeded(os="linux")

    assert _seeded(to_tuple=True, os="linux") == expected.to_tuple()
    assert _seeded(to_dict=True, os="linux") == expected.to_dict()
    assert is_known_device(_seeded(PlatformDevice.DESKTOP, os="linux"), PlatformDevice.DESKTOP)


def test_random_device_refuses_an_os_no_platform_reports() -> None:
    with pytest.raises(ValueError, match="no platform reports the OS 'haiku'"):
        random_device(os="haiku")


def test_random_device_refuses_an_os_the_pinned_platform_lacks() -> None:
    with pytest.raises(ValueError, match="android has no 'linux' devices"):
        random_device(PlatformDevice.ANDROID, os="linux")


# --- is_known_device -------------------------------------------------------


def test_is_known_device_accepts_a_device_or_its_tuple() -> None:
    device = random_device(PlatformDevice.IOS)

    assert is_known_device(device)
    assert is_known_device(device.to_tuple())
    assert is_known_device(device, PlatformDevice.IOS)


def test_is_known_device_rejects_an_unknown_or_misplaced_pair() -> None:
    device = random_device(PlatformDevice.IOS)

    assert not is_known_device(("no such model", "SDK 35"))
    assert not is_known_device(DeviceInfo(device.device_model, "0.0"))
    assert not is_known_device(device, PlatformDevice.ANDROID)


def test_is_known_device_rejects_a_model_with_another_oss_version() -> None:
    desktop = get_device_catalog(PlatformDevice.DESKTOP)
    assert "KVM" in desktop.models(os="linux")
    assert "KVM" not in desktop.models(os="windows")
    assert "Windows 11 x64" in desktop.versions(os="windows")

    assert not is_known_device(("KVM", "Windows 11 x64"))
    assert not is_known_device(("KVM", "Windows 11 x64"), PlatformDevice.DESKTOP)


@pytest.mark.parametrize("device", [("model",), ("model", "1.0", "extra")])
def test_is_known_device_refuses_a_tuple_that_is_not_a_pair(device: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="values to unpack"):
        is_known_device(device)


def test_is_known_device_refuses_an_unknown_platform() -> None:
    with pytest.raises(KeyError):
        is_known_device(("model", "1.0"), "nope")
