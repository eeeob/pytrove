"""The output contract: one finished catalog, ready to serialize."""

from __future__ import annotations as _annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .shared import OUT_DIR, ROOT, SCHEMA, TODAY

# ============================== output ==============================

@dataclass(frozen=True, slots=True)
class Catalog:
    """One platform's finished catalog, ready to serialize.

    The field order here is the key order in the file, so a rebuild of
    unchanged data produces an unchanged file and a real change shows up as a
    small diff.

    A platform that runs one OS documents itself with the four flat fields. A
    platform that runs several -- desktop, where the same PC reports Windows or
    Linux -- fills `os` instead, because the formats, sources and caveats are
    genuinely per-OS and flattening them would lose that.
    """

    platform: str
    versions: list[dict[str, Any]]
    devices: list[dict[str, Any]]

    model_format: str = ""
    version_format: str = ""
    sources: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    os: dict[str, dict[str, Any]] | None = None

    def write(self, out_dir: Path = OUT_DIR) -> Path:
        """Write this catalog as JSON under `out_dir` and return its path."""
        out_dir.mkdir(parents=True, exist_ok=True)

        payload: dict[str, Any] = {
            "schema": SCHEMA,
            "platform": self.platform,
            "updated": TODAY,
        }
        if self.os is not None:
            payload["os"] = self.os
        else:
            payload["model_format"] = self.model_format
            payload["version_format"] = self.version_format
            payload["sources"] = self.sources
            payload["notes"] = self.notes
        payload["versions"] = self.versions
        payload["devices"] = self.devices

        # newline="\n" on purpose: without it Python's text mode writes CRLF on
        # Windows and LF everywhere else, so the same cache would produce two
        # different files and "a rebuild is byte-identical" would hold only per
        # platform. git hides this when core.autocrlf is on; the generator
        # should not depend on that.
        path = out_dir / f"{self.platform}.json"
        path.write_text(json.dumps(payload, indent=1, ensure_ascii=False),
                        encoding="utf-8", newline="\n")
        print(f"{self.platform}: {len(self.devices)} devices, "
              f"{len(self.versions)} versions -> {path.relative_to(ROOT)}")
        return path
