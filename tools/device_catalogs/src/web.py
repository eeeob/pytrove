"""Browsers running Telegram Web, which reports the User-Agent as its model.

Telegram ships two web clients and they agree on both fields, so unlike the
desktop catalog there is no choice of reference client to make:

    Web K  src/lib/appManagers/networkerFactory.ts
             deviceModel:    getEnvironment().USER_AGENT || 'Unknown UserAgent'
             systemVersion:  navigator.platform || 'Unknown Platform'
    Web A  src/api/gramjs/methods/client.ts
             deviceModel:    navigator.userAgent || userAgent || 'Unknown UserAgent'
             systemVersion:  platform || 'Unknown platform'

So `device_model` is the raw `navigator.userAgent` and `system_version` is
`navigator.platform`. Both are now frozen by the browsers themselves, which is
what makes this catalog exact rather than a scrape:

  * `navigator.platform` (WebCore/page/NavigatorBase.cpp, which Blink mirrors)
    is "Win32" on Windows even on 64-bit, "MacIntel" on macOS even on Apple
    silicon, and uname's sysname + machine on Linux. Three strings, not a pool.
  * the Chromium UA (components/embedder_support/user_agent_utils.cc) is
    "Mozilla/5.0 (%s) AppleWebKit/537.36 (KHTML, like Gecko) %s Safari/537.36"
    with GetUnifiedPlatform() giving a frozen platform token per OS, and only
    the major version moving -- the minor is pinned to .0.0.0.
  * the Gecko UA (netwerk/protocol/http/nsHttpHandler.cpp BuildUserAgent) is
    assembled from mPlatform, mOscpu and "rv:" + MOZILLA_UAVERSION, with the
    platform token dropped on Windows alone (UA_SPARE_PLATFORM is defined only
    under XP_WIN) and OSCPU_WINDOWS deliberately hardcoded to "Windows NT 10.0".
  * the Edge token is Microsoft's documented " Edg/<version>" appended to the
    Chromium string, with `Edg` on all three desktop systems.

Safari is deliberately absent. WebKit freezes its prefix (UserAgentMac.mm) but
the "Version/x.y Safari/605.1.15" suffix is Safari's own application name, and
Apple publishes no machine-readable feed for it -- endoflife.date has chrome
and firefox and no safari. Hand-typing those numbers is the one thing this
script does not do, so macOS is covered by Chrome, Edge and Firefox only.
"""

from __future__ import annotations

import collections
from typing import Any, ClassVar, NamedTuple

from .builder import Builder
from .catalog import Catalog


class WebPlatform(NamedTuple):
    """One operating system, in every spelling the three browsers use for it.

    The spellings genuinely differ and none of them can be derived from
    another: Chromium freezes macOS to "10_15_7" with underscores while Gecko
    sends "10.15" with a dot, and `navigator.platform` says "MacIntel" for the
    same machine.
    """

    key: str
    #: Group label, so a share can be given to "Chrome on Windows".
    label: str
    #: GetUnifiedPlatform() in user_agent_utils.cc.
    chromium: str
    #: nsHttpHandler mPlatform. Empty on Windows: UA_SPARE_PLATFORM is defined
    #: only under XP_WIN, and BuildUserAgent then omits the token entirely.
    firefox_platform: str
    #: nsHttpHandler mOscpu.
    firefox_oscpu: str
    #: NavigatorBase::platform(), which is what system_version carries.
    navigator: str
    #: Path segment in Google's version history API.
    chrome_slug: str
    #: "Platform" value in Microsoft's Edge update feed.
    edge_platform: str


class WebBuilder(Builder):
    """One catalog of (browser, version, operating system) User-Agent strings.

    A "device" here is a whole UA string and its "version" is the matching
    `navigator.platform`, which is why every device lists exactly one version:
    a UA that claims Windows cannot report "MacIntel".
    """

    key = "web"
    platform: ClassVar[str] = "web"

    # --- scope ------------------------------------------------------------

    #: Majors kept per browser and OS. Browsers auto-update, so the realistic
    #: pool is short -- a session five majors behind barely exists.
    MAJORS: ClassVar[int] = 4

    #: Desktop only. A phone browser reporting a mobile UA is a real session
    #: but a rare one, and it would need its own platform tokens and its own
    #: `navigator.platform` values ("iPhone", "Linux armv81") to stay honest.
    PLATFORMS: ClassVar[tuple[WebPlatform, ...]] = (
        WebPlatform(
            key="windows", label="Windows",
            chromium="Windows NT 10.0; Win64; x64",
            firefox_platform="", firefox_oscpu="Windows NT 10.0; Win64; x64",
            navigator="Win32", chrome_slug="win", edge_platform="Windows",
        ),
        WebPlatform(
            key="macos", label="macOS",
            chromium="Macintosh; Intel Mac OS X 10_15_7",
            firefox_platform="Macintosh", firefox_oscpu="Intel Mac OS X 10.15",
            navigator="MacIntel", chrome_slug="mac", edge_platform="MacOS",
        ),
        WebPlatform(
            key="linux", label="Linux",
            chromium="X11; Linux x86_64",
            firefox_platform="X11", firefox_oscpu="Linux x86_64",
            navigator="Linux x86_64", chrome_slug="linux", edge_platform="Linux",
        ),
    )

    #: (browser, OS) pairs to emit, and the share name each one carries. Every
    #: pair here must come back non-empty or the build says so, rather than
    #: quietly shipping a catalog with a browser missing.
    COMBINATIONS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("Chrome", "windows"), ("Chrome", "macos"), ("Chrome", "linux"),
        ("Edge", "windows"), ("Edge", "macos"), ("Edge", "linux"),
        ("Firefox", "windows"), ("Firefox", "macos"), ("Firefox", "linux"),
    )

    # --- the User-Agent templates ----------------------------------------

    #: BuildUserAgentFromOSAndProduct in user_agent_utils.cc.
    CHROMIUM_TEMPLATE: ClassVar[str] = (
        "Mozilla/5.0 ({token}) AppleWebKit/537.36 (KHTML, like Gecko) "
        "{product} Safari/537.36")
    #: The product part. Only the major is real: the minor version has been
    #: pinned to 0.0.0 since Chrome 101.
    CHROMIUM_PRODUCT: ClassVar[str] = "Chrome/{major}.0.0.0"
    #: Microsoft appends its own token to the Chromium string, and uses `Edg`
    #: on Windows, macOS and Linux alike.
    EDGE_SUFFIX: ClassVar[str] = " Edg/{major}.0.0.0"
    #: nsHttpHandler::BuildUserAgent, with the comment assembled from the
    #: platform token (when there is one), the oscpu and "rv:".
    FIREFOX_TEMPLATE: ClassVar[str] = (
        "Mozilla/5.0 ({comment}) Gecko/{trail} Firefox/{major}.0")
    #: LEGACY_UA_GECKO_TRAIL, frozen since Gecko 2.0.
    GECKO_TRAIL: ClassVar[str] = "20100101"

    # --- sources ----------------------------------------------------------

    CHROME_URL: ClassVar[str] = (
        "https://versionhistory.googleapis.com/v1/chrome/platforms/{slug}"
        "/channels/stable/versions/all/releases")
    FIREFOX_URL: ClassVar[str] = (
        "https://product-details.mozilla.org/1.0/firefox_history_major_releases.json")
    EDGE_URL: ClassVar[str] = (
        "https://edgeupdates.microsoft.com/api/products?view=enterprise")

    CHROME_FILE: ClassVar[str] = "chrome_releases_{slug}.json"
    FIREFOX_FILE: ClassVar[str] = "firefox_releases.json"
    EDGE_FILE: ClassVar[str] = "edge_releases.json"

    #: Microsoft lists one row per architecture; the UA is identical across
    #: them because GetUnifiedPlatform() reports "Win64; x64" whatever the
    #: real machine is, so one architecture is read and the rest skipped.
    EDGE_PRODUCT: ClassVar[str] = "Stable"
    EDGE_ARCH: ClassVar[dict[str, str]] = {
        "Windows": "x64", "MacOS": "universal", "Linux": "x64",
    }

    # --- documentation written into the catalog ---------------------------

    MODEL_FORMAT: ClassVar[str] = (
        "navigator.userAgent verbatim, which is what both Telegram web clients send")
    VERSION_FORMAT: ClassVar[str] = (
        "navigator.platform -- Win32, MacIntel, or uname sysname + machine on Linux")

    SOURCES: ClassVar[tuple[str, ...]] = (
        "https://github.com/morethanwords/tweb/blob/master/src/lib/appManagers/networkerFactory.ts"
        " -- Telegram Web K: deviceModel = USER_AGENT, systemVersion = navigator.platform",
        "https://github.com/Ajaxy/telegram-tt/blob/master/src/api/gramjs/methods/client.ts"
        " -- Telegram Web A: the same two fields",
        "https://github.com/chromium/chromium/blob/main/components/embedder_support/user_agent_utils.cc"
        " -- the Chromium UA template and the frozen platform tokens",
        "https://github.com/mozilla/gecko-dev/blob/master/netwerk/protocol/http/nsHttpHandler.cpp"
        " -- BuildUserAgent, mPlatform, mOscpu and UA_SPARE_PLATFORM",
        "https://github.com/WebKit/WebKit/blob/main/Source/WebCore/page/NavigatorBase.cpp"
        " -- NavigatorBase::platform(), the system_version values",
        "https://learn.microsoft.com/en-us/microsoft-edge/web-platform/user-agent-guidance"
        " -- the Edg token and where it goes",
        "https://versionhistory.googleapis.com/v1/chrome/platforms/win/channels/stable/versions/all/releases"
        " -- released Chrome versions per platform",
        "https://product-details.mozilla.org/1.0/firefox_history_major_releases.json"
        " -- released Firefox majors and their dates",
        "https://edgeupdates.microsoft.com/api/products?view=enterprise"
        " -- released Edge versions per platform",
    )

    NOTES: ClassVar[tuple[str, ...]] = (
        "model is the whole User-Agent string, not a device name: a browser has no "
        "model to report, so both web clients send navigator.userAgent as it stands. "
        "This is also why a web session draws a browser icon in every client -- "
        "Telegram Android matches 'chrome'/'firefox'/'edge' inside device_model and "
        "Telegram Desktop matches 'chrome'/'firefox'/'edg/', both before they look at "
        "the platform.",
        "Every string is generated from the browsers' own frozen templates rather than "
        "collected, because there is nothing left to collect: Chromium pins its "
        "platform token and its minor version, Gecko pins the Windows OS version to "
        "10.0, and only the major version still moves. The majors and their dates come "
        "from each vendor's own release feed.",
        f"Only the newest {MAJORS} majors per browser and system are kept. Browsers "
        f"update themselves, so a session further behind than that is not a realistic "
        f"thing to report.",
        "Desktop only, on purpose. A phone browser is a real web session but a rare "
        "one, and it would need its own frozen tokens and its own navigator.platform "
        "values to be honest rather than guessed.",
        "Safari is absent: WebKit freezes the UA prefix but the 'Version/x.y "
        "Safari/605.1.15' suffix is Safari's own application name and Apple publishes "
        "no machine-readable version feed, so the numbers would have to be invented. "
        "macOS is still covered, by Chrome, Edge and Firefox.",
        "Each device lists exactly one version because a UA and navigator.platform "
        "describe the same machine: a UA claiming Windows cannot report 'MacIntel'.",
    )

    # --- release feeds ----------------------------------------------------

    def chrome_majors(self, platform: WebPlatform) -> list[tuple[int, str]]:
        """(major, first serving date) newest first, from Google's feed."""

        data = self.cache.fetch_json(
            self.CHROME_FILE.format(slug=platform.chrome_slug),
            self.CHROME_URL.format(slug=platform.chrome_slug))

        first: dict[int, str] = {}
        for release in data.get("releases", []):
            try:
                major = int(str(release["version"]).split(".")[0])
            except (KeyError, ValueError):
                continue
            day = ((release.get("serving") or {}).get("startTime") or "")[:10]
            if day and (major not in first or day < first[major]):
                first[major] = day
        return sorted(first.items(), reverse=True)

    def firefox_majors(self) -> list[tuple[int, str]]:
        """(major, release date) newest first, from Mozilla's own history."""

        data = self.cache.fetch_json(self.FIREFOX_FILE, self.FIREFOX_URL)

        first: dict[int, str] = {}
        for version, day in data.items():
            try:
                major = int(str(version).split(".")[0])
            except ValueError:
                continue
            if day and (major not in first or day < first[major]):
                first[major] = day[:10]
        return sorted(first.items(), reverse=True)

    def edge_majors(self, platform: WebPlatform) -> list[tuple[int, str]]:
        """(major, first publish date) newest first, from Microsoft's feed."""

        data = self.cache.fetch_json(self.EDGE_FILE, self.EDGE_URL)
        arch = self.EDGE_ARCH.get(platform.edge_platform)

        first: dict[int, str] = {}
        for product in data:
            if product.get("Product") != self.EDGE_PRODUCT:
                continue
            for release in product.get("Releases", []):
                if (release.get("Platform") != platform.edge_platform
                        or release.get("Architecture") != arch):
                    continue
                try:
                    major = int(str(release["ProductVersion"]).split(".")[0])
                except (KeyError, ValueError):
                    continue
                day = (release.get("PublishedTime") or "")[:10]
                if day and (major not in first or day < first[major]):
                    first[major] = day
        return sorted(first.items(), reverse=True)

    # --- User-Agent assembly ---------------------------------------------

    @classmethod
    def chromium_agent(cls, platform: WebPlatform, major: int) -> str:
        return cls.CHROMIUM_TEMPLATE.format(
            token=platform.chromium,
            product=cls.CHROMIUM_PRODUCT.format(major=major))

    @classmethod
    def edge_agent(cls, platform: WebPlatform, major: int) -> str:
        return (cls.chromium_agent(platform, major)
                + cls.EDGE_SUFFIX.format(major=major))

    @classmethod
    def firefox_agent(cls, platform: WebPlatform, major: int) -> str:
        parts = [platform.firefox_platform, platform.firefox_oscpu, f"rv:{major}.0"]
        return cls.FIREFOX_TEMPLATE.format(
            comment="; ".join(part for part in parts if part),
            trail=cls.GECKO_TRAIL, major=major)

    # --- output -----------------------------------------------------------

    def build(self) -> list[Catalog]:
        by_platform = {p.key: p for p in self.PLATFORMS}
        agents = {"Chrome": self.chromium_agent,
                  "Edge": self.edge_agent,
                  "Firefox": self.firefox_agent}
        feeds = {"Chrome": self.chrome_majors,
                 "Edge": self.edge_majors,
                 "Firefox": lambda _platform: self.firefox_majors()}

        devices: list[dict[str, Any]] = []
        empty: list[str] = []

        for browser, platform_key in self.COMBINATIONS:
            platform = by_platform[platform_key]
            group = f"{browser} on {platform.label}"
            majors = feeds[browser](platform)[: self.MAJORS]
            if not majors:
                empty.append(group)
                continue

            for major, released in majors:
                devices.append({
                    "model": agents[browser](platform, major),
                    "browser": browser,
                    "major": major,
                    "system": platform.label,
                    # `brand` is the group a share is given to, which is the
                    # browser and the system together: Chrome's share on
                    # Windows has nothing to do with its share on Linux.
                    "brand": group,
                    "released": released,
                    "versions": [platform.navigator],
                    "source": f"{browser} release feed + the browser's own UA template",
                })
            print(f"  {group}: {', '.join(str(m) for m, _ in majors)}")

        if empty:
            print(f"  WARNING: no release found for {', '.join(empty)}")

        seen = collections.Counter(d["model"] for d in devices)
        duplicates = [model for model, count in seen.items() if count > 1]
        if duplicates:
            raise SystemExit(f"duplicate User-Agent strings: {duplicates}")

        return [Catalog(
            platform=self.platform,
            model_format=self.MODEL_FORMAT,
            version_format=self.VERSION_FORMAT,
            sources=list(self.SOURCES),
            notes=list(self.NOTES),
            versions=[{"version": p.navigator} for p in self.PLATFORMS],
            devices=sorted(devices, key=lambda d: (d["brand"], -d["major"])),
        )]
