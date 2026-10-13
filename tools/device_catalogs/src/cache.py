"""The download cache: the only module that touches the network."""

from __future__ import annotations

import json
import os
import shutil
import stat
import urllib.request
from pathlib import Path
from typing import Any, Iterable, NoReturn

from .shared import CACHE_DIR, USER_AGENT

# =============================== cache ===============================

class Cache:
    """The download cache, and the only place that touches the network.

    The cache always wins over the network, even without `--offline`: that is
    what makes a rebuild deterministic and lets the whole script run with no
    connection. To genuinely refresh a source, delete its file (or the whole
    directory) first.
    """

    def __init__(self, directory: Path = CACHE_DIR, *, offline: bool = False) -> None:
        self.directory = directory
        self.offline = offline

    # --- paths -----------------------------------------------------------

    def path(self, name: str) -> Path:
        return self.directory / name

    def has(self, name: str) -> bool:
        return self.path(name).is_file()

    def missing(self, hint: str) -> NoReturn:
        """Abort because a cache entry `--offline` needs is not there."""

        raise SystemExit(hint)

    # --- cached downloads -------------------------------------------------

    def fetch(self, name: str, url: str) -> bytes:
        """`url`, from the cache when it is there and from the network when not."""

        path = self.path(name)
        if path.exists():
            return path.read_bytes()
        if self.offline:
            raise SystemExit(f"--offline but {path} is missing")

        data = self.download(url)
        self.directory.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"  downloaded {name} ({len(data)} bytes)")
        return data

    def fetch_text(
        self, 
        name: str, 
        url: str, *,
        encoding: str = "utf-8", 
        errors: str = "strict"
        ) -> str:

        return self.fetch(name, url).decode(encoding, errors)

    def fetch_json(self, name: str, url: str) -> Any:
        return json.loads(self.fetch(name, url))

    # --- uncached network -------------------------------------------------

    def download(self, url: str, *, timeout: int = 180) -> bytes:
        # `with`, not a bare call: the DMI and firmware steps download from a
        # dozen threads at once, and leaving each socket to the garbage
        # collector keeps connections open for as long as it takes to notice.
        request = urllib.request.Request(url, headers=USER_AGENT)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()

    def get_json(self, url: str) -> Any:
        """A single uncached request, for sources queried per device rather
        than downloaded whole (ipsw.me)."""

        return json.loads(self.download(url))

    # --- cache-only storage ----------------------------------------------

    def read_json(self, name: str) -> Any:
        return json.loads(self.path(name).read_text(encoding="utf-8"))

    def write_json(self, name: str, value: Any) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path(name).write_text(json.dumps(value), encoding="utf-8")

    def read_lines(self, name: str) -> list[str]:
        return self.path(name).read_text(encoding="utf-8").splitlines()

    def write_lines(self, name: str, lines: Iterable[str]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path(name).write_text("\n".join(lines), encoding="utf-8")

    def wipe(self, name: str) -> None:
        """Delete a cached directory, clearing read-only bits as it goes.

        git marks its objects read-only, which makes a plain rmtree fail on
        Windows and silently leave the clone behind.
        """

        def drop_readonly(func, path, _exc):
            os.chmod(path, stat.S_IWRITE)
            func(path)

        target = self.path(name)
        if target.exists():
            shutil.rmtree(target, onerror=drop_readonly)
