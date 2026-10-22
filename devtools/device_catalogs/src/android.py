"""Android phones: model codes, release dates and SDK ranges."""

from __future__ import annotations as _annotations

import collections
import csv
from datetime import date
import io
import re
from typing import TYPE_CHECKING, Any, ClassVar, NamedTuple

from .builder import Builder
from .catalog import Catalog
from .firmware import FirmwareHarvest
from .shared import TODAY, normalize

if TYPE_CHECKING:
    from collections.abc import Callable

    from .cache import Cache

# -------------------------------- Android --------------------------------

class ApiLevel(NamedTuple):
    """One Android API level, from source.android.com."""

    api: int
    android: str
    released: str


class AndroidBuilder(Builder):
    """Android phones, joined from three sources.

    Model codes come from Google, dates and support windows from
    endoflife.date, and Xiaomi from its firmware tracker.

    No single source has all three, so this joins them on the device's
    marketing name -- which is why `normalize` and the name builders below
    carry so much of the weight.
    """

    key = "android"
    platform: ClassVar[str] = "android"

    # --- scope ------------------------------------------------------------

    MIN_SDK: ClassVar[int] = 33                       # Android 13
    MIN_RELEASE: ClassVar[str] = "2023-01-01"
    #: Conservative bound on how many major upgrades a phone really received.
    MAX_OS_UPGRADES: ClassVar[int] = 4
    #: API levels allowed below a Xiaomi device's newest shipped firmware, and
    #: the same allowance for the brands a firmware dump evidences.
    #
    #: Both are 0, which means those devices list exactly the one API level
    #: their newest shipped firmware proves they run. A larger value would
    #: claim a phone also ran older releases, and for these brands there is no
    #: launch date anywhere to check that against -- a model that shipped with
    #: Android 15 would be offered Android 13, which it never ran. The dated
    #: families below do not need the allowance: endoflife.date gives them a
    #: real release date, so `sdk_at` derives a true launch level and the range
    #: up from it is real.
    XIAOMI_BACK: ClassVar[int] = 0
    FIRMWARE_BACK: ClassVar[int] = 0

    API_LEVELS: ClassVar[tuple[ApiLevel, ...]] = (
        ApiLevel(33, "13", "2022-08-15"),
        ApiLevel(34, "14", "2023-10-04"),
        ApiLevel(35, "15", "2024-09-03"),
        ApiLevel(36, "16", "2025-06-10"),
        ApiLevel(37, "17", "2026-06-16"),
    )

    # --- the manufacturer prefix -----------------------------------------

    # Build.MANUFACTURER per retail brand, which is what the model string is
    # prefixed with. Redmi and POCO hardware reports Xiaomi here.
    #
    # The casing is NOT the retail branding Google's catalog prints ("Samsung",
    # "Motorola"); it is `ro.product.manufacturer` as resolved on the device.
    # Verified against stock factory firmware on dumps.tadiphone.dev, reading
    # the per-partition props in the order each device's own
    # ro.product.property_source_order asks for (AOSP default is
    # "product,odm,vendor,system_ext,system" -- property_service.cpp
    # property_initialize_ro_product_props):
    #
    #   samsung/dm3q  (SM-S918B)      odm+product+vendor+system -> samsung
    #   samsung/e3q   (SM-S928B)      odm+product+vendor+system -> samsung
    #   xiaomi/houji  (23127PN0CG)    odm                       -> Xiaomi
    #   google/komodo (Pixel 9 ProXL) product+vendor            -> Google
    #   motorola/rhode                product+system            -> motorola
    #   oneplus/op595dl1              odm/build.prop            -> OnePlus
    #
    # The Chinese brands were read the same way, through the overlay the
    # bootloader selects (see `FirmwareHarvest`):
    #
    #   oppo/op5e8bl1   odm/etc/24203/build.default.prop -> OPPO   (CPH2797)
    #   realme/re60c8l1 odm/etc/24776/build.default.prop -> realme (RMX5210)
    #   vivo/pd2073     odm/etc/build.prop               -> vivo   (V2073A)
    MANUFACTURER: ClassVar[dict[str, str]] = {
        "samsung": "samsung",
        "google": "Google",
        "xiaomi": "Xiaomi",
        "redmi": "Xiaomi",
        "poco": "Xiaomi",
        "oneplus": "OnePlus",
        "motorola": "motorola",
        "oppo": "OPPO",
        "realme": "realme",
        "vivo": "vivo",
    }

    # --- sources ----------------------------------------------------------

    PLAY_URL: ClassVar[str] = "https://storage.googleapis.com/play_public/supported_devices.csv"
    EOL_URL: ClassVar[str] = "https://endoflife.date/api/{product}.json"
    XIAOMI_BASE: ClassVar[str] = "https://raw.githubusercontent.com/XiaomiFirmwareUpdater/miui-updates-tracker/master/data/"
    API_LEVEL_URL: ClassVar[str] = "https://source.android.com/docs/setup/reference/build-numbers"
    CONNECTIONS_MANAGER_URL: ClassVar[str] = (
        "https://github.com/DrKLO/Telegram/blob/master/TMessagesProj/src/main/java/org/telegram/tgnet/ConnectionsManager.java"
    )

    #: One cache file per source, so a rename is one edit and not a search.
    PLAY_FILE: ClassVar[str] = "play_devices.csv"
    #: Google publishes the catalog as UTF-16, not UTF-8.
    PLAY_ENCODING: ClassVar[str] = "utf-16"
    EOL_FILE: ClassVar[str] = "eol_{product}.json"
    XIAOMI_LATEST_FILE: ClassVar[str] = "xiaomi_latest.yml"
    XIAOMI_DEVICES_FILE: ClassVar[str] = "xiaomi_devices.yml"

    #: The tracker file names under XIAOMI_BASE.
    XIAOMI_LATEST: ClassVar[str] = "latest.yml"
    XIAOMI_DEVICES: ClassVar[str] = "devices.yml"
    #: Only shipped stable firmware counts as evidence of a top version.
    XIAOMI_BRANCH: ClassVar[str] = "Stable"
    #: Which retail brand a Xiaomi-family marketing name belongs to, tried in
    #: order because "Redmi Note" must not match the bare "xiaomi" fallback.
    XIAOMI_BRANDS: ClassVar[tuple[str, ...]] = ("redmi", "poco", "xiaomi")

    #: endoflife.date product, Play "Retail Branding", and the method that
    #: turns a release cycle into the marketing name Google's catalog uses.
    EOL_FAMILIES: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("samsung-mobile", "samsung", "title_name"),
        ("pixel", "google", "pixel_name"),
        ("oneplus", "oneplus", "oneplus_name"),
        ("motorola-mobility", "motorola", "motorola_name"),
    )

    # --- filters and name shapes -----------------------------------------

    #: Non-phones that share a phone brand's release feed. A tablet reports
    #: its model exactly as a phone does, so this is a scope rule rather than
    #: a correctness one -- but it has to be applied to every brand or the mix
    #: tilts: Google's catalog lists far more Xiaomi and Redmi tablets than
    #: Samsung ones, so filtering only "tab s"/"tab a" let a brand's share be
    #: spent on slates while another brand's was not.
    #: `\d*` on the slate words because a word boundary does not fall between
    #: a letter and a digit: `\bpad\b` matches "Pad 2" but not "Pad2", which is
    #: how `OnePlus Pad2` and `vivo Pad2` reached the phone pool.
    SKIP: ClassVar[re.Pattern[str]] = re.compile(
        r"\b(watch|slate|pixelbook|pixel c|book|buds|tab\d*|tablet|pad\d*)\b",
        re.I)
    #: What a plausible Build.MODEL looks like.
    MODEL_CODE: ClassVar[re.Pattern[str]] = re.compile(r"[A-Za-z0-9 ._+-]{3,32}")
    #: Generic-system-image names that Google's catalog does carry but no retail
    #: handset reports: it lists "Xiaomi for arm64" for the Xiaomi 14 Ultra and
    #: the MIX Fold 4, and "MSM8996 for arm64" for the HTC 10. A phone sends its
    #: own code, so these would be the one invented-looking string in the file.
    CODE_REJECT: ClassVar[re.Pattern[str]] = re.compile(r"\bfor\s+arm", re.I)
    #: Suffixes that stay uppercase where `capitalize()` would mangle them.
    UPPER_WORD: ClassVar[re.Pattern[str]] = re.compile(r"(fe|5g|4g|xl|nfc)")

    #: endoflife.date writes Pixel cycles as "9pro"; Google writes "Pixel 9 Pro".
    PIXEL_CYCLE: ClassVar[re.Pattern[str]] = re.compile(r"(\d+)(a|pro|proxl|profold|xl|fold)?")
    PIXEL_SUFFIX: ClassVar[dict[str, str]] = {
        "a": "a", "pro": " Pro", "proxl": " Pro XL", "profold": " Pro Fold",
        "xl": " XL", "fold": " Fold",
    }

    #: Regional codename and name tails in the Xiaomi tracker, which lists the
    #: same phone once per market.
    XIAOMI_REGION_CODE: ClassVar[re.Pattern[str]] = re.compile(
        r"_(eea|in|ru|tr|tw|id|jp|kr|global)(_global)?$")
    XIAOMI_REGION_NAME: ClassVar[re.Pattern[str]] = re.compile(
        r"\s+(China|Global|EEA|India|Russia|Taiwan|Japan|Korea|Indonesia|Turkey|NFC|TD|LTE)$")

    def __init__(self, cache: Cache) -> None:
        """Start with empty Google Play lookups; `build` fills them."""
        super().__init__(cache)
        #: (retail branding, marketing name) -> every Build.MODEL code Google lists.
        self.play: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
        #: (retail branding, Build.MODEL) -> the marketing name, for the reverse
        #: lookup a firmware dump needs: it proves a code, not a name.
        self.play_names: dict[tuple[str, str], str] = {}
        #: model string -> finished device record.
        self.devices: dict[str, dict[str, Any]] = {}

    # --- API level helpers ------------------------------------------------

    @classmethod
    def sdk_at(cls, day: str) -> int:
        """The API level current on `day`, floored at MIN_SDK."""
        level = cls.MIN_SDK
        for entry in cls.API_LEVELS:
            if entry.released <= day:
                level = entry.api
        return level

    @classmethod
    def sdk_of_android(cls, android: str) -> int | None:
        """Return the SDK level of an Android release, or None if unknown."""
        return next((e.api for e in cls.API_LEVELS if e.android == android), None)

    @classmethod
    def release_of_sdk(cls, api: int) -> str:
        """Return the release date of an SDK level."""
        return next(e.released for e in cls.API_LEVELS if e.api == api)

    # --- name builders ----------------------------------------------------

    @classmethod
    def title_name(cls, cycle: str, prefix: str = "") -> str:
        """Title-case an endoflife.date cycle, after an optional brand prefix."""
        words = [w.upper() if cls.UPPER_WORD.fullmatch(w) else w.capitalize()
                 for w in cycle.replace("-", " ").split()]
        return (prefix + " " + " ".join(words)).strip()

    @classmethod
    def oneplus_name(cls, cycle: str) -> str:
        """Name a OnePlus device from its endoflife.date cycle."""
        return cls.title_name(cycle, "OnePlus")

    @staticmethod
    def motorola_name(cycle: str) -> str:
        """Name a Motorola device from its endoflife.date cycle."""
        return cycle.replace("-", " ")

    @classmethod
    def pixel_name(cls, cycle: str) -> str:
        """Name a Pixel device from its endoflife.date cycle."""
        found = cls.PIXEL_CYCLE.fullmatch(cycle)
        if found:
            return "Pixel " + found.group(1) + cls.PIXEL_SUFFIX.get(found.group(2) or "", "")
        return "Pixel " + cycle.capitalize()

    # --- tracker YAML (no PyYAML dependency) ------------------------------

    @staticmethod
    def parse_flat_yaml(text: str) -> list[dict[str, str]]:
        """Reader for the tracker's list-of-flat-mappings YAML."""
        items: list[dict[str, str]] = []
        current: dict[str, str] | None = None
        for raw in text.splitlines():
            line = raw
            if raw.startswith("- "):
                if current:
                    items.append(current)
                current = {}
                line = "  " + raw[2:]
            if current is None or ":" not in line:
                continue
            key, _, value = line.strip().partition(":")
            current[key.strip()] = value.strip().strip("'").strip('"')
        if current:
            items.append(current)
        return items

    @staticmethod
    def parse_codenames(text: str) -> dict[str, str]:
        """Codename -> first listed marketing name, from the tracker's devices.yml."""
        names: dict[str, str] = {}
        key: str | None = None
        for line in text.splitlines():
            if not line.startswith((" ", "-")) and line.strip().endswith(":"):
                key = line.strip()[:-1]
            elif line.strip().startswith("- ") and key and key not in names:
                names[key] = line.strip()[2:].strip().strip("'").strip('"')
        return names

    # --- assembly ---------------------------------------------------------

    def load_play_catalog(self) -> None:
        """Google publishes the CSV as UTF-16; it is the authority on Build.MODEL."""
        text = self.cache.fetch_text(self.PLAY_FILE, self.PLAY_URL,
                                     encoding=self.PLAY_ENCODING)
        for row in csv.DictReader(io.StringIO(text)):
            brand = normalize(row.get("Retail Branding"))
            marketing = (row.get("Marketing Name") or "").strip()
            name = normalize(marketing)
            model = (row.get("Model") or "").strip()
            if brand and name and model:
                self.play[(brand, name)].add(model)
                self.play_names.setdefault((brand, model), marketing)

    def model_codes(self, brand: str, name: str) -> list[str]:
        """Every Build.MODEL Google lists for this phone.

        Sources disagree on the "5G" suffix, so the name is tried as given,
        with it, and without it.
        """
        key = normalize(name)
        for candidate in (key, key + " 5g", key.replace(" 5g", "").strip()):
            if (brand, candidate) in self.play:
                return sorted(self.play[(brand, candidate)])
        return []

    def sdk_range(self, released: str, max_sdk: int,
                  upgrades: int | None = None) -> list[str]:
        """Return the SDK levels this phone plausibly ran.

        They run from its launch level up to the lowest of: its support
        ceiling, the newest level that exists, and launch plus the upgrades
        its own support window allows.
        """
        launch = self.sdk_at(released)
        allowed = self.MAX_OS_UPGRADES if upgrades is None else upgrades
        top = min(max_sdk, self.API_LEVELS[-1].api, launch + allowed)
        return [f"SDK {sdk}" for sdk in range(launch, top + 1) if sdk >= self.MIN_SDK]

    def add(self, brand: str, name: str, released: str, max_sdk: int, source: str,
            upgrades: int | None = None) -> bool:
        """Record every regional variant of one phone. False when nothing matched."""
        if self.SKIP.search(name):
            return False

        codes = self.model_codes(brand, name)
        versions = self.sdk_range(released, max_sdk, upgrades)
        if not codes or not versions:
            return False

        manufacturer = self.MANUFACTURER[brand]
        added = False
        for code in codes:
            if not self.MODEL_CODE.fullmatch(code) or self.CODE_REJECT.search(code):
                continue
            self.devices[manufacturer + code] = {
                # `model` is what the client sends; the two parts it is built
                # from are kept so the composition stays auditable.
                "model": manufacturer + code,
                "manufacturer": manufacturer,
                "code": code,
                "name": name,
                "brand": brand,
                "released": released,
                "versions": versions,
                "source": source,
            }
            added = True
        return added

    @classmethod
    def upgrades(cls, cycle: dict[str, Any]) -> int:
        """How many major upgrades this family's own support window allows.

        The window length is the count. Samsung publishes the two together --
        the A0x gets two OS upgrades, the A1x and A3x four, the S and Z lines
        six or seven -- and endoflife.date carries `releaseDate` and `support`
        per family, so the span between them says which tier a phone is in
        without a hand-kept table. A flat four offered a Galaxy A06 Android 17
        when its window closed two upgrades in.

        `MAX_OS_UPGRADES` is the fallback for a family with no `support` date,
        which is every Motorola one: there the span cannot be measured and a
        conservative constant is all that is left.
        """
        rel, sup = cycle.get("releaseDate"), cycle.get("support")
        if not (isinstance(rel, str) and isinstance(sup, str)):
            return cls.MAX_OS_UPGRADES
        try:
            days = (date.fromisoformat(sup) - date.fromisoformat(rel)).days
        except ValueError:
            return cls.MAX_OS_UPGRADES
        return max(0, round(days / 365.25))

    @staticmethod
    def horizon(cycle: dict[str, Any]) -> str:
        """The last day this family could still have gained an OS release.

        `support` first, because that is the field that means what is being
        asked: endoflife.date publishes it separately from `eol`, and for
        Samsung it is genuinely tiered -- two years for the A0x and M1x, four
        for the A1x and A3x, six or seven for the S and Z lines -- while `eol`
        runs two further years past it as the security window. Reading `eol`
        offered a Galaxy A14 four OS upgrades when Samsung promised it two.

        `eol` remains the fallback, because Motorola publishes no `support`
        date at all and it is then the only bound there is; and when neither
        is a date (a family still open-ended, where the API is a bool) there
        is nothing to bound with, so the caller's clamp to today decides.
        """
        for key in ("support", "eol"):
            value = cycle.get(key)
            if isinstance(value, str):
                return value
        return TODAY

    def add_eol_families(self) -> None:
        """Samsung, Pixel, OnePlus and Motorola, which endoflife.date dates."""
        for product, brand, namer_name in self.EOL_FAMILIES:
            data = self.cache.fetch_json(self.EOL_FILE.format(product=product),
                                         self.EOL_URL.format(product=product))
            namer: Callable[[str], str] = getattr(self, namer_name)
            matched = 0
            for cycle in data:
                released = cycle.get("releaseDate") or ""
                if not released or released < self.MIN_RELEASE:
                    continue
                if self.add(brand, namer(cycle["cycle"]), released,
                            self.sdk_at(min(self.horizon(cycle), TODAY)),
                            f"endoflife.date/{product} + play catalog",
                            self.upgrades(cycle)):
                    matched += 1
            print(f"  {product}: {matched} families")

    def add_xiaomi(self) -> None:
        """Xiaomi, Redmi and POCO, from the firmware tracker.

        latest.yml carries only the newest firmware per codename and region, so
        it gives a verified top Android version but no release date: the
        regional codenames are grouped, the highest shipped version becomes the
        ceiling, and the floor is XIAOMI_BACK levels below it with a synthetic
        date taken from the API level table.
        """
        latest = self.parse_flat_yaml(self.cache.fetch_text(
            self.XIAOMI_LATEST_FILE, self.XIAOMI_BASE + self.XIAOMI_LATEST,
            errors="ignore"))
        codenames = self.parse_codenames(self.cache.fetch_text(
            self.XIAOMI_DEVICES_FILE, self.XIAOMI_BASE + self.XIAOMI_DEVICES,
            errors="ignore"))

        families: dict[str, dict[str, Any]] = collections.defaultdict(
            lambda: {"android": 0, "date": "", "name": ""})

        for entry in latest:
            if entry.get("branch") != self.XIAOMI_BRANCH or not entry.get("codename"):
                continue
            family = families[self.XIAOMI_REGION_CODE.sub("", entry["codename"])]
            try:
                major = int(str(entry.get("android") or "0").split(".")[0])
            except ValueError:
                continue
            family["android"] = max(family["android"], major)
            family["date"] = max(family["date"], entry.get("date") or "")
            if not family["name"]:
                raw = codenames.get(entry["codename"]) or entry.get("name") or ""
                family["name"] = self.XIAOMI_REGION_NAME.sub("", raw).split("/")[0].strip()

        matched = 0
        for family in families.values():
            if family["date"] < self.MIN_RELEASE or not family["name"]:
                continue
            max_sdk = self.sdk_of_android(str(family["android"]))
            if max_sdk is None:
                continue

            name = family["name"]
            brand = next((b for b in self.XIAOMI_BRANDS
                          if name.lower().startswith(b)), self.XIAOMI_BRANDS[-1])
            floor = max(self.MIN_SDK, max_sdk - self.XIAOMI_BACK)
            if self.add(brand, name, self.release_of_sdk(floor), max_sdk,
                        "miui-updates-tracker + play catalog"):
                matched += 1
        print(f"  xiaomi: {matched} families")

    def add_firmware_brands(self) -> None:
        """OPPO, realme and vivo, from stock firmware.

        A dump proves a Build.MODEL and the newest Android release that shipped
        on it, but carries no launch date, so the floor is derived from the
        ceiling the way Xiaomi's is. The code is turned back into a marketing
        name through Google's catalog, which then expands it to every regional
        variant -- the dump only ever covers the market it was pulled from.
        """
        records = FirmwareHarvest(self.cache).records()
        wrong: set[tuple[str, str]] = set()
        done: set[tuple[str, str]] = set()
        matched = 0

        for record in records:
            brand = normalize(record["brand"])
            expected = self.MANUFACTURER.get(brand)
            if expected and record["manufacturer"] != expected:
                wrong.add((record["manufacturer"], expected))

            name = self.play_names.get((brand, record["code"]))
            if not name or (brand, name) in done:
                continue
            max_sdk = self.sdk_of_android(str(record["android"]))
            if max_sdk is None:
                continue

            floor = max(self.MIN_SDK, max_sdk - self.FIRMWARE_BACK)
            if self.add(brand, name, self.release_of_sdk(floor), max_sdk,
                        "dumps.tadiphone.dev firmware + play catalog"):
                done.add((brand, name))
                matched += 1

        if wrong:
            print(f"  WARNING: firmware disagrees with MANUFACTURER: {sorted(wrong)}")
        print(f"  firmware brands: {matched} families")

    # --- documentation written into the catalog ---------------------------

    MODEL_FORMAT: ClassVar[str] = (
        "Build.MANUFACTURER + Build.MODEL (no separator), as Telegram Android sends it")
    VERSION_FORMAT: ClassVar[str] = "SDK followed by Build.VERSION.SDK_INT"

    SOURCES: ClassVar[tuple[str, ...]] = (
        f"{PLAY_URL} -- Google public device catalog",
        "https://endoflife.date/api/samsung-mobile.json, pixel.json, oneplus.json, motorola-mobility.json",
        XIAOMI_BASE,
        f"{API_LEVEL_URL} -- API level release dates",
        CONNECTIONS_MANAGER_URL,
        (f"{FirmwareHarvest.WEB} -- stock factory firmware build.prop, for the "
         f"ro.product.manufacturer casing and for the OPPO, realme and vivo ceilings"),
    )

    NOTES: ClassVar[tuple[str, ...]] = (
        f"Devices released before {MIN_RELEASE} are excluded.",
        (f"Allowed SDKs run from the API level current at release up to "
         f"min(latest, launch + {MAX_OS_UPGRADES}, API level at support end)."),
        ("Xiaomi, Redmi, POCO, OPPO, realme and vivo carry exactly one SDK each: the one "
         "their newest shipped stable firmware proves they run. Those brands have no "
         "release date in any public feed -- endoflife.date tracks no Chinese phone brand "
         "and Google's catalog carries no dates -- so a range below that level could not "
         "be checked against a launch version and would offer a phone a release it never "
         "ran. The measured level is listed and nothing else."),
        ("Huawei and Honor are absent on purpose -- Huawei has no Android 13+ "
         "firmware because it moved to HarmonyOS, and the Honor dumps are GSI or "
         "enterprise images reporting manufacturer=unknown with model=magic."),
        ("model is manufacturer + code with no separator, which is how Telegram Android "
         "builds it (ConnectionsManager.java). code is Build.MODEL straight from Google's "
         "catalog. manufacturer is ro.product.manufacturer as resolved on the device, not "
         "the retail branding Google prints: verified on stock factory firmware (samsung "
         "dm3q/e3q -> samsung, xiaomi houji -> Xiaomi, google komodo -> Google, motorola "
         "rhode -> motorola, oneplus op595dl1 -> OnePlus, oppo op5e8bl1 -> OPPO, realme "
         "re60c8l1 -> realme, vivo pd2073 -> vivo). OPPO and realme hide theirs behind a "
         "bootloader-selected overlay, so the value comes from "
         "odm/etc/<prjname>/build.<flag>.prop rather than from any partition's build.prop."),
        ("Neither string is what anyone sees. Telegram's server rewrites both before "
         "storing them, measured by sending values over MTProto and reading back "
         "account.getAuthorizations: 'samsungSM-S918B' comes back as 'Samsung Galaxy S23 "
         "Ultra' and 'SDK 34' as '14 (34)'. The display name is this catalog's own brand + "
         "name fields, and the SDK mapping is the API level table above, so the server "
         "independently confirms both."),
        ("The lookup tolerates casing and spacing ('Samsung SM-S918B' resolves too), and an "
         "unrecognised code is still split and title-cased ('samsungSM-ZZZZZ' -> 'Samsung "
         "SM-ZZZZZ'). So the exact raw string matters for being what a real handset sends, "
         "not for how the session reads -- but every code here does resolve to a real "
         "device, which an invented one would not."),
    )

    # --- output -----------------------------------------------------------

    def build(self) -> list[Catalog]:
        """Join every Android source into the Android catalog."""
        self.load_play_catalog()
        self.add_eol_families()
        self.add_xiaomi()
        self.add_firmware_brands()

        return [Catalog(
            platform=self.platform,
            model_format=self.MODEL_FORMAT,
            version_format=self.VERSION_FORMAT,
            sources=list(self.SOURCES),
            notes=list(self.NOTES),
            versions=[{"version": f"SDK {e.api}", "released": e.released, "android": e.android}
                      for e in self.API_LEVELS if e.api >= self.MIN_SDK],
            devices=sorted(self.devices.values(), key=lambda d: (d["released"], d["model"])),
        )]
