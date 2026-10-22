"""Windows and Linux, which Telegram reports as one desktop platform."""

from __future__ import annotations as _annotations

import collections
import re
from typing import TYPE_CHECKING, Any, ClassVar

from .builder import Builder
from .catalog import Catalog
from .dmi import DmiHarvest
from .libbase import LibBase
from .shared import Share

if TYPE_CHECKING:
    from collections.abc import Iterable

# ----------------------------- desktop builder -----------------------------


class DesktopBuilder(Builder):
    """One catalog for every desktop OS.

    That is the one platform Telegram's clients present:
    `PlatformDevice.DESKTOP`.

    Windows and Linux share the hardware pool outright -- the same PC reports
    either, and both clients derive the model from the same firmware fields
    through the same `LibBase` rules -- so those models are stored once and
    tagged `["windows", "linux"]`.

    Telegram Desktop is the single reference client, and every string here is
    what its own `lib_base` rules produce. Unigram, the other official Windows
    client, reports the raw `systemProductName` with no cleaning and no length
    cap and a bare "Windows 11" with no architecture; modelling it too would
    mean two mutually exclusive formats in one pool, so it is left out.

    macOS is deliberately absent. Telegram ships two Mac clients that disagree
    on the version string -- the native one sends NSProcessInfo's bare "26.1"
    (MTApiEnvironment.m) while Telegram Desktop sends "macOS 26.1"
    (base_info_mac.mm) -- and the bare form carries no substring any client can
    match, so a Mac row renders with the wrong icon unless the api_id is itself
    registered as a Mac app. Neither choice is wrong and neither is safe, so
    the catalog reports only Windows and Linux.
    """

    key = "desktop"
    platform: ClassVar[str] = "desktop"

    #: Models kept per vendor group, so a well-represented vendor cannot
    #: swamp the pool.
    PER_VENDOR: ClassVar[int] = 90

    #: Firmware placeholders that are technically reportable but meaningless.
    JUNK: ClassVar[re.Pattern[str]] = re.compile(
        r"(to be filled|system product|default string|invalid|o\.e\.m|not applicable|"
        r"not specified|^none$|^n/?a$|unknown|example|placeholder|^\d+$|^\W)",
        re.I,
    )
    HAS_LETTER: ClassVar[re.Pattern[str]] = re.compile(r"[A-Za-z]")

    #: ChromeOS machines name their reference platform in the DMI family, so
    #: `Google_Zork` or `Google_Hatch` identifies one from its probe alone and
    #: nothing has to be recognised by product name. They are dropped rather
    #: than tagged Linux-only, for the same reason Huawei is not in the Android
    #: pool: the string would be wrong for almost everyone who could send it.
    #: Windows is not installable on them at all -- coreboot, no CSM, no
    #: vendor drivers -- so `Berknip` beside "Windows 11 x64" is a machine
    #: that cannot exist. And on ChromeOS itself Telegram Desktop runs inside
    #: the Crostini VM, which reports the VM's own firmware and not the board,
    #: so the probe's string is not what that client sends either. Only a
    #: Chromebook with unlocked firmware and Linux installed over ChromeOS
    #: would report it, and that is far too narrow to model.
    CHROME_OS_FAMILY: ClassVar[str] = "Google_"

    #: What FinalizeDeviceModel reports when the firmware exposes nothing
    #: usable, which covers virtual machines and many custom builds.
    FALLBACK_MODEL: ClassVar[str] = "Desktop"

    #: The OSes a PC can report. Which one a draw lands on is decided by the
    #: version weights, since the machine itself runs either.
    PC_OS: ClassVar[list[str]] = ["windows", "linux"]

    # --- Windows versions -------------------------------------------------

    #: SystemVersionPretty output and its share of the installed base. Hand
    #: maintained: there is no feed for this.
    #
    #: "Windows 11 arm64" is a string the client really does send, but it is
    #: deliberately not here: SystemVersionPretty writes arm64 only on an ARM
    #: machine, and every model in the pool is x86 -- linuxhw/DMI has no ARM
    #: Windows laptop under any sampled vendor folder, and the Microsoft folder
    #: contributes no probe at all. Offering it would pair an ARM OS with a
    #: Dell or Lenovo x86 model number, which is a machine that cannot exist.
    #: Add it only together with real ARM hardware for it to sit on.
    WINDOWS_VERSIONS: ClassVar[tuple[dict[str, Any], ...]] = (
        {"os": "windows", "version": "Windows 11 x64", "released": "2021-10-04", "weight": 72},
        {"os": "windows", "version": "Windows 10 x64", "released": "2015-07-29", "weight": 27},
        # No architecture at all: SystemVersionPretty appends one only for
        # AMD64 and ARM64, so a 32-bit x86 machine reports the bare name.
        # Windows 11 has no 32-bit edition, so only the 10 line reaches this.
        {"os": "windows", "version": "Windows 10", "released": "2015-07-29", "weight": 1},
    )

    # --- Linux and the other Unixes ---------------------------------------

    #: uname sysname, plus the release on everything except Linux -- lib_base
    #: appends u.release under `#ifndef Q_OS_LINUX`, so a FreeBSD machine
    #: reports its version and a Linux one does not.
    KERNELS: ClassVar[tuple[Share, ...]] = (
        Share("Linux", 970),
        Share("FreeBSD 14.3-RELEASE", 2),
        Share("FreeBSD 15.0-RELEASE", 1),
    )

    #: Every XDG_CURRENT_DESKTOP part is kept, so these are the values whole.
    DESKTOPS: ClassVar[tuple[Share, ...]] = (
        Share("ubuntu GNOME", 24),
        Share("GNOME", 19),
        Share("KDE", 21),
        Share("X-Cinnamon", 8),
        Share("XFCE", 7),
        Share("MATE", 4),
        Share("LXQt", 2),
        Share("pop GNOME", 3),
        Share("Budgie GNOME", 2),
        Share("Hyprland", 3),
        Share("sway", 1),
        Share("Unity", 1),
        Share("Deepin", 2),
        Share("Pantheon", 1),
        Share("COSMIC", 1),
        Share("LXDE", 1),
    )

    #: Desktop identifiers a non-Linux kernel can never report, so the kernel
    #: x desktop product does not invent a machine that cannot exist. Three of
    #: them are a distribution's own session name rather than the desktop's --
    #: `ubuntu:GNOME` and `pop:GNOME` are set by Ubuntu's and Pop!_OS's session
    #: files, and upstream budgie-desktop exports a bare `Budgie`, so
    #: `Budgie GNOME` is Ubuntu Budgie's. The other three simply have no
    #: FreeBSD port: checked against the ports tree, `x11/cinnamon`,
    #: `x11/budgie-desktop`, `x11-wm/cosmic-comp`, `x11/gnome-shell`,
    #: `x11/plasma6-plasma-desktop`, `x11/xfce4`, `x11/mate`, `x11/lxqt`,
    #: `x11/lxde-meta`, `x11-wm/hyprland` and `x11-wm/sway` are all there
    #: while deepin, unity and pantheon are not.
    LINUX_ONLY_DESKTOPS: ClassVar[frozenset[str]] = frozenset(
        {
            "ubuntu GNOME",
            "pop GNOME",
            "Budgie GNOME",
            "Unity",
            "Deepin",
            "Pantheon",
        }
    )
    SESSIONS: ClassVar[tuple[Share, ...]] = (
        Share("Wayland", 62),
        Share("X11", 33),
        Share("Xwayland", 5),
    )
    #: The empty name is not a gap: GetLibcVersion returns nothing outside
    #: glibc, and SystemVersionPretty then omits the libc part entirely, so a
    #: musl distribution reports "Linux GNOME Wayland". lib_base's "libc"
    #: fallback is unreachable -- the name is only ever empty when the version
    #: is too -- so no "libc X.Y" string is generated.
    LIBC: ClassVar[tuple[Share, ...]] = (
        Share("glibc 2.35", 14),
        Share("glibc 2.36", 8),
        Share("glibc 2.37", 4),
        Share("glibc 2.38", 6),
        Share("glibc 2.39", 22),
        Share("glibc 2.40", 8),
        Share("glibc 2.41", 12),
        Share("glibc 2.42", 14),
        Share("glibc 2.43", 12),
        Share("", 3),
    )
    #: Divides the four-factor product into readable weights.
    VERSION_SCALE: ClassVar[float] = 1e4

    # base_info_linux.cpp falls back to systemd-detect-virt (uppercased) and
    # then to the SMBIOS chassis type, so these are reportable Linux models
    # too. Windows has no such fallback: lib_base there ends at
    # FinalizeDeviceModel's "Desktop".
    LINUX_VIRT: ClassVar[tuple[Share, ...]] = (
        Share("KVM", 7),
        Share("ORACLE", 3),
        Share("VMWARE", 3),
        Share("QEMU", 2),
        Share("MICROSOFT", 2),
    )
    # The only strings ChassisTypeToString can return, minus "Desktop" which is
    # already in the pool as the FinalizeDeviceModel fallback. Notebook and
    # laptop chassis types all map to "Laptop", so "Notebook" is unreachable.
    LINUX_CHASSIS: ClassVar[tuple[Share, ...]] = (
        Share("Laptop", 12),
        Share("Server", 2),
        Share("Tablet", 1),
        Share("Convertible", 1),
        Share("Handset", 1),
    )

    # --- per-OS documentation ---------------------------------------------

    DMI_SOURCES: ClassVar[tuple[str, ...]] = (
        "https://github.com/linuxhw/DMI -- real dmidecode output collected from Linux machines",
        "https://github.com/desktop-app/lib_base/blob/master/base/platform/base_platform_info.cpp -- model string rules",
    )

    SHARED_MODEL_NOTE: ClassVar[str] = (
        "Model strings are produced by running lib_base's own DeviceModelPretty over real "
        "dmidecode records, so a machine whose product name the client would reject appears "
        "as its family + board or not at all. This is why most Lenovo entries are machine "
        "type codes and HP entries keep their 'HP ' prefix: that is what the firmware reports."
    )

    WINDOWS_DOC: ClassVar[dict[str, Any]] = {
        "model_format": "DeviceModelPretty of real DMI records: SystemProductName, else SystemFamily + BaseBoardProduct; 15 chars, HP names up to 32",
        "version_format": "marketing name + native architecture",
        "sources": [
            *DMI_SOURCES,
            "https://github.com/desktop-app/lib_base/blob/master/base/platform/win/base_info_win.cpp",
            "https://endoflife.date/api/windows.json -- release and support dates behind the version weights (read by hand, not fetched)",
        ],
        "notes": [
            "Version weights approximate the installed base after Windows 10 went end of support on 2025-10-14.",
            "Hardware era is not matched against the Windows version; the pool is limited to current hardware instead.",
            (
                "No arm64 version is listed. SystemVersionPretty writes arm64 only on an ARM "
                "machine and every model in this pool is x86, so the string would have to be "
                "paired with hardware that cannot run it."
            ),
            SHARED_MODEL_NOTE,
        ],
    }

    LINUX_DOC: ClassVar[dict[str, Any]] = {
        "model_format": "DeviceModelPretty of real DMI records: product_name, else product_family + board_name; 15 chars, HP names up to 32",
        "version_format": "uname sysname (plus the release off Linux) + XDG_CURRENT_DESKTOP parts + session type + libc",
        "sources": [
            *DMI_SOURCES,
            "https://github.com/desktop-app/lib_base/blob/master/base/platform/linux/base_info_linux.cpp",
            "https://repology.org/api/v1/project/glibc -- glibc versions behind the LIBC table (read by hand, not fetched)",
        ],
        "notes": [
            "Version strings are every combination of kernel, desktop environment, session type and libc.",
            "Weights are popularity estimates, not measurements; desktop and session shares follow common distro defaults.",
            (
                "A non-glibc system carries no libc part at all, because GetLibcVersion returns nothing "
                "outside glibc and the whole clause is then skipped. FreeBSD additionally carries "
                "uname's release, which lib_base appends everywhere except Linux."
            ),
            (
                "The model pool adds what Windows has no equivalent for: systemd-detect-virt names "
                "(uppercased, for virtual machines) and SMBIOS chassis types, which base_info_linux.cpp "
                "falls back to when DMI exposes no usable product name."
            ),
            SHARED_MODEL_NOTE,
        ],
    }

    # --- PC hardware pool -------------------------------------------------

    @staticmethod
    def bios_date(record: dict[str, str]) -> str:
        """Dmidecode prints MM/DD/YYYY; reorder so a string compare sorts it.

        This stands in for a release date, which DMI does not carry.
        """
        parts = record.get("bios", "").split("/")
        return f"{parts[2]}-{parts[0]}-{parts[1]}" if len(parts) == 3 else ""

    def models_by_vendor(self, records: Iterable[dict[str, str]]) -> dict[str, dict[str, str]]:
        """Vendor -> {model string: newest BIOS date that produced it}."""
        by_vendor: dict[str, dict[str, str]] = collections.defaultdict(dict)
        for record in records:
            if record.get("family", "").startswith(self.CHROME_OS_FAMILY):
                continue
            model = LibBase.device_model_from_dmi(
                record["product"], record["family"], record["board"]
            )
            if not model or self.JUNK.search(model) or not self.HAS_LETTER.search(model):
                continue
            bucket = by_vendor[record["vendor"]]
            if self.bios_date(record) >= bucket.get(model, ""):
                bucket[model] = self.bios_date(record)
        return by_vendor

    def pc_pool(self, records: Iterable[dict[str, str]]) -> list[dict[str, Any]]:
        """Return the newest `PER_VENDOR` models per vendor, plus a fallback.

        The fallback covers firmware that reports nothing; every entry is
        reportable under both Windows and Linux.
        """
        by_vendor = self.models_by_vendor(records)
        devices: list[dict[str, Any]] = [
            {
                "model": self.FALLBACK_MODEL,
                "os": self.PC_OS,
                "vendor": "Other",
                "source": "lib_base FinalizeDeviceModel fallback",
            }
        ]

        # A model string may only appear once: the same board turns up under
        # more than one sys_vendor folder (an ASRock board in a machine
        # reporting MSI), and a few machines report a product name equal to a
        # fallback string.
        taken = {self.FALLBACK_MODEL}
        taken |= {share.name for share in self.LINUX_VIRT + self.LINUX_CHASSIS}

        for vendor in sorted(by_vendor):
            newest = sorted(by_vendor[vendor].items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
            kept: list[str] = []
            for model, _bios in newest:
                if len(kept) >= self.PER_VENDOR:
                    break
                if model not in taken:
                    taken.add(model)
                    kept.append(model)

            devices += [
                {"model": model, "os": self.PC_OS, "vendor": vendor, "source": "linuxhw/DMI"}
                for model in sorted(kept)
            ]
            print(f"  {vendor}: {len(by_vendor[vendor])} models -> {len(kept)} kept")

        return devices[:1] + sorted(devices[1:], key=lambda d: (d["vendor"], d["model"]))

    @classmethod
    def linux_only_models(cls) -> list[dict[str, Any]]:
        """Fallback names no Windows machine can report."""
        return [
            {
                "model": share.name,
                "os": ["linux"],
                "vendor": "Other",
                "weight": share.weight,
                "source": source,
            }
            for shares, source in (
                (cls.LINUX_VIRT, "lib_base systemd-detect-virt fallback"),
                (cls.LINUX_CHASSIS, "lib_base ChassisTypeToString fallback"),
            )
            for share in shares
        ]

    # --- version strings --------------------------------------------------

    @classmethod
    def unix_versions(cls) -> list[dict[str, Any]]:
        """Every kernel x desktop x session x libc string the client can join.

        Session and libc are independent of each other, but both are
        constrained by the kernel, so the product is taken per kernel rather
        than once: BSD is pinned to the empty libc because it is never glibc,
        and it drops the desktop identifiers no BSD can report, which would
        otherwise pair a FreeBSD release with Ubuntu's own session name.
        """
        out: list[dict[str, Any]] = []
        for kernel in cls.KERNELS:
            linux = kernel.name == "Linux"
            libcs = cls.LIBC if linux else (Share("", 100),)
            desktops = (
                cls.DESKTOPS
                if linux
                else tuple(d for d in cls.DESKTOPS if d.name not in cls.LINUX_ONLY_DESKTOPS)
            )
            for desktop in desktops:
                for session in cls.SESSIONS:
                    for libc in libcs:
                        parts = (kernel.name, desktop.name, session.name, libc.name)
                        weight = (
                            kernel.weight
                            * desktop.weight
                            * session.weight
                            * libc.weight
                            / cls.VERSION_SCALE
                        )
                        out.append(
                            {
                                "os": "linux",
                                "version": " ".join(part for part in parts if part),
                                "weight": round(weight, 6),
                            }
                        )
        return out

    # --- output -----------------------------------------------------------

    def build(self) -> list[Catalog]:
        """Build the desktop catalog from the DMI pool and Linux-only models."""
        devices = self.pc_pool(DmiHarvest(self.cache).records())
        devices += self.linux_only_models()

        return [
            Catalog(
                platform=self.platform,
                os={
                    "windows": self.WINDOWS_DOC,
                    "linux": self.LINUX_DOC,
                },
                versions=[*self.WINDOWS_VERSIONS, *self.unix_versions()],
                devices=devices,
            )
        ]
