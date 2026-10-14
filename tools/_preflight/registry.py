"""Reading a tool's declarations -- sources/sources.toml and
ported/citations.toml -- into the model.

This is the only module that knows the file format, and it knows nothing
about any particular tool: discovery is a glob, so a new tool is registered
by dropping a file in, not by editing anything here.

Every unknown key is an error rather than a shrug. A registry is the record
of what a tool depends on, and a typo that silently drops a contract would
leave a source unchecked while the report says it passed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, ClassVar

from .model import (Citation, Contract, Derived, Fingerprint, Policy,
                    Registry, Source)

try:                                              # 3.11+
    import tomllib
except ModuleNotFoundError:                       # 3.10, via tools/requirements.txt
    try:
        import tomli as tomllib                   # type: ignore[no-redef]
    except ModuleNotFoundError:                   # pragma: no cover
        raise SystemExit(
            "reading sources.toml needs tomli on Python 3.10:\n"
            "    pip install -r tools/requirements.txt"
        ) from None


# ============================== discovery ==============================

class Layout:
    """The tool folder contract, in one place.

    A tool's root holds named sections and a single `__main__.py` door.
    Anything this class names is a section; everything else at that level is
    a structural mistake.
    """

    #: tools/, found from this module rather than from the caller's cwd.
    TOOLS_DIR: ClassVar[Path] = Path(__file__).resolve().parent.parent

    SOURCES: ClassVar[str] = "sources"
    REGISTRY_FILE: ClassVar[str] = "sources.toml"
    LOCK_FILE: ClassVar[str] = "sources.lock.json"

    CACHE: ClassVar[str] = ".cache"
    STATE_FILE: ClassVar[str] = "preflight.state.json"

    SRC: ClassVar[str] = "src"
    DOOR: ClassVar[str] = "__main__.py"

    SCHEDULE: ClassVar[str] = "schedule"
    SCHEDULE_FILE: ClassVar[str] = "schedule.toml"

    PORTED: ClassVar[str] = "ported"
    CITATIONS_FILE: ClassVar[str] = "citations.toml"

    #: Sections that land in later phases. Named here so the contract is
    #: readable in one place even before they exist.
    CONFIG: ClassVar[str] = "config"
    DOCS: ClassVar[str] = "docs"

    @classmethod
    def registry_path(cls, tool: str) -> Path:
        return cls.TOOLS_DIR / tool / cls.SOURCES / cls.REGISTRY_FILE

    @classmethod
    def lock_path(cls, tool: str) -> Path:
        return cls.TOOLS_DIR / tool / cls.SOURCES / cls.LOCK_FILE

    @classmethod
    def schedule_path(cls, tool: str) -> Path:
        return cls.TOOLS_DIR / tool / cls.SCHEDULE / cls.SCHEDULE_FILE

    @classmethod
    def citations_path(cls, tool: str) -> Path:
        return cls.TOOLS_DIR / tool / cls.PORTED / cls.CITATIONS_FILE

    @classmethod
    def cache_dir(cls, tool: str) -> Path:
        return cls.TOOLS_DIR / tool / cls.CACHE

    @classmethod
    def state_path(cls, tool: str) -> Path:
        return cls.cache_dir(tool) / cls.STATE_FILE

    @classmethod
    def tools(cls) -> list[str]:
        """Every tool that declares sources, in a stable order.

        `_preflight` itself is skipped for free: it is machinery, not a tool,
        so it has no `sources/` and the glob never finds it. No name is
        special-cased.
        """

        found = cls.TOOLS_DIR.glob(f"*/{cls.SOURCES}/{cls.REGISTRY_FILE}")
        return sorted(path.parent.parent.name for path in found)


# ============================== the parser ==============================

class RegistryError(SystemExit):
    """A malformed registry. Fatal: an unchecked source is worse than none."""


def _require(table: dict[str, Any], key: str, where: str) -> Any:
    if key not in table:
        raise RegistryError(f"{where}: missing required key {key!r}")
    return table[key]


def _reject_unknown(table: dict[str, Any], known: set[str], where: str) -> None:
    unknown = sorted(set(table) - known)
    if unknown:
        raise RegistryError(f"{where}: unknown key(s) {unknown}")


def _tuple(value: Any) -> tuple[str, ...]:
    return tuple(value) if isinstance(value, list) else ()


def _regex(pattern: str, key: str, where: str) -> str:
    """A pattern is compiled here or not at all.

    A typo in one is a malformed registry, and saying so at parse time is the
    difference between exit code 4 and a `re.PatternError` traceback out of
    the middle of a check that has already touched the network.
    """

    try:
        re.compile(pattern)
    except re.error as exc:
        raise RegistryError(f"{where}: {key} is not a valid regex: {exc}") from None
    return pattern


def _contract(table: dict[str, Any] | None, where: str) -> Contract | None:
    if table is None:
        return None
    _reject_unknown(table, {
        "kind", "encoding", "must_have_columns", "min_rows", "min_items",
        "item_keys", "object_keys", "must_contain", "must_match", "min_matches",
    }, where)

    kind = _require(table, "kind", where)
    if kind not in Contract.KINDS:
        raise RegistryError(
            f"{where}: contract kind {kind!r}; known: {sorted(Contract.KINDS)}")

    return Contract(
        kind=kind,
        encoding=table.get("encoding", "utf-8"),
        must_have_columns=_tuple(table.get("must_have_columns")),
        min_rows=int(table.get("min_rows", 0)),
        min_items=int(table.get("min_items", 0)),
        item_keys=_tuple(table.get("item_keys")),
        object_keys=_tuple(table.get("object_keys")),
        must_contain=_tuple(table.get("must_contain")),
        must_match=_regex(table.get("must_match", ""), "must_match", where),
        min_matches=int(table.get("min_matches", 0)),
    )


def _fingerprint(table: dict[str, Any] | None, where: str) -> Fingerprint | None:
    if table is None:
        return None
    _reject_unknown(table, {"kind", "pattern"}, where)

    kind = _require(table, "kind", where)
    if kind not in Fingerprint.KINDS:
        raise RegistryError(
            f"{where}: fingerprint kind {kind!r}; known: {sorted(Fingerprint.KINDS)}")
    if kind.startswith("regex") and not table.get("pattern"):
        raise RegistryError(f"{where}: fingerprint kind {kind!r} needs a pattern")

    return Fingerprint(
        kind=kind,
        pattern=_regex(table.get("pattern", ""), "pattern", where))


def _source(table: dict[str, Any], index: int) -> Source:
    where = f"[[source]] #{index} ({table.get('id', '?')})"
    _reject_unknown(table, {
        "id", "url", "probe_url", "cache", "on_change", "contract",
        "fingerprint", "consumed_by", "on_removal", "notes",
    }, where)

    source = Source(
        id=_require(table, "id", where),
        url=table.get("url", ""),
        probe_url=table.get("probe_url", ""),
        cache=table.get("cache", ""),
        on_change=table.get("on_change", Policy.DELETE),
        contract=_contract(table.get("contract"), where),
        fingerprint=_fingerprint(table.get("fingerprint"), where),
        consumed_by=table.get("consumed_by", ""),
        on_removal=table.get("on_removal", ""),
        notes=table.get("notes", ""),
    )

    if not source.target:
        raise RegistryError(f"{where}: needs either url or probe_url")
    if source.url and source.probe_url:
        raise RegistryError(f"{where}: url and probe_url are mutually exclusive")
    if source.url and not source.cache:
        raise RegistryError(f"{where}: a fetched url needs a cache name")
    if source.probe_url and source.cache:
        raise RegistryError(
            f"{where}: a probe_url caches nothing; declare its cache as [[derived]]")
    if source.on_change not in Policy.ALL:
        raise RegistryError(f"{where}: on_change {source.on_change!r}")
    for key in ("consumed_by", "on_removal"):
        if not getattr(source, key):
            raise RegistryError(
                f"{where}: {key} is required -- a failure report has to tell a "
                f"developer where this source is read and what its loss costs")
    return source


def _derived(table: dict[str, Any], index: int, source_ids: set[str]) -> Derived:
    where = f"[[derived]] #{index} ({table.get('id', '?')})"
    _reject_unknown(table, {
        "id", "cache", "derives_from", "on_change", "max_age_days",
        "record_max_age_days", "cost", "consumed_by", "notes",
    }, where)

    derived = Derived(
        id=_require(table, "id", where),
        cache=_require(table, "cache", where),
        derives_from=_tuple(table.get("derives_from")),
        on_change=table.get("on_change", Policy.DELETE),
        max_age_days=int(table.get("max_age_days", 0)),
        record_max_age_days=int(table.get("record_max_age_days", 0)),
        cost=table.get("cost", ""),
        consumed_by=table.get("consumed_by", ""),
        notes=table.get("notes", ""),
    )

    if derived.on_change not in Policy.ALL:
        raise RegistryError(f"{where}: on_change {derived.on_change!r}")
    if not derived.derives_from:
        raise RegistryError(
            f"{where}: derives_from is required -- a produced cache has no URL "
            f"to revalidate, so a source it was built from is the only signal")
    unknown = sorted(set(derived.derives_from) - source_ids)
    if unknown:
        raise RegistryError(f"{where}: derives_from names no such source: {unknown}")
    if derived.on_change == Policy.MERGE and not derived.record_max_age_days:
        raise RegistryError(
            f"{where}: on_change = 'merge' needs record_max_age_days, or the "
            f"file grows forever and keeps devices no dump has shown in years")
    return derived


# ---------------------------- [[citation]] ----------------------------

CITATION_KEYS = frozenset(
    {"id", "url", "anchors", "ported_to", "on_drift", "notes"})


def _citation(table: dict[str, Any], index: int) -> Citation:
    where = f"[[citation]] #{index} ({table.get('id', '?')})"
    _reject_unknown(table, CITATION_KEYS, where)

    for key in ("id", "url", "ported_to", "on_drift"):
        _require(table, key, where)

    anchors = _tuple(table.get("anchors"))
    if not anchors:
        raise RegistryError(
            f"{where}: anchors is required -- a citation with nothing to look "
            f"for would pass while the rule it quotes was rewritten")

    return Citation(
        id=str(table["id"]),
        url=str(table["url"]),
        anchors=anchors,
        ported_to=str(table["ported_to"]),
        on_drift=str(table["on_drift"]).strip(),
        notes=str(table.get("notes", "")).strip(),
    )


def _citations(tool: str) -> tuple[Citation, ...]:
    """Every ported rule the tool declares, or none.

    Optional on purpose: a tool that reimplements nothing has nothing to
    quote, and a missing file is that answer rather than an error.
    """

    path = Layout.citations_path(tool)
    if not path.is_file():
        return ()

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise RegistryError(f"{path}: {exc}") from None

    unknown = sorted(set(data) - {"citation"})
    if unknown:
        raise RegistryError(f"{path}: unknown top-level table(s) {unknown}")

    found = tuple(_citation(table, index)
                  for index, table in enumerate(data.get("citation", []), 1))
    ids = [c.id for c in found]
    duplicate = sorted({i for i in ids if ids.count(i) > 1})
    if duplicate:
        raise RegistryError(f"{path}: duplicate citation id(s) {duplicate}")
    return found


def load(tool: str) -> Registry:
    """Parse one tool's declarations. Raises `RegistryError` on anything odd."""

    path = Layout.registry_path(tool)
    if not path.is_file():
        raise RegistryError(
            f"no registry for {tool!r}: {path} is missing.\n"
            f"tools with one: {', '.join(Layout.tools()) or '(none)'}")

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise RegistryError(f"{path}: {exc}") from None

    meta = data.get("tool", {})
    _reject_unknown(meta, {"name", "scratch", "notes"}, "[tool]")
    declared = meta.get("name", tool)
    if declared != tool:
        raise RegistryError(
            f"{path}: [tool] name is {declared!r} but it sits in {tool!r}/")

    sources = tuple(_source(t, i) for i, t in enumerate(data.get("source", []), 1))
    ids = [s.id for s in sources]
    duplicate = sorted({i for i in ids if ids.count(i) > 1})
    if duplicate:
        raise RegistryError(f"{path}: duplicate source id(s) {duplicate}")

    derived = tuple(
        _derived(t, i, set(ids)) for i, t in enumerate(data.get("derived", []), 1))

    citations = _citations(tool)
    clash = sorted(set(ids) & {c.id for c in citations})
    if clash:
        raise RegistryError(
            f"{path}: {clash} is declared as both a source and a citation; "
            f"one body cannot be two kinds of promise")

    caches = [s.cache for s in sources if s.cache] + [d.cache for d in derived]
    clashing = sorted({c for c in caches if caches.count(c) > 1})
    if clashing:
        raise RegistryError(f"{path}: two entries claim the same cache file {clashing}")

    return Registry(
        tool=tool,
        tool_dir=Layout.TOOLS_DIR / tool,
        cache_dir=Layout.cache_dir(tool),
        scratch=_tuple(meta.get("scratch")),
        sources=sources,
        derived=derived,
        citations=citations,
        deferred={k: len(v) for k, v in data.items()
                  if k in ("watch",) and isinstance(v, list)},
    )
