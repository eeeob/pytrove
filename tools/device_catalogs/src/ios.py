"""iPhones, their firmwares, and the strings Telegram iOS sends for them."""

from __future__ import annotations as _annotations

import re
import time
from typing import Any, ClassVar

from .builder import Builder
from .catalog import Catalog
from .shared import major_of, version_key

# ---------------------------------- iOS ----------------------------------

class IOSBuilder(Builder):
    """iPhones, their firmwares, and the strings Telegram iOS sends for them."""

    key = "ios"
    platform: ClassVar[str] = "ios"

    # --- scope ------------------------------------------------------------

    #: 17 and older are no longer current.
    MIN_MAJOR: ClassVar[int] = 18
    #: iPhones announced before this are out of scope even if still supported.
    MIN_RELEASE_YEAR: ClassVar[str] = "2018"

    # --- sources ----------------------------------------------------------

    APPLEDB_URL: ClassVar[str] = "https://api.appledb.dev/device/main.json"
    IPSW_URL: ClassVar[str] = "https://api.ipsw.me/v4/device/{identifier}?type=ipsw"
    MTAPI_URL: ClassVar[str] = (
        "https://raw.githubusercontent.com/TelegramMessenger/Telegram-iOS/master/submodules/MtProtoKit/Sources/MTApiEnvironment.m"
    )
    IOS_APPDELEGATE_URL: ClassVar[str] = (
        "https://github.com/TelegramMessenger/Telegram-iOS/blob/master/submodules/TelegramUI/Sources/AppDelegate.swift"
    )

    #: One cache file per source, so a rename is one edit and not a search.
    APPLEDB_FILE: ClassVar[str] = "appledb_device.json"
    FIRMWARE_FILE: ClassVar[str] = "ipsw_iphones.json"
    MTAPI_FILE: ClassVar[str] = "mtapi_environment.m"

    # --- parsing ----------------------------------------------------------

    #: Where platformString starts and ends inside MTApiEnvironment.m.
    MTAPI_OPEN: ClassVar[str] = "- (NSString *)platformString"
    MTAPI_CLOSE: ClassVar[str] = "\n}\n"

    #: One `return @"name";` and every identifier that falls through to it.
    #: The conditions are written as an `||` chain, so several identifiers can
    #: share one string (iPhone11,4 and 11,6 are both "iPhone XS Max").
    NAME_BLOCK: ClassVar[re.Pattern[str]] = re.compile(
        r'((?:\s*(?:if|\|\|)?\s*\[platform (?:isEqualToString|hasPrefix):@"[^"]+"\]\s*(?:\|\|)?)+)'
        r'\s*\)?\s*\n?\s*return @"([^"]+)";')

    #: Polite spacing for the per-device ipsw.me queries.
    REQUEST_PAUSE: ClassVar[float] = 0.4

    # --- documentation written into the catalog ---------------------------

    MODEL_FORMAT: ClassVar[str] = (
        "MTApiEnvironment.platformString table, keyed by hw.machine")
    VERSION_FORMAT: ClassVar[str] = (
        "[UIDevice currentDevice].systemVersion -- plain, no prefix")

    SOURCES: ClassVar[tuple[str, ...]] = (
        f"{IPSW_URL} -- released iOS firmwares per device",
        f"{APPLEDB_URL} -- iPhone identifiers, release dates",
        f"{MTAPI_URL} -- platformString, the exact model string the client sends",
        f"{IOS_APPDELEGATE_URL} -- passes deviceModelName: nil, which is why "
        f"platformString is what reaches the wire",
    )

    NOTES: ClassVar[tuple[str, ...]] = (
        "model comes from Telegram's own platformString table, not Apple's marketing "
        "name: the client hardcodes the string, so a device the table omits reports "
        "'Unknown iPhone' instead.",
        "version is [UIDevice currentDevice].systemVersion verbatim (MTApiEnvironment.m), "
        "which carries no 'iOS' prefix.",
    )

    def telegram_names(self) -> dict[str, str]:
        """Identifier -> the string Telegram iOS actually puts on the wire.

        MTApiEnvironment.platformString is a hardcoded table, so Apple's own
        marketing name is the wrong source for this field even when it is the
        prettier one: an identifier the table omits reports "Unknown iPhone".
        """
        source = self.cache.fetch_text(self.MTAPI_FILE, self.MTAPI_URL, errors="replace")
        body = source[source.index(self.MTAPI_OPEN):]
        body = body[:body.index(self.MTAPI_CLOSE)]

        names: dict[str, str] = {}
        for match in self.NAME_BLOCK.finditer(body):
            for identifier in re.findall(r'@"([^"]+)"', match.group(1)):
                names.setdefault(identifier, match.group(2))

        return {key: value for key, value in names.items()
                if key.startswith("iPhone") and "," in key}

    def identifiers(self) -> dict[str, dict[str, str]]:
        """IPhone identifier -> name and release date, from appledb."""
        wanted: dict[str, dict[str, str]] = {}
        for entry in self.cache.fetch_json(self.APPLEDB_FILE, self.APPLEDB_URL):
            if entry.get("type") != "iPhone" or entry.get("internal"):
                continue

            # appledb gives `released` as a string for some devices and a list
            # for others; without this both shapes have to be handled below.
            released = entry.get("released") or []
            if isinstance(released, str):
                released = [released]
            released = [r for r in released if isinstance(r, str) and re.match(r"^\d{4}", r)]

            if not released or min(released) < self.MIN_RELEASE_YEAR:
                continue
            for identifier in entry.get("identifier") or []:
                wanted[identifier] = {"name": entry["name"], "released": min(released)}

        return wanted

    def firmwares(self, wanted: dict[str, dict[str, str]]) -> dict[str, dict[str, Any]]:
        """Return every released firmware per identifier.

        Cached as one file because it costs one request per device.
        """
        name = self.FIRMWARE_FILE
        if self.cache.has(name):
            return self.cache.read_json(name)
        if self.cache.offline:
            self.cache.missing(f"--offline but {self.cache.path(name)} is missing")

        out: dict[str, dict[str, Any]] = {}
        for index, (identifier, meta) in enumerate(sorted(wanted.items()), 1):
            try:
                data = self.cache.get_json(self.IPSW_URL.format(identifier=identifier))
            except Exception as exc:                      # noqa: BLE001 - report and skip
                print(f"  {identifier}: {type(exc).__name__} {exc}")
                continue

            out[identifier] = {
                "name": data.get("name") or meta["name"],
                "released": meta["released"],
                "firmwares": [{"version": f["version"],
                               "date": (f.get("releasedate") or "")[:10]}
                              for f in data.get("firmwares", [])],
            }
            print(f"  {index}/{len(wanted)} {identifier}: {len(out[identifier]['firmwares'])}")
            time.sleep(self.REQUEST_PAUSE)

        self.cache.write_json(name, out)
        return out

    def build(self) -> list[Catalog]:
        """Build the iOS catalog from firmware data and Telegram's names."""
        firmwares = self.firmwares(self.identifiers())
        telegram_names = self.telegram_names()

        best: dict[str, dict[str, Any]] = {}
        dates: dict[str, str] = {}
        unnamed: list[str] = []

        for identifier, meta in firmwares.items():
            # The model string has to be the one the client sends, not Apple's
            # marketing name: Telegram says "iPhone 13 Mini" and "iPhone SE
            # (2nd gen)", and reports "Unknown iPhone" for anything it predates.
            name = telegram_names.get(identifier)
            if not name:
                unnamed.append(identifier)
                continue

            versions = []
            for firmware in meta["firmwares"]:
                try:
                    if major_of(firmware["version"]) < self.MIN_MAJOR:
                        continue
                except ValueError:
                    continue
                versions.append(firmware["version"])
                if firmware["date"]:
                    dates.setdefault(firmware["version"], firmware["date"])

            if not versions:
                continue

            # Widest firmware coverage wins (that is the global variant); the
            # identifier breaks ties so a rebuild always produces the same file.
            current = best.get(name)
            if (current is None
                    or len(versions) > len(current["versions"])
                    or (len(versions) == len(current["versions"])
                        and identifier < current["identifier"])):
                best[name] = {
                    "model": name,
                    "identifier": identifier,
                    "released": meta["released"],
                    # Apple ships some versions with more than one build.
                    "versions": sorted(dict.fromkeys(versions), key=version_key),
                }

        if unnamed:
            print(f"  skipped (not in Telegram's name table): {', '.join(sorted(unnamed))}")

        return [Catalog(
            platform=self.platform,
            model_format=self.MODEL_FORMAT,
            version_format=self.VERSION_FORMAT,
            sources=list(self.SOURCES),
            notes=list(self.NOTES),
            versions=[{"version": v, "released": dates[v]} for v in sorted(dates, key=version_key)],
            devices=sorted(best.values(), key=lambda d: (d["released"], d["model"])),
        )]
