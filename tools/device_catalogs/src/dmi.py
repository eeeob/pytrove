"""Real dmidecode records from linuxhw/DMI, for PC hardware."""

from __future__ import annotations as _annotations

import collections
import re
import subprocess
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import ClassVar
from collections.abc import Iterable

from .cache import Cache

# ------------------------- DMI harvest (PC hardware) -------------------------

class DmiHarvest:
    """Real `dmidecode` records from linuxhw/DMI.

    The folder names in that repository are its own labels, not what a machine
    reports -- a Lenovo folder reads "ThinkPad T540p 20BE004EUS" while the
    firmware says "20BE004EUS", HP folders drop the "HP " the firmware really
    sends, and ASUS or Gigabyte DIY boards report "System Product Name" or
    "To be filled by O.E.M.". So the fields have to come out of the probe files
    themselves.
    """

    REPO: ClassVar[str] = "https://github.com/linuxhw/DMI.git"
    RAW: ClassVar[str] = "https://raw.githubusercontent.com/linuxhw/DMI/master/"
    #: Probe paths are <Category>/<Vendor>/<Family>/<Model>/<probe id>.
    PATH_DEPTH: ClassVar[int] = 5
    CATEGORIES: ClassVar[frozenset[str]] = frozenset(
        {"Desktop", "Notebook", "All In One", "Mini Pc", "Convertible"})
    #: Probes read per vendor folder. One probe per distinct model folder, so
    #: this is a model count, not a machine count.
    SAMPLES: ClassVar[int] = 420
    WORKERS: ClassVar[int] = 16

    #: The share of the sample that must actually arrive. Sixteen threads
    #: against raw.githubusercontent gets throttled, and a throttled probe was
    #: dropped silently: a cold rebuild then wrote a catalog built from a
    #: slightly different sample every time, which is why eleven of 821 models
    #: changed between two builds of an identical commit. The loss cannot be
    #: removed -- it is somebody else's rate limit -- but it can be stated and
    #: it can be bounded, so a badly throttled run stops instead of quietly
    #: producing a thinner catalogue. Normal loss is well under one percent.
    MIN_READ: ClassVar[float] = 0.90

    PATHS_FILE: ClassVar[str] = "dmi_paths.txt"
    RECORDS_FILE: ClassVar[str] = "dmi_records.json"
    CLONE_DIR: ClassVar[str] = "dmi-repo"

    #: linuxhw/DMI vendor folder -> the group weighted in _devices.GROUP_SHARES.
    #: A folder absent from here is skipped entirely.
    VENDORS: ClassVar[dict[str, str]] = {
        "Lenovo": "Lenovo", "Lenovo Product": "Lenovo",
        "Hewlett-Packard": "HP", "HPE": "HP",
        "Dell": "Dell", "Dell Inc.": "Dell", "Dell System": "Dell", "DellInc.": "Dell",
        "ASUSTek Computer": "ASUS",
        "Acer": "Acer",
        "MSI": "MSI",
        "Gigabyte Technology": "Gigabyte",
        "ASRock": "ASRock", "ASRock Industrial": "ASRock",
        "Microsoft": "Other", "Apple": "Other", "Framework": "Other",
        "Intel": "Other", "Samsung Electronics": "Other", "LG Electronics": "Other",
        "Sony": "Other", "Toshiba": "Other", "Fujitsu": "Other", "Supermicro": "Other",
    }

    #: field name -> (dmidecode block, key inside it). `chassis` is captured
    #: for provenance only; the chassis fallback weights are estimates.
    FIELDS: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("product", "System Information", "Product Name"),
        ("family", "System Information", "Family"),
        ("board", "Base Board Information", "Product Name"),
        ("bios", "BIOS Information", "Release Date"),
        ("chassis", "Chassis Information", "Type"),
    )

    def __init__(self, cache: Cache) -> None:
        """Compile the dmidecode patterns for every field this harvest reads."""
        self.cache = cache
        self.patterns = {
            name: (re.compile(r"^" + block + r"\n((?:\t.*\n)+)", re.M),
                   re.compile(r"^\t" + re.escape(key) + r": (.*)$", re.M))
            for name, block, key in self.FIELDS
        }

    # --- step 1: the path list -------------------------------------------

    def paths(self) -> list[str]:
        """Every probe path, via a blobless shallow clone.

        The git protocol is used rather than the GitHub API because the API
        caps anonymous callers at 60 requests an hour and truncates large
        trees, which silently starved whole vendors. `--filter=blob:none`
        fetches the trees only: a few megabytes for ~160k paths.
        """
        if self.cache.has(self.PATHS_FILE):
            return self.cache.read_lines(self.PATHS_FILE)
        if self.cache.offline:
            self.cache.missing(
                f"no {self.PATHS_FILE} in the cache; run once with network access")

        repo = self.cache.path(self.CLONE_DIR)
        self.cache.wipe(self.CLONE_DIR)
        self.cache.directory.mkdir(parents=True, exist_ok=True)

        print("  cloning linuxhw/DMI (trees only)")
        self.git("clone", "--filter=blob:none", "--no-checkout",
                 "--depth", "1", "--single-branch", self.REPO, str(repo))
        listing = self.git("-C", str(repo), "ls-tree", "-r", "--name-only", "HEAD")
        self.cache.wipe(self.CLONE_DIR)

        paths = listing.splitlines()
        self.cache.write_lines(self.PATHS_FILE, paths)
        print(f"  {len(paths)} probe paths")
        return paths

    @staticmethod
    def git(*args: str) -> str:
        """Run `git` with `args` and return its decoded standard output."""
        done = subprocess.run(["git", *args], check=True, capture_output=True)
        return done.stdout.decode("utf-8", "replace")

    # --- step 2: which probes to read ------------------------------------

    def sample(self, paths: Iterable[str]) -> list[tuple[str, str]]:
        """Pick one probe per distinct (vendor, model) folder.

        Probes are spread evenly across each vendor's models rather than
        taking the first N alphabetically.
        """
        seen: set[tuple[str, str]] = set()
        per_folder: dict[str, list[str]] = collections.defaultdict(list)

        for path in paths:
            parts = path.split("/")
            if len(parts) != self.PATH_DEPTH or parts[0] not in self.CATEGORIES:
                continue
            vendor, model = parts[1], parts[3]
            if vendor not in self.VENDORS or (vendor, model) in seen:
                continue
            seen.add((vendor, model))
            per_folder[vendor].append(path)

        wanted: list[tuple[str, str]] = []
        for vendor, vendor_paths in sorted(per_folder.items()):
            step = max(1, len(vendor_paths) // self.SAMPLES)
            wanted += [(vendor, p) for p in sorted(vendor_paths)[::step][:self.SAMPLES]]

        print(f"  sampling {len(wanted)} probes across {len(per_folder)} vendor folders")
        return wanted

    # --- step 3: read them -----------------------------------------------

    def read_probe(self, item: tuple[str, str]) -> dict[str, str] | None:
        """Read one probe's DMI fields, or None when it cannot be fetched."""
        vendor, path = item
        try:
            text = self.cache.download(self.RAW + urllib.parse.quote(path), timeout=90)
        except Exception:                                 # noqa: BLE001 - skip the probe
            return None

        body = text.decode("utf-8", "replace")
        record = {"vendor": self.VENDORS[vendor], "folder": vendor}
        for name, (block_rx, key_rx) in self.patterns.items():
            block = block_rx.search(body)
            hit = key_rx.search(block.group(1)) if block else None
            record[name] = hit.group(1).strip() if hit else ""
        return record

    def records(self) -> list[dict[str, str]]:
        """The DMI fields the client actually reads, from real machines."""
        if self.cache.has(self.RECORDS_FILE):
            return self.cache.read_json(self.RECORDS_FILE)
        if self.cache.offline:
            self.cache.missing(
                f"no {self.RECORDS_FILE} in the cache; run once with network access")

        wanted = self.sample(self.paths())
        with ThreadPoolExecutor(max_workers=self.WORKERS) as pool:
            records = [r for r in pool.map(self.read_probe, wanted) if r]

        lost = len(wanted) - len(records)
        print(f"  read {len(records)} of {len(wanted)} probes"
              + (f" ({lost} unreachable)" if lost else ""))
        if wanted and len(records) < len(wanted) * self.MIN_READ:
            msg = (
                f"only {len(records)} of {len(wanted)} DMI probes could be read "
                f"({len(records) / len(wanted):.0%}, floor "
                f"{self.MIN_READ:.0%}).\nraw.githubusercontent is rate limiting "
                f"this run; nothing was written. retry later."
            )
            raise SystemExit(msg)
        self.cache.write_json(self.RECORDS_FILE, records)
        return records
