"""Retail phone identity read out of stock firmware dumps."""

from __future__ import annotations as _annotations

import json
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, ClassVar

from .shared import TODAY

if TYPE_CHECKING:
    from .cache import Cache

# ------------------- firmware harvest (Chinese OEM phones) -------------------

class FirmwareHarvest:
    """Retail device names and newest Android releases from stock firmware.

    Reads `Build.MANUFACTURER`/`Build.MODEL` and the newest Android release
    shipped out of stock firmware on dumps.tadiphone.dev.

    Needed because endoflife.date tracks no Chinese phone brand -- of its 483
    products the only phone families are pixel, samsung-mobile, oneplus,
    motorola-mobility and nokia -- and Google's catalog carries no dates. The
    firmware itself carries both, so these brands are evidenced the same way
    Xiaomi is: a measured ceiling, and a floor derived from it.

    Two layouts exist and both are handled:

      * vivo writes the real values straight into each partition's build.prop.
      * oplus (OPPO and realme) writes placeholders there -- `manufacturer` is
        literally "oplus" and `model` is an internal codename -- and defers the
        retail values to `/odm/etc/${ro.boot.prjname}/build.${ro.boot.flag}.prop`,
        a file the bootloader picks per project and region. Since the boot
        variables cannot be known from a static dump, the numbered project
        directory is listed and every `build.*.prop` in it is read; the regional
        files are what give a phone its several model codes.

    The harvest is cumulative, which no other cache here is: see `merge`.

    Honor and Huawei are deliberately absent. Huawei has no Android 13+ dump at
    all because it moved to HarmonyOS, and the Honor dumps are GSI or enterprise
    images that report `manufacturer=unknown` with `model=magic`, so neither
    yields a retail string.
    """

    BASE: ClassVar[str] = "https://dumps.tadiphone.dev/api/v4"
    WEB: ClassVar[str] = "https://dumps.tadiphone.dev/dumps"
    RECORDS_FILE: ClassVar[str] = "firmware_records.json"
    #: What `devtools/_preflight`'s janitor renames RECORDS_FILE to when a source
    #: it derives from moves -- `on_change = "merge"` on the firmware_records
    #: entry in sources/sources.toml. This filename is the entire interface
    #: between the two: nothing here imports the checker, and the janitor
    #: knows only how to rename a file, never what is inside one. When no
    #: `.prev` file exists the harvest behaves exactly as it did before.
    PREV_FILE: ClassVar[str] = "firmware_records.prev.json"
    #: How long a device survives without a dump proving it again. Must stay
    #: in step with `record_max_age_days` on that same registry entry.
    RECORD_MAX_AGE_DAYS: ClassVar[int] = 730

    #: Brand subgroup under /dumps -> the Play "Retail Branding" it maps to.
    #: Only brands whose dumps were checked to carry retail props are here.
    BRANDS: ClassVar[dict[str, str]] = {
        "oppo": "oppo",
        "realme": "realme",
        "vivo": "vivo",
    }

    #: Dumps older than this are ignored: the catalog only carries current
    #: hardware, and `AndroidBuilder.MIN_SDK` would drop them anyway.
    MIN_ANDROID: ClassVar[int] = 13
    #: Project list pages per brand, 100 projects each.
    MAX_PAGES: ClassVar[int] = 4
    WORKERS: ClassVar[int] = 12

    #: The Android release and the build timestamp both sit in the branch name,
    #: e.g. "qssi_64-user-16-BP2A.250605.015-1775558843758-release-keys--IN".
    BRANCH_RELEASE: ClassVar[re.Pattern[str]] = re.compile(r"-user-(\d+)-")
    BRANCH_STAMP: ClassVar[re.Pattern[str]] = re.compile(r"-(\d{13})-")

    #: AOSP's default `ro.product.property_source_order`; a device may override
    #: it, and the resolved value is whichever partition in this order names the
    #: property first (property_service.cpp).
    SOURCE_ORDER: ClassVar[tuple[str, ...]] = (
        "product", "odm", "vendor", "system_ext", "system")
    SOURCE_ORDER_PROP: ClassVar[str] = "ro.product.property_source_order"

    #: Where each partition keeps its build.prop inside a dump.
    PROP_PATH: ClassVar[dict[str, str]] = {
        "product": "product/etc/build.prop",
        "odm": "odm/etc/build.prop",
        "vendor": "vendor/build.prop",
        "system_ext": "system_ext/etc/build.prop",
        "system": "system/system/build.prop",
    }
    #: Where the bootloader-selected overlay lives, and what its files look like.
    OVERLAY_DIR: ClassVar[str] = "odm/etc"
    OVERLAY_PREFIX: ClassVar[str] = "build."
    OVERLAY_SUFFIX: ClassVar[str] = ".prop"

    #: Build-system placeholders that are not retail values. A model or
    #: manufacturer matching one of these means the real value is elsewhere.
    #: "qualcomm" is in here because some dumps carry a partition whose props
    #: are still the chip vendor's defaults, which resolve to
    #: manufacturer=QUALCOMM with the SoC codename as the model ("Kona for
    #: arm64", "Lahaina for arm64"). Treating it as a placeholder sends the
    #: resolver on to the overlay, where the retail values are.
    PLACEHOLDER: ClassVar[frozenset[str]] = frozenset({
        "unknown", "alps", "oplus", "magic", "qssi", "mssi", "generic",
        "android", "aosp", "gsi", "sys", "none", "qualcomm", "qti", "",
    })
    #: What a retail Build.MODEL looks like, so a leftover codename is dropped.
    MODEL_SHAPE: ClassVar[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._+-]{2,31}")
    #: A generic-system-image model, which is never what a handset reports.
    MODEL_REJECT: ClassVar[re.Pattern[str]] = re.compile(r"\bfor\s+arm", re.I)

    PROP_LINE: ClassVar[re.Pattern[str]] = re.compile(
        r"^(ro\.product(?:\.[a-z_]+)?\.(?:model|manufacturer))=(.*)$", re.M)

    def __init__(self, cache: Cache) -> None:
        """Keep the cache the harvest reads and writes through."""
        self.cache = cache

    # --- the GitLab API ---------------------------------------------------

    def api(self, path: str) -> Any:
        """Call the GitLab API at `path` and return the decoded JSON."""
        return json.loads(self.cache.download(self.BASE + path, timeout=90))

    def file(self, project: int, path: str, ref: str) -> str:
        """One file out of a dump, or "" when the dump does not carry it."""
        url = (f"{self.BASE}/projects/{project}/repository/files/"
               f"{urllib.parse.quote(path, safe='')}/raw"
               f"?ref={urllib.parse.quote(ref, safe='')}")
        try:
            return self.cache.download(url, timeout=90).decode("utf-8", "replace")
        except Exception:                                 # noqa: BLE001 - skip it
            return ""

    def tree(self, project: int, path: str, ref: str) -> list[dict[str, Any]]:
        """List the entries under `path` in a dump."""
        try:
            return self.api(
                f"/projects/{project}/repository/tree"
                f"?path={urllib.parse.quote(path, safe='')}&per_page=100"
                f"&ref={urllib.parse.quote(ref, safe='')}")
        except Exception:                                 # noqa: BLE001 - skip it
            return []

    # --- step 1: which dumps are worth reading ---------------------------

    def dumps(self, brand: str) -> list[tuple[int, str, int, str]]:
        """(project id, branch, android release, build date) per fresh dump."""
        found: list[tuple[int, str, int, str]] = []
        for page in range(1, self.MAX_PAGES + 1):
            try:
                items = self.api(
                    f"/groups/dumps%2F{brand}/projects"
                    f"?per_page=100&page={page}&include_subgroups=true")
            except Exception as exc:                      # noqa: BLE001
                print(f"  {brand}: {type(exc).__name__} {exc}")
                break
            if not items:
                break
            for item in items:
                branch = item.get("default_branch") or ""
                release = self.BRANCH_RELEASE.search(branch)
                if not release or int(release.group(1)) < self.MIN_ANDROID:
                    continue
                stamp = self.BRANCH_STAMP.search(branch)
                day = (date.fromtimestamp(int(stamp.group(1)) / 1000).isoformat()
                       if stamp else "")
                found.append((item["id"], branch, int(release.group(1)), day))
        return found

    # --- step 2: resolve the retail strings ------------------------------

    @classmethod
    def props(cls, text: str) -> dict[str, str]:
        """Parse a `build.prop` text into a key-to-value mapping."""
        return {key: value.strip()
                for key, value in cls.PROP_LINE.findall(text)}

    @classmethod
    def pick(cls, props: dict[str, str], partition: str, field: str) -> str:
        """The value `partition` contributes for `field`, placeholders aside."""
        for key in (f"ro.product.{partition}.{field}", f"ro.product.{field}"):
            value = props.get(key, "").strip()
            if value and value.lower() not in cls.PLACEHOLDER:
                return value
        return ""

    def resolve(self, project: int, ref: str) -> list[tuple[str, str]]:
        """Every (manufacturer, model) pair this dump can report.

        A list rather than one pair because the regional overlay files give a
        phone one model code per market, exactly as Google's catalog does.
        """
        files = {partition: self.file(project, path, ref)
                 for partition, path in self.PROP_PATH.items()}

        # The first partition that declares the order wins. The inner `break`
        # this replaces only left the line loop, so every later partition
        # overwrote the value and the *last* declaration won instead -- the
        # same answer whenever the partitions agree, which is why it went
        # unnoticed, and the wrong one the moment they do not.
        order = self.SOURCE_ORDER
        for text in files.values():
            declared = next((line for line in text.splitlines()
                             if line.startswith(self.SOURCE_ORDER_PROP + "=")), None)
            if declared is not None:
                parts = tuple(p.strip() for p in declared.split("=", 1)[1].split(","))
                order = tuple(p for p in parts if p in self.PROP_PATH) or order
                break

        for partition in order:
            props = self.props(files.get(partition, ""))
            model = self.pick(props, partition, "model")
            manufacturer = self.pick(props, partition, "manufacturer")
            if model and manufacturer:
                return [(manufacturer, model)]

        # Nothing retail in the partitions themselves: oplus defers to the
        # numbered project directory the bootloader selects.
        pairs: list[tuple[str, str]] = []
        for entry in self.tree(project, self.OVERLAY_DIR, ref):
            if entry.get("type") != "tree" or not entry["name"].isdigit():
                continue
            for leaf in self.tree(project, f"{self.OVERLAY_DIR}/{entry['name']}", ref):
                name = leaf.get("name", "")
                if not (name.startswith(self.OVERLAY_PREFIX)
                        and name.endswith(self.OVERLAY_SUFFIX)):
                    continue
                props = self.props(self.file(
                    project, f"{self.OVERLAY_DIR}/{entry['name']}/{name}", ref))
                model = self.pick(props, "odm", "model")
                manufacturer = self.pick(props, "odm", "manufacturer")
                if model and manufacturer:
                    pairs.append((manufacturer, model))

        return pairs

    # --- step 3: the harvest ---------------------------------------------

    def read_dump(self, item: tuple[str, int, str, int, str]) -> list[dict[str, Any]]:
        """Return one record per retail model a dump proves."""
        brand, project, ref, release, day = item
        return [{"brand": brand, "manufacturer": manufacturer, "code": code,
                 "android": release, "date": day, "project": project,
                 "last_seen": TODAY}
                for manufacturer, code in self.resolve(project, ref)
                if self.MODEL_SHAPE.fullmatch(code)
                and not self.MODEL_REJECT.search(code)]

    def records(self) -> list[dict[str, Any]]:
        """One record per (brand, model code) a retail dump has ever proved."""
        if self.cache.has(self.RECORDS_FILE):
            return self.cache.read_json(self.RECORDS_FILE)
        if self.cache.offline:
            # The janitor sets the file aside rather than deleting it, so an
            # offline rebuild right after a clean still has every device the
            # last harvest proved. It gains no new ones, which is the honest
            # outcome of having no network.
            if not self.cache.has(self.PREV_FILE):
                self.cache.missing(
                    f"no {self.RECORDS_FILE} in the cache; run once with "
                    f"network access")
            return self.store(self.merge([]))

        wanted: list[tuple[str, int, str, int, str]] = []
        for brand in self.BRANDS:
            fresh = self.dumps(brand)
            wanted += [(brand, project, branch, release, day)
                       for project, branch, release, day in fresh]
            print(f"  {brand}: {len(fresh)} dumps on Android {self.MIN_ANDROID}+")

        with ThreadPoolExecutor(max_workers=self.WORKERS) as pool:
            records = [r for batch in pool.map(self.read_dump, wanted) for r in batch]

        # Keep the newest Android release per (brand, code); several dumps of
        # one phone differ only by firmware age.
        best: dict[tuple[str, str], dict[str, Any]] = {}
        for record in records:
            key = (record["brand"], record["code"])
            current = best.get(key)
            if current is None or record["android"] > current["android"]:
                best[key] = record

        print(f"  resolved {len(best)} retail model codes")
        return self.store(self.merge(list(best.values())))

    # --- step 4: accumulate ----------------------------------------------

    def carried(self) -> list[dict[str, Any]]:
        """Whatever the previous harvest wrote, set aside under PREV_FILE."""
        if not self.cache.has(self.PREV_FILE):
            return []
        old = self.cache.read_json(self.PREV_FILE)
        # A file written before the harvest accumulated carries no sighting
        # date, and the only honest one available is when it was written.
        written = date.fromtimestamp(
            self.cache.path(self.PREV_FILE).stat().st_mtime).isoformat()
        print(f"  carrying {len(old)} records from the previous harvest")
        return [{**record, "last_seen": record.get("last_seen") or written}
                for record in old]

    def merge(self, fresh: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge `fresh` with what an earlier harvest proved.

        The result is `fresh` plus every device an earlier harvest proved and
        this run did not see again.

        The dumps group is listed newest first and only MAX_PAGES pages deep,
        so a phone scrolls out of the window as dumps pile up behind it -- we
        watched OPPOCPH2579 leave one run and come back in the next. Without
        this a device would silently leave the catalog the week its brand had
        a busy release season, which is the opposite of what the window means.
        A sighting therefore expires on its own schedule, after
        RECORD_MAX_AGE_DAYS, rather than at the end of the run that missed it.
        """
        kept = {(r["brand"], r["code"]): r for r in self.carried()}
        for record in fresh:
            key = (record["brand"], record["code"])
            was = kept.get(key)
            # `android` is a ceiling -- the newest release a dump ever proved
            # this phone runs -- so it never moves back down because this run
            # happened to see only an older regional dump of the same device.
            if was is not None and was["android"] > record["android"]:
                kept[key] = {**was, "last_seen": record["last_seen"]}
            else:
                kept[key] = record

        floor = (date.today()
                 - timedelta(days=self.RECORD_MAX_AGE_DAYS)).isoformat()
        current = [r for r in kept.values() if r["last_seen"] >= floor]
        if len(current) != len(kept):
            print(f"  dropping {len(kept) - len(current)} unseen since {floor}")
        if len(current) > len(fresh):
            print(f"  carried {len(current) - len(fresh)} "
                  f"no dump in this harvest reached")
        return current

    def store(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Write the accumulation, and retire the file it was merged from."""
        out = sorted(records, key=lambda r: (r["brand"], r["code"]))
        self.cache.write_json(self.RECORDS_FILE, out)
        self.cache.path(self.PREV_FILE).unlink(missing_ok=True)
        return out
