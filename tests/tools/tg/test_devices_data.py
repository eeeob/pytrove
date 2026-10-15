import collections
import json
import re

import pytest

from pytrove.models import DeviceInfo
from pytrove.tg_tools._internal.catalog import _load, _DATA_DIR, _SCHEMA, GROUP_SHARES, OS_SHARES
from pytrove.tg_tools._internal.families import (
    AndroidDevice,
    DesktopDevice,
    SystemInfo,
    WebDevice,
    iOSDevice,
    random_family,
)

#: Only present after a build; the tests that need it skip when it is absent.
PLAY_CATALOG = (_DATA_DIR.parents[2] / "tools" / "device_catalogs"
                / ".cache" / "play_devices.csv")

#: tools/ is dev-only and ships in no wheel, so importing it is best-effort.
#: This one module is loadable on its own: it imports nothing from its package
#: precisely so this test can read it without building the whole thing.
BUILDER = (_DATA_DIR.parents[2] / "tools" / "device_catalogs"
           / "src" / "libbase.py")


def _lib_base():
    """The builder's port of lib_base, loaded by path."""

    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("_libbase_for_tests", BUILDER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module          # dataclasses needs it importable
    spec.loader.exec_module(module)
    return module.LibBase

ALL_PLATFORMS = (DesktopDevice, AndroidDevice, iOSDevice, WebDevice)
IDS = [p.platform for p in ALL_PLATFORMS]

#: Telegram reports every desktop OS as "desktop". macOS is deliberately not
#: in the catalog -- see DesktopDevice's docstring.
DESKTOP_OSES = ("windows", "linux")

# lib_base IsDeviceModelOk: non-empty, at most 15 chars; HP names keep up to 32.
MAX_MODEL = 15
MAX_HP_MODEL = 32


def _duplicates(items):
    return [item for item, count in collections.Counter(items).items() if count > 1]


@pytest.fixture(scope="module", params=ALL_PLATFORMS, ids=IDS)
def platform(request):
    return request.param


@pytest.fixture(scope="module")
def desktop():
    return _load("desktop")


# --- data file shape -------------------------------------------------------

def test_every_platform_has_its_own_data_file():
    files = {p.stem for p in _DATA_DIR.glob("*.json")}
    assert files == {p.platform for p in ALL_PLATFORMS}


def test_data_file_declares_the_schema_and_update_date(platform):
    data = _load(platform.platform)

    assert data["schema"] == _SCHEMA
    assert data["platform"] == platform.platform
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["updated"])


def test_single_os_platform_documents_itself_at_the_top_level():
    for name in ("android", "ios"):
        data = _load(name)

        assert "os" not in data
        assert data["model_format"] and data["version_format"]
        assert data["sources"] and all(s.startswith("http") for s in data["sources"])
        assert data["notes"]


def test_desktop_documents_every_os_separately(desktop):
    # The formats and caveats genuinely differ per OS -- Windows reads the
    # registry and names an architecture, Linux reads /sys/class/dmi and names
    # the desktop session -- so one shared description would lose that.
    assert set(desktop["os"]) == set(DESKTOP_OSES)
    assert not {"model_format", "version_format", "sources", "notes"} & set(desktop)

    for name, doc in desktop["os"].items():
        assert doc["model_format"] and doc["version_format"], name
        assert doc["sources"] and all(s.startswith("http") for s in doc["sources"]), name
        assert doc["notes"], name


def test_data_file_is_valid_json_without_duplicate_models(platform):
    data = json.loads((_DATA_DIR / f"{platform.platform}.json").read_text(encoding="utf-8"))

    assert _duplicates([d["model"] for d in data["devices"]]) == []
    assert _duplicates([v["version"] for v in data["versions"]]) == []


# --- os tagging ------------------------------------------------------------

def test_desktop_tags_every_device_and_version_with_a_known_os(desktop):
    for version in desktop["versions"]:
        assert version["os"] in DESKTOP_OSES, version

    for device in desktop["devices"]:
        assert device["os"], device["model"]
        assert set(device["os"]) <= set(DESKTOP_OSES), device


def test_pc_models_are_stored_once_for_both_windows_and_linux(desktop):
    # The hardware pool is shared: the same machine reports either OS, so a
    # model carrying both tags is one row rather than two files' worth.
    shared = [d for d in desktop["devices"] if set(d["os"]) == {"windows", "linux"}]

    assert len(shared) > 500
    assert all("versions" not in d for d in shared), "a PC runs any build of either OS"


def test_single_os_platforms_declare_no_os_tag():
    for name in ("android", "ios", "web"):
        assert all("os" not in d for d in _load(name)["devices"])
        assert all("os" not in v for v in _load(name)["versions"])


# --- web -------------------------------------------------------------------

#: Each browser's frozen template, as its own engine builds it. Only the major
#: version is a capture group because only the major still moves: Chromium pins
#: its minor to 0.0.0 and its platform token per OS, Gecko pins the Windows
#: version to 10.0, and Microsoft appends Edg/ to the Chromium string.
WEB_AGENTS = {
    "Chrome": re.compile(
        r"Mozilla/5\.0 \((?P<token>[^)]+)\) AppleWebKit/537\.36 "
        r"\(KHTML, like Gecko\) Chrome/(?P<major>\d+)\.0\.0\.0 Safari/537\.36"),
    "Edge": re.compile(
        r"Mozilla/5\.0 \((?P<token>[^)]+)\) AppleWebKit/537\.36 "
        r"\(KHTML, like Gecko\) Chrome/(?P<major>\d+)\.0\.0\.0 Safari/537\.36"
        r" Edg/\d+\.0\.0\.0"),
    "Firefox": re.compile(
        r"Mozilla/5\.0 \((?P<token>[^)]+); rv:(?P<major>\d+)\.0\) "
        r"Gecko/20100101 Firefox/\d+\.0"),
}

#: What the UA claims -> what navigator.platform must say for the same machine,
#: from NavigatorBase::platform(). Chromium and Gecko spell macOS differently.
WEB_PAIRS = {
    "Windows NT 10.0; Win64; x64": "Win32",
    "Macintosh; Intel Mac OS X 10_15_7": "MacIntel",
    "Macintosh; Intel Mac OS X 10.15": "MacIntel",
    "X11; Linux x86_64": "Linux x86_64",
}


def test_web_models_match_their_browsers_own_frozen_template():
    for device in _load("web")["devices"]:
        pattern = WEB_AGENTS[device["browser"]]
        found = pattern.fullmatch(device["model"])

        assert found, device["model"]
        assert int(found["major"]) == device["major"], device["model"]


def test_web_user_agent_and_navigator_platform_describe_one_machine():
    # A UA claiming Windows cannot report "MacIntel", so each device lists
    # exactly one version and it is the one its own platform token implies.
    for device in _load("web")["devices"]:
        token = WEB_AGENTS[device["browser"]].fullmatch(device["model"])["token"]

        assert device["versions"] == [WEB_PAIRS[token]], device["model"]


def test_web_carries_no_safari_and_no_mobile_agent():
    # Safari is out because its Version/ token has no machine-readable feed,
    # and the catalog is desktop-only; a mobile token would need its own
    # verified navigator.platform value.
    for device in _load("web")["devices"]:
        model = device["model"]

        assert "Version/" not in model, model
        assert not re.search(r"\b(Android|iPhone|iPad|Mobile|CrOS)\b", model), model


def test_every_web_draw_is_a_real_browser_release():
    # The majors come from each vendor's own feed, so a draw must land on one
    # of them rather than on an interpolated number.
    known = {(d["browser"], d["major"]) for d in _load("web")["devices"]}

    for i in range(200):
        model = WebDevice.random_device(f"web-{i}").model
        browser = next(b for b in WEB_AGENTS
                       if WEB_AGENTS[b].fullmatch(model))
        major = int(WEB_AGENTS[browser].fullmatch(model)["major"])

        assert (browser, major) in known, model


# --- catalog integrity -----------------------------------------------------

def test_catalog_has_devices_and_versions(platform):
    catalog = platform.catalog()

    assert catalog.devices
    assert platform.versions()
    assert all(d.versions for d in catalog.devices)


def test_every_device_version_is_a_known_platform_version(platform):
    known = {v["version"] for v in _load(platform.platform)["versions"]}

    for device in platform.catalog().devices:
        unknown = set(device.versions) - known
        assert not unknown, f"{device.model} lists unknown versions {unknown}"


def test_a_device_only_offers_versions_of_an_os_it_reports():
    data = _load("desktop")
    os_of = {v["version"]: v["os"] for v in data["versions"]}

    for device in DesktopDevice.catalog().devices:
        assert device.oses
        for version in device.versions:
            assert os_of[version] in device.oses, (device.model, version)


def test_weights_are_positive_and_aligned(platform):
    catalog = platform.catalog()

    assert len(catalog.weights) == len(catalog.devices)
    assert all(w > 0 for w in catalog.weights)

    for device in catalog.devices:
        assert len(device.version_weights) == len(device.versions)
        assert all(w > 0 for w in device.version_weights)


def test_desktop_os_views_cover_every_device_and_version():
    catalog = DesktopDevice.catalog()

    assert set(catalog.oses) == set(DESKTOP_OSES)
    assert set(catalog.by_os) == set(DESKTOP_OSES)

    for name, view in catalog.by_os.items():
        assert view.devices and len(view.weights) == len(view.devices)
        for device in view.devices:
            names, weights = device.by_os[name]
            assert names and len(names) == len(weights)

    # every device belongs to at least one view
    seen = {d.model for view in catalog.by_os.values() for d in view.devices}
    assert seen == {d.model for d in catalog.devices}


def test_no_device_lists_a_version_twice(platform):
    for device in platform.catalog().devices:
        assert _duplicates(device.versions) == []


# --- per platform string formats ------------------------------------------

def test_ios_versions_are_current_and_numeric():
    for version in iOSDevice.versions():
        assert re.fullmatch(r"\d+(\.\d+)*", version)
        assert int(version.split(".")[0]) >= 18   # 12-17 dropped as obsolete


def test_ios_devices_are_iphones_with_a_release_date():
    data = _load("ios")

    for device in data["devices"]:
        assert device["model"].startswith("iPhone")
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", device["released"])


def test_ios_device_never_offers_a_version_released_before_it():
    data = _load("ios")
    released = {v["version"]: v["released"] for v in data["versions"]}

    for device in data["devices"]:
        oldest = min(released[v] for v in device["versions"])
        # the launch firmware may predate the retail date by a few days
        assert oldest >= "2024-01-01" or device["released"] <= "2024-01-01"


def test_android_versions_are_sdk_levels_in_range():
    for version in AndroidDevice.versions():
        assert re.fullmatch(r"SDK \d+", version)
        assert 33 <= int(version.split()[1]) <= 37


def test_android_device_sdk_ranges_are_contiguous():
    for device in AndroidDevice.catalog().devices:
        levels = sorted(int(v.split()[1]) for v in device.versions)
        assert levels == list(range(levels[0], levels[-1] + 1)), device.model


def test_android_models_carry_a_manufacturer_prefix():
    # The prefix comes from the device's own `manufacturer`, not a literal
    # list -- which brands exist is what
    # test_android_manufacturer_casing_is_the_measured_set covers.
    for device in _load("android")["devices"]:
        assert device["model"].startswith(device["manufacturer"]), device["model"]
        assert device["brand"] and device["released"]


def test_android_device_resolves_to_a_real_marketing_name():
    # Telegram's server does not show what the client sends: it looks the raw
    # manufacturer+code up and stores "Retail Branding + Marketing Name"
    # instead ('samsungSM-S918B' comes back as 'Samsung Galaxy S23 Ultra').
    # A code it cannot find is still split and title-cased, so an invented
    # model would look plausible while naming no real device -- these two
    # fields are what the lookup will land on, so neither may be empty.
    for device in _load("android")["devices"]:
        assert device["name"].strip(), device["model"]
        assert device["brand"].strip(), device["model"]
        assert device["code"].strip(), device["model"]


@pytest.mark.skipif(not PLAY_CATALOG.is_file(),
                    reason="Google's device catalog is only in the build cache")
def test_every_android_code_exists_in_googles_catalog():
    # The stronger form of the test above, when the cache is there to check
    # against: the server's lookup table is this catalog, so a code missing
    # from it is a device that would display as a bare code.
    import csv
    import io

    text = PLAY_CATALOG.read_bytes().decode("utf-16")
    known = {(row.get("Model") or "").strip() for row in csv.DictReader(io.StringIO(text))}

    missing = [d["code"] for d in _load("android")["devices"] if d["code"] not in known]
    assert not missing, f"{len(missing)} codes are not real devices: {missing[:5]}"


def test_every_catalog_group_has_an_explicit_share():
    # A group the table does not name falls back to 1.0, which is how OPPO,
    # vivo and realme would have landed at a fraction of their real share the
    # moment they were added -- silently, since nothing else would complain.
    groups = {device.get("brand") or device.get("vendor")
              for name in ("android", "desktop", "ios", "web")
              for device in _load(name)["devices"]} - {None}

    assert groups <= set(GROUP_SHARES), sorted(groups - set(GROUP_SHARES))


def test_android_manufacturer_casing_is_the_measured_set():
    # Every one of these was read off stock factory firmware, resolving
    # ro.product.manufacturer through the device's own property source order.
    # A new spelling here means a brand was added without that check -- the
    # casing is not Google's retail branding and cannot be guessed from it.
    measured = {"samsung", "Google", "Xiaomi", "OnePlus", "motorola",
                "OPPO", "realme", "vivo"}

    assert {d["manufacturer"] for d in _load("android")["devices"]} <= measured


def test_no_generic_system_image_code_reaches_the_android_catalog():
    # Google's catalog really does list "Xiaomi for arm64" for the Xiaomi 14
    # Ultra and the MIX Fold 4, and "MSM8996 for arm64" for the HTC 10, but no
    # handset reports a GSI name -- it sends its own code. Chinese-brand dumps
    # hit the same trap from the other side, where a partition still holding
    # the chip vendor's defaults resolves to "Kona for arm64".
    leaked = [d["model"] for d in _load("android")["devices"]
              if re.search(r"\bfor\s+arm", d["code"], re.I)]

    assert not leaked, leaked


def test_android_model_is_manufacturer_and_code_with_no_separator():
    # Telegram Android sends Build.MANUFACTURER + Build.MODEL, no separator
    # (ConnectionsManager.java), and `code` is Build.MODEL as Google lists it.
    for device in _load("android")["devices"]:
        assert device["model"] == device["manufacturer"] + device["code"]
        assert " " not in device["manufacturer"]


def test_no_tablet_reaches_the_android_phone_catalog():
    # A tablet reports its model exactly as a phone does, so this is a scope
    # rule, not a format one -- but it has to hold for every brand at once.
    # Google's catalog lists dozens of Xiaomi and Redmi slates and barely any
    # Samsung ones, so filtering only "Galaxy Tab" spent Xiaomi's group share
    # on tablets while Samsung's went entirely to phones.
    #
    # The pattern here is deliberately looser than the builder's, and that is
    # the point: the first version of this test reused `\b(pad|tab|...)\b`,
    # the same expression the builder filters with, so it shared exactly the
    # blind spot it was meant to guard. A word boundary does not fall between
    # a letter and a digit, so `OnePlus Pad2` and `vivo Pad2` passed both.
    # A guard written from the implementation can only confirm it.
    slates = [f"{d['name']} ({d['model']})" for d in _load("android")["devices"]
              if re.search(r"(?<![a-z])(pad|tab|tablet|watch|book|buds|slate)\d*\b",
                           d["name"], re.I)]

    assert not slates, slates


def test_firmware_dated_brands_list_only_the_sdk_their_firmware_proves():
    # Xiaomi, OPPO, realme and vivo have no release date in any public feed,
    # so there is nothing to derive a launch API level from. Only the level
    # their newest shipped firmware proves is listed: a range below it would
    # offer a phone a release it may never have run, and no source could
    # contradict that. The dated families are different -- endoflife.date
    # gives them a real release date, so their range starts at a true launch
    # level and widening it upwards is evidenced.
    measured = ("miui-updates-tracker", "dumps.tadiphone.dev")
    wide = [(d["model"], d["versions"]) for d in _load("android")["devices"]
            if d["source"].startswith(measured) and len(d["versions"]) != 1]

    assert not wide, wide


def test_no_desktop_version_claims_an_architecture_no_model_can_run(desktop):
    # SystemVersionPretty writes "arm64" only on an ARM machine. linuxhw/DMI
    # contributes no ARM Windows hardware under any sampled vendor folder, so
    # the string could only ever be paired with an x86 model number -- a
    # machine that does not exist. It comes back when ARM hardware does.
    arm = [v["version"] for v in desktop["versions"]
           if re.search(r"\b(arm64|aarch64|armv)", v["version"], re.I)]
    arm_models = [d["model"] for d in desktop["devices"]
                  if re.search(r"\b(surface pro x|thinkpad x13s|snapdragon)", d["model"], re.I)]

    assert bool(arm) == bool(arm_models), (arm, arm_models)


def test_no_bsd_version_reports_a_desktop_only_linux_ships(desktop):
    # SystemVersionPretty joins uname's sysname with XDG_CURRENT_DESKTOP, and
    # the two are not independent. Three of these identifiers are a
    # distribution's own session name rather than the desktop's -- Ubuntu and
    # Pop!_OS set `ubuntu:GNOME` and `pop:GNOME`, and upstream budgie-desktop
    # exports a bare `Budgie`, so `Budgie GNOME` is Ubuntu Budgie's. The other
    # three have no FreeBSD port at all. Pairing any of them with a FreeBSD
    # release describes a machine that cannot exist, which is the one thing a
    # generated identity may never do.
    paired = [v["version"] for v in desktop["versions"]
              if not v["version"].startswith("Linux ")
              and any(d in v["version"] for d in _lib_base_linux_only())]

    assert not paired, paired


def _lib_base_linux_only():
    """The builder's own list, so the data and the rule cannot drift.

    Read out of the source with `ast` rather than imported: `desktop.py`
    imports its siblings, and `tools/` ships in no wheel, so parsing is the
    one way to reach the constant that works wherever the data does.
    """

    import ast

    tree = ast.parse(BUILDER.with_name("desktop.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.AnnAssign)
                and getattr(node.target, "id", "") == "LINUX_ONLY_DESKTOPS"):
            return {ast.literal_eval(e) for e in node.value.args[0].elts}
    raise AssertionError("desktop.py no longer declares LINUX_ONLY_DESKTOPS")


def test_every_bsd_desktop_pairing_is_one_a_ports_tree_can_produce(desktop):
    # The complement of the test above, stated positively, so a desktop added
    # to the pool without being classified shows up here rather than silently
    # reaching a BSD row.
    bsd = {v["version"].split("RELEASE ", 1)[1].rsplit(" ", 1)[0]
           for v in desktop["versions"]
           if "RELEASE " in v["version"]}

    # Checked against the FreeBSD ports tree: x11/gnome-shell,
    # x11/plasma6-plasma-desktop, x11/cinnamon, x11/xfce4, x11/mate,
    # x11/lxqt, x11/lxde-meta, x11/budgie-desktop, x11-wm/hyprland,
    # x11-wm/sway and x11-wm/cosmic-comp all exist.
    ported = {"GNOME", "KDE", "X-Cinnamon", "XFCE", "MATE", "LXQt",
              "Hyprland", "sway", "COSMIC", "LXDE"}

    assert bsd <= ported, sorted(bsd - ported)


def test_no_chromeos_machine_is_offered_with_a_windows_version(desktop):
    # A ChromeOS machine names its reference platform in the DMI family, so
    # `Google_Zork` and `Google_Hatch` identify one from the probe alone. Three
    # reached the pool tagged Windows-capable, and Windows is not installable
    # on them at all -- coreboot, no CSM, no vendor drivers -- so `Berknip`
    # beside "Windows 11 x64" is a machine that cannot exist. On ChromeOS
    # itself Telegram Desktop runs in the Crostini VM, which reports the VM's
    # firmware rather than the board, so the probe's string is not what that
    # client sends either.
    #
    # The board names are checked rather than the family, because the family
    # is what the builder filters on and a guard must not share its input.
    boards = {"berknip", "dratini", "gumboz", "zork", "hatch", "octopus",
              "coral", "volteer", "brya", "nissa", "trogdor", "grunt"}
    leaked = [d["model"] for d in desktop["devices"]
              if d["model"].lower() in boards]

    assert not leaked, leaked


def test_only_hp_models_exceed_lib_bases_fifteen_character_cap(desktop):
    # IsDeviceModelOk caps a model at 15 characters and makes one exception,
    # for the HP names that are longer. A non-HP string over the cap would
    # mean the port stopped being applied somewhere.
    over = [d["model"] for d in desktop["devices"]
            if len(d["model"]) > MAX_MODEL
            and not d["model"].startswith(("HP", "103C"))]

    assert not over, over
    assert all(len(d["model"]) <= MAX_HP_MODEL for d in desktop["devices"])


def test_macos_stays_out_of_the_desktop_catalog(desktop):
    # macOS was dropped on purpose: its two official clients send different
    # version strings and the native one's bare "26.1" matches no client's
    # icon rules. What must not come back is the OS, not Apple hardware --
    # a Mac booted into Linux really does report "MacBookPro13,1" through
    # DMI, so those rows are Linux/Windows rows and they stay.
    assert set(desktop["os"]) == {"windows", "linux"}
    assert all(d["os"] != ["macos"] for d in desktop["devices"])
    assert all(v["os"] in ("windows", "linux") for v in desktop["versions"])

    # A bare "26.1" would be a macOS version that slipped through.
    assert not [v["version"] for v in desktop["versions"]
                if re.fullmatch(r"\d+(\.\d+)*", v["version"])]


@pytest.mark.skipif(not BUILDER.is_file(), reason="tools/ is not installed")
def test_every_desktop_model_is_a_fixed_point_of_lib_bases_own_rules():
    # The strongest statement available without a Windows registry: feed each
    # stored model back in as `product_name` and lib_base must return it
    # unchanged. A model that fails this is one the client would have trimmed
    # or rejected, so it could never appear in a real session.
    lib_base = _lib_base()

    for model in DesktopDevice.models():
        assert lib_base.simplify_device_model(model) == model, model
        assert lib_base.product_name_to_device_model(model) == model, model


@pytest.mark.parametrize("os", ["windows", "linux"])
def test_pc_models_fit_what_the_client_can_report(os):
    for model in DesktopDevice.models(os):
        limit = MAX_HP_MODEL if model.startswith("HP ") else MAX_MODEL
        assert 0 < len(model) <= limit, model
        assert "_" not in model
        assert model == " ".join(model.split())


def test_windows_versions_name_the_release_and_optional_architecture():
    # SystemVersionPretty appends an architecture only for AMD64 and ARM64, so
    # a 32-bit x86 machine reports the bare name.
    for version in DesktopDevice.versions("windows"):
        assert re.fullmatch(r"Windows (10|11)( (x64|arm64))?", version)


def test_linux_versions_carry_desktop_and_session():
    for version in DesktopDevice.versions("linux"):
        assert re.match(r"^(Linux|FreeBSD \S+) ", version)
        assert re.search(r"\b(Wayland|X11|Xwayland)\b", version)


def test_linux_versions_only_carry_glibc_on_glibc_systems():
    # GetLibcVersion returns nothing outside glibc and SystemVersionPretty then
    # skips the whole clause, so musl and BSD strings end at the session type.
    for version in DesktopDevice.versions("linux"):
        libc = re.search(r"\bglibc \d+\.\d+$", version)
        if version.startswith("FreeBSD"):
            assert libc is None, version
        else:
            assert libc or re.search(r"\b(Wayland|X11|Xwayland)$", version), version


def test_linux_model_pool_adds_the_fallbacks_windows_has_none_of():
    models = set(DesktopDevice.models("linux"))

    assert {"KVM", "QEMU", "VMWARE"} <= models      # systemd-detect-virt
    assert {"Laptop", "Tablet", "Handset"} <= models  # ChassisTypeToString
    assert "Desktop" in models                       # FinalizeDeviceModel
    # ChassisTypeToString maps every notebook chassis to "Laptop"
    assert "Notebook" not in models
    # none of these reach a Windows client
    assert not ({"KVM", "Laptop"} & set(DesktopDevice.models("windows")))


# --- sampling --------------------------------------------------------------

def test_random_device_only_returns_pairs_the_catalog_allows(platform):
    allowed = {(d.model, v) for d in platform.catalog().devices for v in d.versions}

    for _ in range(200):
        device = platform.random_device()
        assert (device.model, device.version) in allowed


def test_same_unique_id_gives_the_same_device(platform):
    assert platform.random_device("user-42") == platform.random_device("user-42")


def test_different_unique_ids_spread_across_devices(platform):
    drawn = {platform.random_device(f"user-{i}").model for i in range(60)}
    assert len(drawn) > 1


def test_random_device_without_an_id_varies(platform):
    drawn = {platform.random_device() for _ in range(80)}
    assert len(drawn) > 1


@pytest.mark.parametrize("os", DESKTOP_OSES)
def test_pinning_an_os_only_draws_that_os(os):
    allowed = {(d.model, v)
               for d in DesktopDevice.catalog().by_os[os].devices
               for v in d.by_os[os][0]}

    for i in range(120):
        device = DesktopDevice.random_device(f"pin-{i}", os=os)
        assert (device.model, device.version) in allowed


def test_pinning_an_os_is_deterministic():
    assert (DesktopDevice.random_device("abc", os="linux")
            == DesktopDevice.random_device("abc", os="linux"))


def test_pinning_an_unknown_os_raises():
    with pytest.raises(ValueError, match="no 'haiku' devices"):
        DesktopDevice.random_device(os="haiku")

    with pytest.raises(ValueError, match="no 'windows' devices"):
        AndroidDevice.random_device(os="windows")


def test_desktop_draws_follow_the_os_shares():
    os_of = {v["version"]: v["os"] for v in _load("desktop")["versions"]}
    picks = collections.Counter(
        os_of[DesktopDevice.random_device().version] for _ in range(4000))
    total = sum(OS_SHARES.values())

    for name, share in OS_SHARES.items():
        assert abs(picks[name] / 4000 - share / total) < 0.05, (name, picks)


def test_newer_releases_are_drawn_more_often_than_the_oldest():
    versions = [iOSDevice.random_device().version for _ in range(600)]
    newest = sum(1 for v in versions if v.startswith("27"))
    oldest = sum(1 for v in versions if v.startswith("18"))

    assert newest > 0
    assert newest >= oldest / 2   # recency weighting, not a hard ordering


def test_random_family_is_weighted_towards_mobile():
    picks = collections.Counter(
        random_family(ALL_PLATFORMS).platform for _ in range(3000))

    assert picks["android"] > picks["desktop"] > picks["ios"] / 2
    assert set(picks) == {p.platform for p in ALL_PLATFORMS}


def test_random_family_is_deterministic_with_a_unique_id():
    assert random_family(ALL_PLATFORMS, "abc") is random_family(ALL_PLATFORMS, "abc")


# --- lookup and types ------------------------------------------------------

def test_find_device_matches_model_and_optional_version():
    device = AndroidDevice.catalog().devices[0]

    assert AndroidDevice.find_device(device.model) is not None
    assert AndroidDevice.find_device(device.model, device.versions[0]) == DeviceInfo(
        device.model, device.versions[0]
    )
    assert AndroidDevice.find_device(device.model, "SDK 1") is None
    assert AndroidDevice.find_device("no such model") is None


def test_models_and_versions_narrow_to_one_os():
    # Windows draws only the shared pool, Linux adds its own boards on top.
    assert set(DesktopDevice.models("windows")) < set(DesktopDevice.models())
    assert set(DesktopDevice.versions("windows")).isdisjoint(
        DesktopDevice.versions("linux"))
    assert sum(len(DesktopDevice.versions(os)) for os in DESKTOP_OSES) == len(
        DesktopDevice.versions())


def test_single_os_platform_reports_no_oses():
    assert AndroidDevice.oses() == ()
    assert iOSDevice.oses() == ()
    assert DesktopDevice.oses() == DESKTOP_OSES


def test_device_info_is_immutable_and_prints_both_parts():
    device = DeviceInfo("model", "version")

    assert str(device) == "model version"
    assert device.to_dict() == {"device_model": "model", "system_version": "version"}

    with pytest.raises(AttributeError):
        device.model = "other"


def test_unknown_platform_raises():
    class Nope(SystemInfo):
        platform = "nope"

    with pytest.raises(FileNotFoundError):
        Nope.random_device()
