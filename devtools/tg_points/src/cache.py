"""The download cache: the only module that touches the network."""

from __future__ import annotations as _annotations

import urllib.request
from http.client import HTTPException
from pathlib import Path
from typing import ClassVar


class Cache:
    """The download cache, and the only place that touches the network.

    The cache always wins over the network, even without `--offline`: that is
    what makes a rebuild deterministic. Preflight deletes a file when its
    source changes upstream, and the next run fetches it again.
    """

    DIRECTORY: ClassVar[Path] = Path(__file__).resolve().parent.parent / ".cache"
    USER_AGENT: ClassVar[dict[str, str]] = {"User-Agent": "pytrove-tg-points"}
    TIMEOUT: ClassVar[int] = 60

    def __init__(self, directory: Path = DIRECTORY, *, offline: bool = False) -> None:
        """Cache under `directory`; `offline` forbids any network access."""
        self.directory = directory
        self.offline = offline

    def fetch(self, name: str, url: str) -> bytes:
        """Return the cache entry `name`, downloading it from `url` when absent.

        A source that does not answer stops the build: an outage is never read
        as an empty source, so nothing is written from half the data.
        """
        path = self.directory / name
        if path.is_file():
            return path.read_bytes()
        if self.offline:
            msg = f"--offline but {path} is missing"
            raise SystemExit(msg)

        request = urllib.request.Request(url, headers=self.USER_AGENT)
        try:
            with urllib.request.urlopen(request, timeout=self.TIMEOUT) as response:
                data = response.read()
        except (OSError, HTTPException) as exc:
            msg = f"{url} did not answer ({type(exc).__name__}: {exc})"
            raise SystemExit(msg) from exc

        self.directory.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"  downloaded {name} ({len(data)} bytes)")
        return data
