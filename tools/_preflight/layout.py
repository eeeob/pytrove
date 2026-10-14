"""The tool folder contract, as code.

One place that knows where anything lives. Every path this package reads or
writes is derived here from a tool's name, so a section that moves is one
edit rather than a search, and no other module ever joins a path by hand.

Imports nothing from the package. It is the answer to "where", and that
question has no opinions in it.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

# ============================== the contract ==============================

class Layout:
    """A tool's root holds named sections and a single `__main__.py` door.

    Anything this class names is a section; any other `.py` at that level is
    a structural mistake, visible at a glance:

        tools/<tool>/
          __main__.py       the door. imports from src/ and nothing else
          src/              the logic
          sources/          sources.toml, sources.lock.json
          schedule/         schedule.toml
          ported/           citations.toml
          config/           config.toml
          docs/             DEVELOPING.md -- for people, not for this package
          .cache/           downloads + preflight.state.json  (gitignored)

    A new tool implements that and gets everything in this package for free.
    """

    #: tools/, found from this module rather than from the caller's cwd, so a
    #: check behaves the same from the repository root and from anywhere else.
    TOOLS_DIR: ClassVar[Path] = Path(__file__).resolve().parent.parent

    SRC: ClassVar[str] = "src"
    DOOR: ClassVar[str] = "__main__.py"

    SOURCES: ClassVar[str] = "sources"
    REGISTRY_FILE: ClassVar[str] = "sources.toml"
    LOCK_FILE: ClassVar[str] = "sources.lock.json"

    SCHEDULE: ClassVar[str] = "schedule"
    SCHEDULE_FILE: ClassVar[str] = "schedule.toml"

    PORTED: ClassVar[str] = "ported"
    CITATIONS_FILE: ClassVar[str] = "citations.toml"

    CONFIG: ClassVar[str] = "config"
    CONFIG_FILE: ClassVar[str] = "config.toml"

    #: The only section this package does not read: it is for whoever
    #: maintains the tool. Named here anyway, so the contract is stated in
    #: one place and a tool cannot ship without its guide unnoticed.
    DOCS: ClassVar[str] = "docs"
    DOCS_FILE: ClassVar[str] = "DEVELOPING.md"

    CACHE: ClassVar[str] = ".cache"
    STATE_FILE: ClassVar[str] = "preflight.state.json"

    #: Inserted before the extension when the janitor sets a `merge` cache
    #: aside: `firmware_records.json` -> `firmware_records.prev.json`. Before
    #: rather than after, so the file keeps its type and the tool can read it
    #: with the same loader it uses for the real one.
    #:
    #: This string is the entire interface between this package and a tool's
    #: accumulating cache. Neither imports the other; the tool learns only
    #: that the file may appear under this name, and when it does not,
    #: nothing accumulates and nothing breaks.
    PREV: ClassVar[str] = ".prev"

    # --- one tool's paths -------------------------------------------------

    @classmethod
    def tool_dir(cls, tool: str) -> Path:
        return cls.TOOLS_DIR / tool

    @classmethod
    def registry_path(cls, tool: str) -> Path:
        return cls.tool_dir(tool) / cls.SOURCES / cls.REGISTRY_FILE

    @classmethod
    def lock_path(cls, tool: str) -> Path:
        return cls.tool_dir(tool) / cls.SOURCES / cls.LOCK_FILE

    @classmethod
    def schedule_path(cls, tool: str) -> Path:
        return cls.tool_dir(tool) / cls.SCHEDULE / cls.SCHEDULE_FILE

    @classmethod
    def citations_path(cls, tool: str) -> Path:
        return cls.tool_dir(tool) / cls.PORTED / cls.CITATIONS_FILE

    @classmethod
    def config_path(cls, tool: str) -> Path:
        return cls.tool_dir(tool) / cls.CONFIG / cls.CONFIG_FILE

    @classmethod
    def docs_path(cls, tool: str) -> Path:
        return cls.tool_dir(tool) / cls.DOCS / cls.DOCS_FILE

    @classmethod
    def cache_dir(cls, tool: str) -> Path:
        return cls.tool_dir(tool) / cls.CACHE

    @classmethod
    def state_path(cls, tool: str) -> Path:
        return cls.cache_dir(tool) / cls.STATE_FILE

    @classmethod
    def aside(cls, path: Path) -> Path:
        """Where a `merge` cache goes when it is set aside."""

        return path.with_name(f"{path.stem}{cls.PREV}{path.suffix}")

    @classmethod
    def is_aside(cls, path: Path) -> bool:
        """Whether a cache file is one already set aside for merging.

        Checked two ways because `.suffixes` only sees a dotted tail: a name
        with no extension at all still carries the marker inline.
        """

        return cls.PREV in path.suffixes or f"{cls.PREV}." in path.name

    # --- discovery --------------------------------------------------------

    @classmethod
    def tools(cls) -> list[str]:
        """Every tool that declares sources, in a stable order.

        `_preflight` itself is skipped for free: it is machinery, not a tool,
        so it has no `sources/` and the glob never finds it. No name is
        special-cased anywhere in this package.
        """

        found = cls.TOOLS_DIR.glob(f"*/{cls.SOURCES}/{cls.REGISTRY_FILE}")
        return sorted(path.parent.parent.name for path in found)
