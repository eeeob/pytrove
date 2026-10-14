"""Reading a tool's declarations into the model.

The only module that knows the file format, and it knows nothing about any
particular tool: discovery is a glob over `tools/*/sources/sources.toml`, so a
new tool is registered by dropping a file in rather than by editing anything
here. Four files, one section kind each:

    sources/sources.toml    [tool], [[source]], [[derived]]
    ported/citations.toml   [[citation]]
    config/config.toml      [[watch]]
    schedule/schedule.toml  [schedule]

Only the first is required; a tool that reimplements nothing has nothing to
cite, and one nobody has decided how often to watch has no schedule.

**Every unknown key is an error rather than a shrug.** A declaration is the
record of what a tool depends on, and a typo that silently dropped a contract
would leave a source unchecked while every report said it passed. The same
goes for a regex: it is compiled here or not at all, so a bad pattern is exit
code 4 before the first request rather than a traceback out of the middle of a
check that has already touched the network.
"""

from __future__ import annotations

import re
from typing import Any, Final

from .enums import ContractKind, FingerprintKind, Policy
from .layout import Layout
from .models import (Citation, Contract, Derived, Fingerprint, Registry,
                     Schedule, Source, Watch)

try:                                              # 3.11+
    import tomllib
except ModuleNotFoundError:                       # 3.10, via tools/requirements.txt
    try:
        import tomli as tomllib                   # type: ignore[no-redef]
    except ModuleNotFoundError:                   # pragma: no cover
        raise SystemExit(
            "reading a tool's .toml declarations needs tomli on Python 3.10:\n"
            "    pip install -r tools/requirements.txt"
        ) from None


class RegistryError(SystemExit):
    """A malformed declaration. Fatal: an unchecked source is worse than none.

    One error type for all four files, because to everything upstream of here
    they are one situation with one response -- and the command line already
    turns it into the single exit code that means "the files describing this
    tool are wrong".
    """


# ============================== small validators ==============================

def _require(table: dict[str, Any], key: str, where: str) -> Any:
    if key not in table:
        raise RegistryError(f"{where}: missing required key {key!r}")
    return table[key]


def _reject_unknown(table: dict[str, Any], known: frozenset[str],
                    where: str) -> None:
    unknown = sorted(set(table) - known)
    if unknown:
        raise RegistryError(f"{where}: unknown key(s) {unknown}")


def _tuple(value: Any) -> tuple[str, ...]:
    return tuple(value) if isinstance(value, list) else ()


def _regex(pattern: str, key: str, where: str) -> str:
    try:
        re.compile(pattern)
    except re.error as exc:
        raise RegistryError(f"{where}: {key} is not a valid regex: {exc}") from None
    return pattern


def _member(enum: type, value: Any, key: str, where: str) -> Any:
    """One of a closed set of values, by name of the thing it describes."""

    try:
        return enum(value)
    except ValueError:
        known = sorted(member.value for member in enum)
        raise RegistryError(
            f"{where}: {key} {value!r}; known: {known}") from None


def _toml(path: Any) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise RegistryError(f"{path}: {exc}") from None


def _only_tables(data: dict[str, Any], known: frozenset[str], path: Any) -> None:
    unknown = sorted(set(data) - known)
    if unknown:
        raise RegistryError(f"{path}: unknown top-level table(s) {unknown}")


def _duplicates(ids: list[str]) -> list[str]:
    return sorted({i for i in ids if ids.count(i) > 1})


# ============================== how a body is judged ==============================

CONTRACT_KEYS: Final[frozenset[str]] = frozenset({
    "kind", "encoding", "must_have_columns", "min_rows", "min_items",
    "item_keys", "object_keys", "must_contain", "must_match", "min_matches"})

FINGERPRINT_KEYS: Final[frozenset[str]] = frozenset({"kind", "pattern"})


def _contract(table: dict[str, Any] | None, where: str) -> Contract | None:
    if table is None:
        return None
    _reject_unknown(table, CONTRACT_KEYS, where)

    return Contract(
        kind=_member(ContractKind, _require(table, "kind", where),
                     "contract kind", where),
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
    _reject_unknown(table, FINGERPRINT_KEYS, where)

    kind = _member(FingerprintKind, _require(table, "kind", where),
                   "fingerprint kind", where)
    if kind.needs_pattern and not table.get("pattern"):
        raise RegistryError(f"{where}: fingerprint kind {kind} needs a pattern")

    return Fingerprint(
        kind=kind,
        pattern=_regex(table.get("pattern", ""), "pattern", where))


# ============================== sources/sources.toml ==============================

TOOL_KEYS: Final[frozenset[str]] = frozenset({"name", "scratch", "notes"})

SOURCE_KEYS: Final[frozenset[str]] = frozenset({
    "id", "url", "probe_url", "cache", "on_change", "contract",
    "fingerprint", "consumed_by", "on_removal", "notes"})

DERIVED_KEYS: Final[frozenset[str]] = frozenset({
    "id", "cache", "derives_from", "on_change", "max_age_days",
    "record_max_age_days", "cost", "consumed_by", "notes"})


def _source(table: dict[str, Any], index: int) -> Source:
    where = f"[[source]] #{index} ({table.get('id', '?')})"
    _reject_unknown(table, SOURCE_KEYS, where)

    source = Source(
        id=_require(table, "id", where),
        url=table.get("url", ""),
        probe_url=table.get("probe_url", ""),
        cache=table.get("cache", ""),
        on_change=_member(Policy, table.get("on_change", Policy.DELETE),
                          "on_change", where),
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
    for key in ("consumed_by", "on_removal"):
        if not getattr(source, key):
            raise RegistryError(
                f"{where}: {key} is required -- a failure report has to tell a "
                f"developer where this source is read and what its loss costs")
    return source


def _derived(table: dict[str, Any], index: int, source_ids: set[str]) -> Derived:
    where = f"[[derived]] #{index} ({table.get('id', '?')})"
    _reject_unknown(table, DERIVED_KEYS, where)

    derived = Derived(
        id=_require(table, "id", where),
        cache=_require(table, "cache", where),
        derives_from=_tuple(table.get("derives_from")),
        on_change=_member(Policy, table.get("on_change", Policy.DELETE),
                          "on_change", where),
        max_age_days=int(table.get("max_age_days", 0)),
        record_max_age_days=int(table.get("record_max_age_days", 0)),
        cost=table.get("cost", ""),
        consumed_by=table.get("consumed_by", ""),
        notes=table.get("notes", ""),
    )

    if not derived.derives_from:
        raise RegistryError(
            f"{where}: derives_from is required -- a produced cache has no URL "
            f"to revalidate, so a source it was built from is the only signal")
    unknown = sorted(set(derived.derives_from) - source_ids)
    if unknown:
        raise RegistryError(f"{where}: derives_from names no such source: {unknown}")
    if derived.on_change is Policy.MERGE and not derived.record_max_age_days:
        raise RegistryError(
            f"{where}: on_change = 'merge' needs record_max_age_days, or the "
            f"file grows forever and keeps devices no dump has shown in years")
    return derived


# ============================== ported/citations.toml ==============================

CITATION_KEYS: Final[frozenset[str]] = frozenset({
    "id", "url", "anchors", "ported_to", "on_drift", "notes"})


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
    path = Layout.citations_path(tool)
    if not path.is_file():
        return ()

    data = _toml(path)
    _only_tables(data, frozenset({"citation"}), path)
    found = tuple(_citation(table, index)
                  for index, table in enumerate(data.get("citation", []), 1))

    duplicate = _duplicates([c.id for c in found])
    if duplicate:
        raise RegistryError(f"{path}: duplicate citation id(s) {duplicate}")
    return found


# ============================== config/config.toml ==============================

WATCH_KEYS: Final[frozenset[str]] = frozenset({
    "id", "url", "value", "fingerprint", "used_by", "decision", "notes"})


def _watch(table: dict[str, Any], index: int) -> Watch:
    where = f"[[watch]] #{index} ({table.get('id', '?')})"
    _reject_unknown(table, WATCH_KEYS, where)

    for key in ("id", "url", "value", "used_by", "decision"):
        _require(table, key, where)

    block = table.get("fingerprint")
    if not isinstance(block, dict):
        raise RegistryError(
            f"{where}: needs a [watch.fingerprint] block -- without one there "
            f"is no number to compare the declared value against")

    return Watch(
        id=str(table["id"]),
        url=str(table["url"]),
        value=table["value"],
        fingerprint=_fingerprint(block, where),
        used_by=str(table["used_by"]),
        decision=str(table["decision"]).strip(),
        notes=str(table.get("notes", "")).strip(),
    )


def _watches(tool: str) -> tuple[Watch, ...]:
    path = Layout.config_path(tool)
    if not path.is_file():
        return ()

    data = _toml(path)
    _only_tables(data, frozenset({"watch"}), path)
    found = tuple(_watch(table, index)
                  for index, table in enumerate(data.get("watch", []), 1))

    duplicate = _duplicates([w.id for w in found])
    if duplicate:
        raise RegistryError(f"{path}: duplicate watch id(s) {duplicate}")
    return found


# ============================== schedule/schedule.toml ==============================

SCHEDULE_SECTION: Final[str] = "schedule"
SCHEDULE_KEYS: Final[frozenset[str]] = frozenset({"cron", "notes"})


def load_schedule(tool: str) -> Schedule:
    """Parse one tool's cadence. Raises `RegistryError` on anything odd.

    Kept out of `Registry` because it is not something the checker compares
    against anything: it says how often the check runs, which only the report
    and the workflow care about.
    """

    path = Layout.schedule_path(tool)
    where = f"{path.parent.name}/{path.name}"

    if not path.is_file():
        raise RegistryError(f"{where}: {tool} declares no schedule")

    table = _toml(path).get(SCHEDULE_SECTION)
    if not isinstance(table, dict):
        raise RegistryError(f"{where}: missing the [{SCHEDULE_SECTION}] table")
    _reject_unknown(table, SCHEDULE_KEYS, where)

    cron = str(table.get("cron", "")).strip()
    if not cron:
        raise RegistryError(f"{where}: [{SCHEDULE_SECTION}] needs cron")

    schedule = Schedule(tool=tool, cron=cron,
                        notes=str(table.get("notes", "")).strip())
    if not schedule.every_days:
        raise RegistryError(
            f"{where}: cron {cron!r} is not a cadence that can be stated in "
            f"days. Use 'm h * * D' for weekly, 'm h D * *' for monthly or "
            f"'m h * * *' for daily -- anything else leaves the escalation "
            f"rule unable to say how long three runs is.")
    return schedule


def find_schedule(tool: str) -> Schedule | None:
    """The tool's cadence, or None when it declares none.

    Soft on purpose. A check run by hand needs no cadence at all, and a tool
    is allowed to exist before anyone has decided how often to watch it; the
    place a missing schedule matters is the workflow, and a test is what
    notices it there.
    """

    return load_schedule(tool) if Layout.schedule_path(tool).is_file() else None


# ============================== the whole declaration ==============================

def load(tool: str) -> Registry:
    """Parse one tool's declarations. Raises `RegistryError` on anything odd."""

    path = Layout.registry_path(tool)
    if not path.is_file():
        raise RegistryError(
            f"no registry for {tool!r}: {path} is missing.\n"
            f"tools with one: {', '.join(Layout.tools()) or '(none)'}")

    data = _toml(path)
    meta = data.get("tool", {})
    _reject_unknown(meta, TOOL_KEYS, "[tool]")

    declared = meta.get("name", tool)
    if declared != tool:
        raise RegistryError(
            f"{path}: [tool] name is {declared!r} but it sits in {tool!r}/")

    sources = tuple(_source(t, i) for i, t in enumerate(data.get("source", []), 1))
    ids = [s.id for s in sources]
    duplicate = _duplicates(ids)
    if duplicate:
        raise RegistryError(f"{path}: duplicate source id(s) {duplicate}")

    derived = tuple(
        _derived(t, i, set(ids)) for i, t in enumerate(data.get("derived", []), 1))

    citations = _citations(tool)
    watches = _watches(tool)

    declared_ids = [*ids, *(c.id for c in citations), *(w.id for w in watches)]
    clash = _duplicates(declared_ids)
    if clash:
        raise RegistryError(
            f"{path}: {clash} is declared more than once across sources, "
            f"citations and watches; each id is one kind of promise")

    caches = [s.cache for s in sources if s.cache] + [d.cache for d in derived]
    clashing = _duplicates(caches)
    if clashing:
        raise RegistryError(f"{path}: two entries claim the same cache file {clashing}")

    return Registry(
        tool=tool,
        tool_dir=Layout.tool_dir(tool),
        cache_dir=Layout.cache_dir(tool),
        scratch=_tuple(meta.get("scratch")),
        sources=sources,
        derived=derived,
        citations=citations,
        watches=watches,
    )
