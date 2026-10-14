"""Tests for tools/_preflight and the tool folder contract.

`tools/` is development-only and ships in no wheel, so these tests skip
entirely when it is absent rather than failing. Nothing here touches the
network: the probing is exercised through its classification, which is the
part with decisions in it.

The test that earns its place most is `test_every_cache_file_is_declared`.
A registry is only as good as its completeness, and a source somebody adds to
a tool but forgets to register would never be checked at all while every
report says the sources are fine. That one makes the omission a failure.
"""

from __future__ import annotations

import ast
import json
import re
import socket
import sys
import urllib.error
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
PREFLIGHT = TOOLS / "_preflight"

pytestmark = pytest.mark.skipif(
    not PREFLIGHT.is_dir(), reason="tools/ is not installed")

if TOOLS.parent.as_posix() not in [p.replace("\\", "/") for p in sys.path]:
    sys.path.insert(0, str(TOOLS.parent))

from tools._preflight import model as _model                      # noqa: E402
from tools._preflight import registry as _registry                # noqa: E402
from tools._preflight import schedule as _schedule              # noqa: E402
from tools._preflight import cli as _cli                           # noqa: E402
from tools._preflight.check import Checker, Report                # noqa: E402
from tools._preflight.contract import ContractCheck               # noqa: E402
from tools._preflight.fingerprint import FingerprintValue         # noqa: E402
from tools._preflight.janitor import Action, Janitor              # noqa: E402
from tools._preflight.lock import Lock                            # noqa: E402
from tools._preflight.probe import Health, Prober                 # noqa: E402
from tools._preflight.report import TextReport                   # noqa: E402

Contract = _model.Contract
Fingerprint = _model.Fingerprint
Policy = _model.Policy
Registry = _model.Registry
Source = _model.Source
Derived = _model.Derived
State = _model.State
Verdict = _model.Verdict
Layout = _registry.Layout


# =============================== fixtures ===============================

@pytest.fixture(scope="module", params=Layout.tools())
def tool(request):
    """Every tool that declares sources, so a new one is covered for free."""

    return request.param


@pytest.fixture(scope="module")
def loaded(tool):
    return _registry.load(tool)


# ======================== the tool folder contract ========================

def test_at_least_one_tool_declares_sources():
    assert Layout.tools(), "no tools/*/sources/sources.toml found"


def test_preflight_is_machinery_and_not_a_tool():
    # It has no sources of its own, so the discovery glob never finds it and
    # nothing has to exclude it by name. If that ever changes, the generic
    # checker would start checking itself.
    assert "_preflight" not in Layout.tools()
    assert not (PREFLIGHT / Layout.SOURCES).exists()


def test_the_tool_root_holds_sections_and_exactly_one_door(tool):
    root = TOOLS / tool
    files = sorted(p.name for p in root.iterdir() if p.is_file())

    assert files == [Layout.DOOR], (
        f"{tool}/ should hold only {Layout.DOOR} as a file; found {files}. "
        f"Logic belongs in {Layout.SRC}/, declarations in a named section.")
    assert (root / Layout.SRC).is_dir()


def test_the_door_only_reaches_into_src(tool):
    """The door must not import the preflight package.

    This is the direction that must never reverse: the tool depends on
    nothing here, so it runs identically with preflight absent. Checked
    against the imports rather than the text, because the docstring is free
    to explain where checking lives -- prose is not a dependency.
    """

    import ast

    door = (TOOLS / tool / Layout.DOOR)
    tree = ast.parse(door.read_text(encoding="utf-8"))
    imported = {
        name.name
        for node in ast.walk(tree) if isinstance(node, ast.Import)
        for name in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }

    assert not any("_preflight" in name for name in imported), sorted(imported)
    assert any(name.startswith(Layout.SRC) for name in imported), sorted(imported)


def test_the_cache_lives_under_the_tool(loaded, tool):
    assert loaded.cache_dir == TOOLS / tool / Layout.CACHE


# ============================== the registry ==============================

def test_registry_parses_and_declares_sources(loaded):
    assert loaded.sources, "a registry with no sources checks nothing"
    assert loaded.tool


def test_every_source_says_where_it_is_read_and_what_it_costs(loaded):
    # The failure report is only useful if the registry carries this: a dead
    # source is a code change, and the person reading the report should not
    # have to go hunting for the call sites.
    for source in loaded.sources:
        assert source.consumed_by.strip(), source.id
        assert source.on_removal.strip(), source.id


def test_every_source_is_reachable_in_exactly_one_way(loaded):
    for source in loaded.sources:
        assert bool(source.url) != bool(source.probe_url), source.id
        # A fetched body is cached; a probed endpoint caches nothing of its
        # own, and declares its produced file as [[derived]] instead.
        assert bool(source.cache) == bool(source.url), source.id


def test_every_policy_is_one_the_janitor_implements(loaded):
    for entry in (*loaded.sources, *loaded.derived):
        assert entry.on_change in Policy.ALL, entry.id


def test_a_merging_cache_declares_a_record_age_limit(loaded):
    # Without it the file grows forever and keeps devices no dump has shown
    # in years, which is the opposite of what accumulating is for.
    for entry in loaded.derived:
        if entry.on_change == Policy.MERGE:
            assert entry.record_max_age_days > 0, entry.id


def test_an_expensive_cache_is_not_rebuilt_on_every_upstream_twitch(loaded):
    # A cache whose cost is measured in thousands of requests must not be
    # `delete`: the DMI repository takes commits daily, so that would mean a
    # full re-harvest every week.
    for entry in loaded.derived:
        if "5,700" in entry.cost or "5700" in entry.cost:
            assert entry.on_change == Policy.KEEP, entry.id


def test_every_derived_cache_names_a_source_it_depends_on(loaded):
    known = {s.id for s in loaded.sources}
    for entry in loaded.derived:
        assert entry.derives_from, entry.id
        assert set(entry.derives_from) <= known, entry.id


def test_every_cache_file_is_declared(loaded):
    """The completeness check: nothing in .cache may be unaccounted for.

    A file here that the registry does not name is either a leftover from a
    renamed key or -- the case this exists for -- a source added to the tool
    and never registered, which would then never be checked while every
    report claims the sources are healthy.
    """

    if not loaded.cache_dir.is_dir():
        pytest.skip("nothing downloaded yet")

    reserved = {"preflight.state.json", *loaded.scratch}
    on_disk = {
        p.name for p in loaded.cache_dir.iterdir()
        if p.name not in reserved and Policy.PREV not in p.name
    }

    assert on_disk <= loaded.declared_cache_files, sorted(
        on_disk - loaded.declared_cache_files)


def test_a_registry_rejects_an_unknown_key(tmp_path, monkeypatch):
    tool = tmp_path / "fake_tool" / Layout.SOURCES
    tool.mkdir(parents=True)
    (tool / Layout.REGISTRY_FILE).write_text(
        '[tool]\nname = "fake_tool"\n\n'
        '[[source]]\nid = "x"\nurl = "https://example.com/a"\n'
        'cache = "a"\nconsumed_by = "x"\non_removal = "x"\n'
        'typo_here = 1\n',
        encoding="utf-8")
    monkeypatch.setattr(Layout, "TOOLS_DIR", tmp_path)

    with pytest.raises(_registry.RegistryError, match="unknown key"):
        _registry.load("fake_tool")


# ============================ the declaration ============================

def test_the_declaration_digest_changes_with_the_declaration():
    # This is what makes a tightened contract take effect: a 304 carries no
    # body, so a stored verdict is only reusable while the declaration that
    # produced it is unchanged.
    loose = Source(id="a", url="u", cache="c", consumed_by="x", on_removal="x",
                   contract=Contract(kind="text", must_contain=("one",)))
    tight = Source(id="a", url="u", cache="c", consumed_by="x", on_removal="x",
                   contract=Contract(kind="text", must_contain=("one", "two")))
    repattern = Source(id="a", url="u", cache="c", consumed_by="x", on_removal="x",
                       contract=Contract(kind="text", must_contain=("one",)),
                       fingerprint=Fingerprint(kind="regex_count", pattern="x"))

    assert loose.digest and loose.digest != tight.digest
    assert loose.digest != repattern.digest
    assert Source(id="a", url="u", cache="c", consumed_by="x",
                  on_removal="x").digest == ""


# ============================== contracts ==============================

def test_a_reshaped_json_feed_fails_its_contract():
    contract = Contract(kind="json_list", min_items=2,
                        item_keys=("cycle", "releaseDate"))

    assert not ContractCheck.run(
        contract, b'[{"cycle":"a","releaseDate":"2026-01-01"},{"cycle":"b"}]')
    assert ContractCheck.run(contract, b'[{"cycle":"a"}]')          # renamed key
    assert ContractCheck.run(contract, b'{"cycle":"a"}')            # not a list
    assert ContractCheck.run(contract, b"<html>oops</html>")        # not JSON


def test_a_csv_contract_reads_the_declared_encoding():
    body = '"Model","Retail Branding"\n"X","Y"\n'.encode("utf-16")
    holds = Contract(kind="csv", encoding="utf-16",
                     must_have_columns=("Model", "Retail Branding"), min_rows=1)
    wrong = Contract(kind="csv", encoding="utf-8",
                     must_have_columns=("Model",), min_rows=1)

    assert not ContractCheck.run(holds, body)
    assert ContractCheck.run(wrong, body)


def test_a_renamed_method_breaks_the_text_contract():
    # The real case: Telegram-iOS refactoring platformString, which the tool
    # locates by string index and would otherwise crash on mid-build.
    contract = Contract(kind="text",
                        must_contain=("- (NSString *)platformString",),
                        must_match='return @"iPhone', min_matches=2)
    good = b'- (NSString *)platformString\nreturn @"iPhone 17";\nreturn @"iPhone Air";'

    assert not ContractCheck.run(contract, good)
    assert ContractCheck.run(contract, good.replace(b"platformString", b"platformName"))
    assert ContractCheck.run(contract, good.replace(b'return @"iPhone Air";', b""))


def test_a_git_advertisement_must_carry_refs():
    contract = Contract(kind="git_refs")

    assert not ContractCheck.run(
        contract, b"001e# service=git-upload-pack\n" + b"a" * 40 + b" HEAD\n")
    assert ContractCheck.run(contract, b"001e# service=git-upload-pack\n")


# ============================= fingerprints =============================

@pytest.mark.parametrize("kind,pattern,body,expected", [
    ("bytes_len", "", b"abcd", 4),
    ("json_len", "", b'[1,2,3]', 3),
    ("json_len", "", b'{"a":1,"b":2}', 2),
    ("regex_count", r'"type":\s*"iPhone"', b'["type": "iPhone", "type": "iPad"]', 1),
    ("regex_max_int", r'"version":\s*"(\d+)\.', b'"version": "99.1" "version": "156.0"', 156),
    ("git_head", "", b"0" * 39 + b"1 HEAD\n", "0" * 39 + "1"),
])
def test_a_fingerprint_reduces_a_body_to_its_watched_value(kind, pattern, body, expected):
    assert FingerprintValue.of(Fingerprint(kind=kind, pattern=pattern), body) == expected


def test_csv_rows_counts_data_rows_not_the_header():
    body = "a,b\n1,2\n3,4\n".encode("utf-16")
    assert FingerprintValue.of(
        Fingerprint(kind="csv_rows"), body, encoding="utf-16") == 2


def test_an_unusable_body_yields_no_fingerprint_rather_than_an_error():
    # A fingerprint is a comparison aid. A malformed body has already failed
    # its contract, which is the loud signal; this must not add a second.
    assert FingerprintValue.of(Fingerprint(kind="json_len"), b"not json") is None
    assert FingerprintValue.of(None, b"anything") is None


# ========================= classifying a failure =========================

@pytest.mark.parametrize("exc,expected", [
    (urllib.error.HTTPError("u", 404, "gone", {}, None), State.GONE),
    (urllib.error.HTTPError("u", 410, "gone", {}, None), State.GONE),
    (urllib.error.HTTPError("u", 429, "slow down", {}, None), State.FLAKY),
    (urllib.error.HTTPError("u", 403, "forbidden", {}, None), State.FLAKY),
    (urllib.error.HTTPError("u", 503, "down", {}, None), State.FLAKY),
    (urllib.error.HTTPError("u", 304, "same", {}, None), State.OK),
    (urllib.error.URLError(socket.timeout("timed out")), State.FLAKY),
    (urllib.error.URLError(socket.gaierror("no dns")), State.FLAKY),
    (TimeoutError("timed out"), State.FLAKY),
])
def test_a_dead_source_is_told_apart_from_an_unreachable_one(exc, expected):
    # The distinction the whole gate rests on. A 404 means a developer has to
    # remove the source from the tool; a timeout means the network blinked,
    # and reporting the second as the first hands somebody a request for
    # surgery on working code.
    state, _status, _message = Prober.classify(exc)
    assert state == expected


def test_a_429_is_expected_rather_than_alarming():
    # The DMI harvest makes thousands of raw.githubusercontent requests and
    # gets throttled for it, which must never read as a dead source.
    state, status, _ = Prober.classify(
        urllib.error.HTTPError("u", 429, "slow down", {}, None))

    assert state == State.FLAKY and status == 429


def test_a_mostly_unreachable_run_blames_the_network_not_the_sources():
    flaky = [Verdict(source_id=f"s{i}", state=State.FLAKY) for i in range(6)]
    fine = [Verdict(source_id=f"o{i}", state=State.OK) for i in range(2)]

    assert Health.assess(flaky + fine) == Health.DEGRADED
    assert Health.assess(fine + flaky[:1]) == Health.OK
    assert Health.assess([]) == Health.OK


# =============================== the gate ===============================

def _report(*states: str, network: str = Health.OK, first: bool = False) -> Report:
    return Report(
        tool="t",
        verdicts=tuple(Verdict(source_id=f"s{i}", state=s)
                       for i, s in enumerate(states)),
        network=network,
        first_run=first,
    )


def test_a_dead_source_always_stops_the_run():
    assert not _report(State.OK, State.GONE).may_proceed()
    assert not _report(State.OK, State.GONE).may_proceed(allow_flaky=True)
    assert not _report(State.CONTRACT_BROKEN).may_proceed(allow_flaky=True)


def test_an_unreachable_source_stops_the_run_but_can_be_waived():
    report = _report(State.OK, State.FLAKY)

    assert not report.may_proceed()
    assert report.may_proceed(allow_flaky=True)


def test_a_change_is_not_a_failure():
    assert _report(State.OK, State.CHANGED, State.NEW).may_proceed()


def test_the_report_puts_what_needs_action_first():
    report = _report(State.OK, State.CHANGED, State.GONE, State.CONTRACT_BROKEN)
    order = [v.state for v in report.sorted_verdicts()]

    assert order[0] == State.CONTRACT_BROKEN
    assert order[-1] == State.OK


# =============================== the lock ===============================

def _registry_for(tmp_path: Path, *sources: Source, **kw) -> Registry:
    return Registry(tool="t", tool_dir=tmp_path, cache_dir=tmp_path / ".cache",
                    sources=tuple(sources), **kw)


def test_a_first_run_reports_new_and_never_changed(tmp_path):
    # Eighteen false alarms on day one teach a maintainer to ignore the
    # dashboard, and it never recovers from that.
    lock = Lock(tmp_path / "sources.lock.json")

    assert lock.is_new
    assert lock.fingerprint("anything") is None


def test_the_lock_is_written_only_when_its_content_differs(tmp_path):
    # The one guarantee the tracked file offers: a diff means something moved.
    path = tmp_path / "sources.lock.json"
    lock = Lock(path)
    source = Source(id="s", url="u", cache="c", consumed_by="x", on_removal="x",
                    fingerprint=Fingerprint(kind="bytes_len"))
    registry = _registry_for(tmp_path, source)
    verdict = Verdict(source_id="s", state=State.NEW, now=10, body=b"0123456789",
                      sha256="abc", bytes_len=10)

    assert lock.save(lock.rebuild(registry, [verdict], today="2026-01-01"))
    assert not lock.save(lock.rebuild(registry, [verdict], today="2026-01-01"))


def test_an_ok_run_carries_the_entry_forward_untouched(tmp_path):
    # Some feeds answer with a different body every time -- Google's version
    # history carries a fresh nextPageToken -- while the value we watch is
    # unchanged. Rewriting the hash there would churn the file every run.
    path = tmp_path / "sources.lock.json"
    lock = Lock(path)
    source = Source(id="s", url="u", cache="c", consumed_by="x", on_removal="x",
                    fingerprint=Fingerprint(kind="bytes_len"))
    registry = _registry_for(tmp_path, source)

    lock.save(lock.rebuild(registry, [Verdict(
        source_id="s", state=State.NEW, now=10, body=b"0" * 10,
        declaration=source.digest)], today="2026-01-01"))
    before = path.read_text(encoding="utf-8")

    lock.save(lock.rebuild(registry, [Verdict(
        source_id="s", state=State.OK, was=10, now=10, body=b"9" * 10,
        sha256="different", declaration=source.digest)], today="2026-02-02"))

    assert path.read_text(encoding="utf-8") == before


def test_a_failure_counter_appears_only_while_failing(tmp_path):
    path = tmp_path / "sources.lock.json"
    lock = Lock(path)
    source = Source(id="s", url="u", cache="c", consumed_by="x", on_removal="x")
    registry = _registry_for(tmp_path, source)

    lock.save(lock.rebuild(registry, [Verdict(
        source_id="s", state=State.NEW, body=b"x")], today="2026-01-01"))
    assert Lock.FAILING not in path.read_text(encoding="utf-8")

    lock.save(lock.rebuild(registry, [Verdict(
        source_id="s", state=State.GONE, error="HTTP 404", consecutive=2)],
        today="2026-01-08"))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["sources"]["s"][Lock.FAILING]["consecutive"] == 2

    lock.save(lock.rebuild(registry, [Verdict(
        source_id="s", state=State.OK, body=None)], today="2026-01-15"))
    assert Lock.FAILING not in path.read_text(encoding="utf-8")


def test_an_unreachable_source_keeps_the_fingerprint_it_had(tmp_path):
    # Otherwise a timeout erases what the next run compares against, and
    # everything comes back as `new`.
    path = tmp_path / "sources.lock.json"
    lock = Lock(path)
    source = Source(id="s", url="u", cache="c", consumed_by="x", on_removal="x",
                    fingerprint=Fingerprint(kind="bytes_len"))
    registry = _registry_for(tmp_path, source)

    lock.save(lock.rebuild(registry, [Verdict(
        source_id="s", state=State.NEW, now=42, body=b"x")], today="2026-01-01"))
    lock.save(lock.rebuild(registry, [Verdict(
        source_id="s", state=State.FLAKY, error="timeout", consecutive=1)],
        today="2026-01-08"))

    assert Lock(path).fingerprint("s") == 42


# ============================== the janitor ==============================

def _changed(source_id: str) -> Verdict:
    return Verdict(source_id=source_id, state=State.CHANGED, was=1, now=2)


def test_a_changed_source_loses_its_cached_body(tmp_path):
    cache = tmp_path / ".cache"
    cache.mkdir()
    (cache / "body.json").write_text("{}", encoding="utf-8")
    source = Source(id="s", url="u", cache="body.json", consumed_by="x",
                    on_removal="x", on_change=Policy.DELETE)

    actions = Janitor(_registry_for(tmp_path, source)).run(
        _report_with(_changed("s")))

    assert any(a.kind == Action.DELETED for a in actions)
    assert not (cache / "body.json").exists()


def test_a_merging_cache_is_renamed_aside_not_deleted(tmp_path):
    # The janitor never reads or rewrites a tool's file, so it cannot merge.
    # It sets the old one aside under a name the tool looks for, and the tool
    # -- which knows the record identity -- does the merging.
    cache = tmp_path / ".cache"
    cache.mkdir()
    (cache / "records.json").write_text("[]", encoding="utf-8")
    source = Source(id="s", probe_url="u", consumed_by="x", on_removal="x")
    derived = Derived(id="d", cache="records.json", derives_from=("s",),
                      on_change=Policy.MERGE, record_max_age_days=730)

    actions = Janitor(_registry_for(tmp_path, source, derived=(derived,))).run(
        _report_with(_changed("s")))

    assert any(a.kind == Action.RENAMED for a in actions)
    assert (cache / f"records{Policy.PREV}.json").exists()
    assert not (cache / "records.json").exists()


def test_an_expensive_cache_survives_an_upstream_change(tmp_path):
    cache = tmp_path / ".cache"
    cache.mkdir()
    (cache / "dmi.json").write_text("[]", encoding="utf-8")
    source = Source(id="s", probe_url="u", consumed_by="x", on_removal="x")
    derived = Derived(id="d", cache="dmi.json", derives_from=("s",),
                      on_change=Policy.KEEP, max_age_days=365)

    actions = Janitor(_registry_for(tmp_path, source, derived=(derived,))).run(
        _report_with(_changed("s")))

    assert any(a.kind == Action.KEPT for a in actions)
    assert (cache / "dmi.json").exists()


def test_a_derived_cache_goes_stale_by_dependency(tmp_path):
    cache = tmp_path / ".cache"
    cache.mkdir()
    (cache / "built.json").write_text("{}", encoding="utf-8")
    source = Source(id="upstream", probe_url="u", consumed_by="x", on_removal="x")
    derived = Derived(id="d", cache="built.json", derives_from=("upstream",),
                      on_change=Policy.DELETE)
    registry = _registry_for(tmp_path, source, derived=(derived,))

    assert not any(a.kind == Action.DELETED for a in
                   Janitor(registry).run(_report_with(
                       Verdict(source_id="upstream", state=State.OK))))
    assert (cache / "built.json").exists()

    Janitor(registry).run(_report_with(_changed("upstream")))
    assert not (cache / "built.json").exists()


def test_scratch_never_survives_a_run(tmp_path):
    cache = tmp_path / ".cache"
    (cache / "dmi-repo" / "objects").mkdir(parents=True)
    source = Source(id="s", probe_url="u", consumed_by="x", on_removal="x")
    registry = _registry_for(tmp_path, source, scratch=("dmi-repo",))

    actions = Janitor(registry).run(_report_with(
        Verdict(source_id="s", state=State.OK)))

    assert any(a.kind == Action.SCRATCH for a in actions)
    assert not (cache / "dmi-repo").exists()


def test_an_undeclared_cache_file_is_reported_and_never_deleted(tmp_path):
    # Guessing that an unknown file is rubbish is how a 20 MB cache vanishes.
    cache = tmp_path / ".cache"
    cache.mkdir()
    (cache / "mystery.json").write_text("{}", encoding="utf-8")
    source = Source(id="s", probe_url="u", consumed_by="x", on_removal="x")

    actions = Janitor(_registry_for(tmp_path, source)).run(_report_with(
        Verdict(source_id="s", state=State.OK)))

    assert any(a.kind == Action.ORPHAN for a in actions)
    assert (cache / "mystery.json").exists()


def test_a_dry_run_changes_nothing(tmp_path):
    cache = tmp_path / ".cache"
    cache.mkdir()
    (cache / "body.json").write_text("{}", encoding="utf-8")
    source = Source(id="s", url="u", cache="body.json", consumed_by="x",
                    on_removal="x")

    Janitor(_registry_for(tmp_path, source), dry_run=True).run(
        _report_with(_changed("s")))

    assert (cache / "body.json").exists()


def _report_with(*verdicts: Verdict) -> Report:
    return Report(tool="t", verdicts=tuple(verdicts), network=Health.OK,
                  first_run=False)


# ======================== conditional request trust ========================

class _FakeProber(Prober):
    """Records what validators each probe was given."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[tuple[str, str]] = []

    def probe(self, source, *, etag="", last_modified=""):           # noqa: ANN001
        self.seen.append((etag, last_modified))
        return Verdict(source_id=source.id, state=State.OK, body=b"body",
                       sha256="hash", bytes_len=4)


@pytest.mark.parametrize("stored,expect_conditional", [
    ({"declaration": "MATCH", "contract": "ok",
      "http": {"etag": "E", "last_modified": "L"}}, True),
    ({"declaration": "STALE", "contract": "ok",
      "http": {"etag": "E", "last_modified": "L"}}, False),
    ({"declaration": "MATCH", "contract": "broken",
      "http": {"etag": "E", "last_modified": "L"}}, False),
])
def test_a_conditional_request_needs_a_trustworthy_previous_verdict(
        tmp_path, stored, expect_conditional):
    """A 304 carries no body, so it reuses the stored verdict.

    That is only honest while the declaration is the one that verdict was
    reached under *and* that verdict was a pass. Otherwise a tightened
    contract would never take effect, and a recorded failure would vanish on
    the very next run -- which it did, until this was fixed.
    """

    source = Source(id="s", url="u", cache="c", consumed_by="x", on_removal="x",
                    contract=Contract(kind="text", must_contain=("x",)))
    path = tmp_path / "sources.lock.json"
    path.write_text(json.dumps({
        "lock_schema": 1,
        "sources": {"s": {**stored, "declaration":
                          source.digest if stored["declaration"] == "MATCH"
                          else "0000"}},
    }), encoding="utf-8")

    prober = _FakeProber()
    Checker(_registry_for(tmp_path, source), Lock(path),
            prober=prober).check_one(source)

    assert (prober.seen[0] != ("", "")) is expect_conditional


# ====================== the soundness of a 304 ======================
#
# A 304 carries no body, so the contract cannot be re-evaluated and the
# stored verdict is reused instead. That is only sound against a validator
# which promises the *bytes* are unchanged. A weak ETag promises semantic
# equivalence (RFC 9110 8.8.3) and `Last-Modified` is weak by definition at
# one-second granularity, so either one lets an origin answer 304 for a body
# that is not the one the contract was checked against -- and the contract is
# then evaluated once, on the very first run, and never again.
#
# Measured against the eighteen real sources: thirteen revalidate
# conditionally, two advertise a weak ETag (appledb, the dumps API) and one
# sends only Last-Modified, so three were silently exempt from the one check
# that catches a reshaped feed.

@pytest.mark.parametrize("stored, expect", [
    ({"etag": '"strong"'}, ('"strong"', "")),
    ({"etag": 'W/"weak"'}, ("", "")),
    ({"last_modified": "Wed, 01 Jan 2025 00:00:00 GMT"}, ("", "")),
    ({"etag": 'W/"weak"', "last_modified": "L"}, ("", "")),
    ({"etag": '"strong"', "last_modified": "L"}, ('"strong"', "")),
    ({}, ("", "")),
])
def test_only_a_strong_etag_may_shorten_a_check(tmp_path, stored, expect):
    path = tmp_path / "sources.lock.json"
    path.write_text(json.dumps({
        "lock_schema": 1,
        "sources": {"s": {"contract": "ok", "http": stored}},
    }), encoding="utf-8")

    assert Lock(path).validators("s") == expect


def test_last_modified_is_still_recorded_as_a_fact(tmp_path):
    """Withheld from a request, but not from the lock.

    It is a genuine upstream fact and reads well in a diff; it simply must
    not be the thing a 304 is earned with.
    """

    source = Source(id="s", url="u", cache="c", consumed_by="x", on_removal="x")
    lock = Lock(tmp_path / "sources.lock.json")
    rebuilt = lock.rebuild(_registry_for(tmp_path, source), [Verdict(
        source_id="s", state=State.NEW, body=b"x", sha256="a", bytes_len=1,
        etag='W/"weak"', last_modified="L")])

    assert rebuilt["sources"]["s"]["http"] == {
        "etag": 'W/"weak"', "last_modified": "L"}
    lock.save(rebuilt)
    assert lock.validators("s") == ("", "")


# ===================== a contract reports, never raises =====================

@pytest.mark.parametrize("contract, body, expect", [
    # a malformed CSV used to raise csv.Error out of the check and end the
    # run in a traceback: nothing reported, nothing cleaned, no exit code.
    # the oversized body is built in the test rather than passed here: a
    # 200 KB parametrize id overflows the environment variable pytest
    # reports the current test through.
    (Contract(kind="csv", min_rows=1), "oversized_csv_field", "could not be read"),
    # a kind the parser would have rejected, reaching the checker anyway.
    (Contract(kind="xml"), b"<a/>", "unknown contract kind"),
])
def test_a_body_that_cannot_be_judged_is_a_stated_failure(contract, body, expect):
    if body == "oversized_csv_field":
        body = b'a,b\n"' + b"x" * 200_000
    errors = ContractCheck.run(contract, body)
    assert errors and expect in errors[0]


def test_every_contract_kind_the_model_declares_is_implemented():
    """One list, two places. They must not drift.

    `Contract.KINDS` is what the registry validates against and
    `ContractCheck.KINDS` is what it dispatches on, so a kind added to one
    and not the other would either be rejected on sight or arrive at the
    dispatcher as an unknown.
    """

    assert set(ContractCheck.KINDS) == set(Contract.KINDS)


@pytest.mark.parametrize("block", [
    'contract = { kind = "text", must_match = "[" }',
    'fingerprint = { kind = "regex_count", pattern = "(" }',
])
def test_a_pattern_that_will_not_compile_is_a_malformed_registry(tmp_path, block):
    """Caught at parse time, so it is exit code 4 rather than a traceback out
    of the middle of a check that has already touched the network."""

    (tmp_path / "demo" / "sources").mkdir(parents=True)
    (tmp_path / "demo" / "sources" / "sources.toml").write_text(
        '[tool]\nname = "demo"\n\n[[source]]\nid = "s"\n'
        'url = "http://x/y"\ncache = "c.json"\n'
        'consumed_by = "x"\non_removal = "x"\n' + block,
        encoding="utf-8")

    was, Layout.TOOLS_DIR = Layout.TOOLS_DIR, tmp_path
    try:
        with pytest.raises(_registry.RegistryError, match="not a valid regex"):
            _registry.load("demo")
    finally:
        Layout.TOOLS_DIR = was


# ========================= a run can be stopped =========================

@pytest.mark.parametrize("raised", [KeyboardInterrupt, SystemExit])
def test_an_interrupt_is_not_classified_as_a_flaky_source(raised):
    """Catching BaseException around a request is right -- one bad socket must
    not end a run of eighteen sources. Swallowing Ctrl-C was not: it became
    `flaky`, was retried twice with a sleep between, and the run carried on to
    the next source, so stopping it took fifty-four keypresses."""

    class Interrupting(Prober):
        BACKOFF = 0.0

        def request(self, url, *, etag="", last_modified=""):
            raise raised

    with pytest.raises(raised):
        Interrupting().probe(
            Source(id="s", url="u", cache="c", consumed_by="x", on_removal="x"))


def test_a_real_failure_is_still_classified_and_retried():
    class Broken(Prober):
        BACKOFF = 0.0

        def request(self, url, *, etag="", last_modified=""):
            raise OSError("socket died")

    verdict = Broken().probe(
        Source(id="s", url="u", cache="c", consumed_by="x", on_removal="x"))
    assert verdict.state == State.FLAKY
    assert verdict.attempts == Prober.ATTEMPTS


# ======================== what the caller learns ========================

@pytest.mark.parametrize("codes, worst", [
    ([_cli.Exit.UNREACHABLE, _cli.Exit.DEAD], _cli.Exit.DEAD),
    ([_cli.Exit.CHANGED, _cli.Exit.DEAD], _cli.Exit.DEAD),
    ([_cli.Exit.DEAD, _cli.Exit.CHANGED], _cli.Exit.DEAD),
    ([_cli.Exit.CHANGED, _cli.Exit.UNREACHABLE], _cli.Exit.UNREACHABLE),
    ([_cli.Exit.DEAD, _cli.Exit.REGISTRY], _cli.Exit.REGISTRY),
    ([_cli.Exit.OK, _cli.Exit.CHANGED, _cli.Exit.OK], _cli.Exit.CHANGED),
    ([_cli.Exit.OK, _cli.Exit.OK], _cli.Exit.OK),
])
def test_all_reports_the_worst_outcome_not_the_first(codes, worst):
    """Taking the first non-zero code answered "unreachable" for a run in
    which another tool's source was dead, so the caller would retry instead
    of fetching a developer."""

    folded = _cli.Exit.OK
    for code in codes:
        folded = _cli.Exit.worse(folded, code)
    assert folded == worst


def test_every_exit_code_is_ranked():
    assert set(_cli.Exit.WORST) == {
        _cli.Exit.OK, _cli.Exit.CHANGED, _cli.Exit.DEAD,
        _cli.Exit.UNREACHABLE, _cli.Exit.REGISTRY}


@pytest.mark.parametrize("code, expect", [
    (None, _cli.Exit.OK), (0, 0), (3, 3), (True, 1), (False, 0),
    # a tool is entitled to `raise SystemExit("the cache is missing")`, and
    # python prints that and exits 1. int() raised a ValueError instead, so
    # the tool's own explanation became a traceback from the launcher.
    ("the cache is missing", _cli.Exit.DEAD),
])
def test_a_tool_may_exit_with_a_message(capsys, code, expect):
    assert _cli.Dispatcher._exit_code(code) == expect


# ===================== a source believed to be dead =====================

def test_a_source_is_only_called_dead_after_enough_consecutive_runs():
    """One failure is weather. The counter lives in the tracked lock so it
    survives a fresh CI runner, and the report is where it is acted on."""

    def report(consecutive):
        return Report(tool="t", network="ok", first_run=False, verdicts=(
            Verdict(source_id="s", state=State.GONE, consecutive=consecutive),))

    assert report(Report.ESCALATE_AFTER - 1).escalated == ()
    assert len(report(Report.ESCALATE_AFTER).escalated) == 1
    assert len(report(Report.ESCALATE_AFTER + 5).escalated) == 1


# ================== break, then recover, then change ==================

def _lifecycle_lock(tmp_path, source):
    return Lock(tmp_path / "sources.lock.json"), _registry_for(tmp_path, source)


def _verdict(source, state, now=None, errors=()):
    return Verdict(source_id=source.id, state=state, now=now,
                   body=None if state in (State.GONE,) else b"body",
                   sha256="s", bytes_len=4, declaration=source.digest,
                   contract_errors=tuple(errors))


def test_a_failure_does_not_erase_the_fingerprint_it_failed_to_produce(tmp_path):
    """Break a source, then let it recover.

    Recording the failure used to write a hash where the fingerprint was,
    because a contract failure never gets as far as computing one. The next
    good run then compared a real value against nothing, called it `changed`,
    and had the janitor delete a cache for a change that never happened.
    """

    source = Source(id="s", url="u", cache="c.json",
                    consumed_by="x", on_removal="x",
                    contract=Contract(kind="json_list", item_keys=("name",)),
                    fingerprint=Fingerprint(kind="json_len"))
    lock, registry = _lifecycle_lock(tmp_path, source)

    lock.save(lock.rebuild(registry, [_verdict(source, State.NEW, now=3)]))
    assert lock.entry("s")["fingerprint"] == 3

    # upstream reshapes: the contract breaks and no fingerprint is produced.
    lock.save(lock.rebuild(registry, [
        _verdict(source, State.CONTRACT_BROKEN, errors=("no item carries 'name'",))]))
    assert lock.entry("s")["contract"] == "broken"
    assert lock.entry("s")["fingerprint"] == 3, "the baseline must survive"
    assert "sha256" not in lock.entry("s")

    # upstream recovers with the same content: `ok`, not `changed`.
    assert Checker(registry, lock)._moved(
        lock.fingerprint("s"), 3, "a", lock.sha256("s")) is False


def test_a_recovered_source_stops_being_called_reshaped(tmp_path):
    """Otherwise the lock keeps claiming the source is broken, and holds it
    off the conditional path forever on the strength of a failure that is
    over."""

    source = Source(id="s", url="u", cache="c.json",
                    consumed_by="x", on_removal="x",
                    contract=Contract(kind="json_list", item_keys=("name",)),
                    fingerprint=Fingerprint(kind="json_len"))
    lock, registry = _lifecycle_lock(tmp_path, source)

    lock.save(lock.rebuild(registry, [_verdict(source, State.NEW, now=3)]))
    lock.save(lock.rebuild(registry, [_verdict(source, State.CONTRACT_BROKEN)]))
    assert lock.entry("s")["contract"] == "broken"

    # a clear verdict that actually ran its contract clears the flag, and
    # carries the facts forward rather than rewriting them.
    wrote = lock.save(lock.rebuild(registry, [_verdict(source, State.OK, now=3)]))
    assert wrote, "broken -> ok is a diff line worth reading"
    assert lock.entry("s")["contract"] == "ok"
    assert lock.entry("s")["fingerprint"] == 3

    # and then it is steady: an `ok` run that learned nothing writes nothing.
    assert lock.save(lock.rebuild(registry, [_verdict(source, State.OK, now=3)])) is False


def test_an_unreachable_source_records_no_verdict_at_all(tmp_path):
    """`flaky` never got a body, so it has nothing to say about the shape.
    Writing `contract: broken` for a timeout would accuse a working source."""

    source = Source(id="s", url="u", cache="c.json",
                    consumed_by="x", on_removal="x",
                    contract=Contract(kind="json_list"),
                    fingerprint=Fingerprint(kind="json_len"))
    lock, registry = _lifecycle_lock(tmp_path, source)

    lock.save(lock.rebuild(registry, [_verdict(source, State.NEW, now=3)]))
    rebuilt = lock.rebuild(registry, [Verdict(
        source_id="s", state=State.FLAKY, error="timeout",
        consecutive=1, declaration=source.digest)])

    assert rebuilt["sources"]["s"]["contract"] == "ok"
    assert rebuilt["sources"]["s"]["fingerprint"] == 3
    assert rebuilt["sources"]["s"][Lock.FAILING]["state"] == State.FLAKY


# ============================== the cadence ==============================
#
# A checker nobody runs reports nothing, so the schedule is what makes the
# rest of this worth anything. It also carries the one duplication this
# design could not avoid: GitHub Actions cannot compute a trigger, so the
# cron sits in the workflow as well as in the tool's own declaration, and
# these tests are what keep the two from drifting apart.

WORKFLOW = TOOLS.parent / ".github" / "workflows" / "tools-preflight.yml"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _triggers() -> list[str]:
    """The crons the workflow really fires on.

    Read with a regex rather than a YAML parser: one string is not a reason
    for this suite to take on a dependency the package itself does not have.
    """

    return re.findall(r'^\s*-\s*cron:\s*"([^"]+)"', _workflow(), re.M)


def test_every_tool_declares_how_often_it_is_checked():
    # A tool with sources and no schedule is checked only when somebody
    # remembers to, which is the state this whole package exists to replace.
    for tool in Layout.tools():
        assert _schedule.load(tool).every_days > 0


def test_every_declared_cadence_is_a_trigger_the_workflow_really_has():
    triggers = _triggers()

    assert triggers, "the workflow declares no schedule at all"
    for tool in Layout.tools():
        assert _schedule.load(tool).cron in triggers


def test_the_workflow_fires_on_nothing_a_tool_did_not_ask_for():
    # The other direction, and the one that rots quietly: a cron left behind
    # after a tool's cadence changed would keep waking the job on a schedule
    # nothing in the repository claims.
    declared = {_schedule.load(tool).cron for tool in Layout.tools()}

    assert set(_triggers()) <= declared


def test_the_scheduled_run_checks_sources_and_never_builds():
    # Rebuilding a catalog rewrites a file that ships in the wheel. That is a
    # decision with a human behind it, so the unattended job reports and
    # records, and runs no generator.
    text = _workflow()

    assert "-m tools._preflight" in text
    assert not re.search(r"-m tools\.(?!_preflight)", text)
    assert "-m tools " not in text


def test_the_scheduled_run_keeps_the_counter_it_depends_on():
    # The consecutive-failure counter lives in the tracked lock precisely
    # because a runner is new every week. If the workflow does not push the
    # lock back, no counter ever reaches ESCALATE_AFTER and no source is ever
    # called dead -- the rule would be arithmetic nothing performs.
    text = _workflow()

    assert "contents: write" in text
    assert Layout.LOCK_FILE in text
    assert "git commit" in text and "git push" in text
    # And it has to happen even on the run that failed, which is the run
    # whose counter matters most.
    assert "if: always()" in text


# --- reading a cadence -----------------------------------------------------

@pytest.mark.parametrize("cron, days", [
    ("19 4 * * 1", _model.Schedule.WEEKLY),
    ("0 5 * * 0", _model.Schedule.WEEKLY),
    ("0 5 * * *", _model.Schedule.DAILY),
    ("0 5 1 * *", _model.Schedule.MONTHLY),
])
def test_a_cadence_is_read_out_of_the_cron_not_declared_beside_it(cron, days):
    # Derived, so there is no second number to drift. The reader is the
    # escalation line: three runs is three weeks here and three days at a
    # daily cadence, and only one of those is worth waiting for.
    assert _model.Schedule(tool="t", cron=cron).every_days == days


@pytest.mark.parametrize("cron", [
    "0 5 * * */3",                                # every third weekday
    "0 5 * * 1,4",                                # twice a week
    "0 5 1 1 *",                                  # once a year
    "0 5 * *",                                    # four fields
    "nonsense",
])
def test_a_cron_that_is_not_a_cadence_is_refused_rather_than_rounded(cron):
    assert _model.Schedule(tool="t", cron=cron).every_days == 0


def test_a_schedule_that_cannot_be_stated_in_days_is_malformed(
        tmp_path, monkeypatch):
    folder = tmp_path / "fake_tool" / Layout.SCHEDULE
    folder.mkdir(parents=True)
    (folder / Layout.SCHEDULE_FILE).write_text(
        '[schedule]\ncron = "0 5 * * 1,4"\n', encoding="utf-8")
    monkeypatch.setattr(Layout, "TOOLS_DIR", tmp_path)

    with pytest.raises(_registry.RegistryError, match="stated in days"):
        _schedule.load("fake_tool")


def test_a_schedule_rejects_an_unknown_key(tmp_path, monkeypatch):
    # Same rule as the registry, for the same reason: a typo that dropped the
    # cron would leave a tool looking scheduled and never checked.
    folder = tmp_path / "fake_tool" / Layout.SCHEDULE
    folder.mkdir(parents=True)
    (folder / Layout.SCHEDULE_FILE).write_text(
        '[schedule]\ncron = "19 4 * * 1"\nevery_days = 7\n', encoding="utf-8")
    monkeypatch.setattr(Layout, "TOOLS_DIR", tmp_path)

    with pytest.raises(_registry.RegistryError, match="unknown key"):
        _schedule.load("fake_tool")


def test_a_tool_with_no_schedule_is_still_checkable_by_hand(
        tmp_path, monkeypatch):
    # Finding a cadence is soft; needing one is the workflow's business.
    monkeypatch.setattr(Layout, "TOOLS_DIR", tmp_path)

    assert _schedule.find("nobody") is None


# --- what a scheduled run reports -----------------------------------------

def _failing(consecutive: int, state: str = State.FLAKY) -> Report:
    return Report(tool="t", network=Health.OK, first_run=False, verdicts=(
        Verdict(source_id="s", state=state, consecutive=consecutive),))


def test_an_escalated_source_is_dead_however_flaky_a_run_may_be():
    # The waiver covers a dropped connection, not three weeks of one. Until
    # this, --allow-flaky hid an escalation completely: the exit code said the
    # sources were fine while the report said one had failed every run for a
    # month, and the scheduled job would have passed every week for ever.
    report = _failing(Report.ESCALATE_AFTER)

    assert _cli.Preflight.code(report, allow_flaky=True) == _cli.Exit.DEAD
    assert _cli.Preflight.code(report) == _cli.Exit.DEAD


def test_one_unreachable_run_is_passable_when_the_caller_says_so():
    report = _failing(1)

    assert _cli.Preflight.code(report) == _cli.Exit.UNREACHABLE
    assert _cli.Preflight.code(report, allow_flaky=True) == _cli.Exit.OK


def test_waiving_flakiness_does_not_hide_a_change():
    report = Report(tool="t", network=Health.OK, first_run=False, verdicts=(
        Verdict(source_id="a", state=State.FLAKY, consecutive=1),
        Verdict(source_id="b", state=State.CHANGED, was=1, now=2)))

    assert _cli.Preflight.code(report, allow_flaky=True) == _cli.Exit.CHANGED


def test_the_escalation_line_says_how_long_that_actually_is(tmp_path):
    # Nobody thinks in runs. The count is what the rule can measure; the
    # cadence is what turns it into a sentence somebody can act on.
    registry = _registry_for(tmp_path)
    report = _failing(Report.ESCALATE_AFTER)
    weekly = _model.Schedule(tool="t", cron="19 4 * * 1")

    plain = TextReport.render(report, registry)
    dated = TextReport.render(report, registry, schedule=weekly)

    assert f"{Report.ESCALATE_AFTER}+ runs" in plain
    assert "days" not in plain
    assert f"about {Report.ESCALATE_AFTER * weekly.every_days} days" in dated


# ============================= ported rules =============================
#
# A citation is the one kind of upstream this tool reads once and then
# reimplements. Nothing in a build fails when such a rule moves -- the port
# keeps producing strings the client no longer produces -- so these tests
# cover both halves of the promise: that the quoted lines are still upstream
# (the check does that weekly), and that the code the citation points at is
# still there (that cannot be checked from upstream at all).


def _tool_classes(tool: str) -> dict[str, set[str]]:
    """Every class under the tool's src/, with its attributes and methods.

    Parsed, never imported: `tools/` ships in no wheel and a src module
    imports its siblings, so reading the text is both lighter and the only
    thing guaranteed to work from a bare checkout.
    """

    found: dict[str, set[str]] = {}
    for path in sorted((Layout.TOOLS_DIR / tool / Layout.SRC).glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            names: set[str] = set()
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(item.name)
                elif isinstance(item, ast.AnnAssign) and isinstance(
                        item.target, ast.Name):
                    names.add(item.target.id)
                elif isinstance(item, ast.Assign):
                    names.update(t.id for t in item.targets
                                 if isinstance(t, ast.Name))
            found.setdefault(node.name, set()).update(names)
    return found


def _ported_tools() -> list[str]:
    return [t for t in Layout.tools() if _registry.load(t).citations]


def test_at_least_one_rule_is_declared_as_ported():
    # Not a tautology: this tool reimplements lib_base, Chromium and Gecko,
    # and if that ever stopped being declared the rest of these tests would
    # pass by having nothing to check.
    assert _ported_tools()


def test_every_ported_rule_points_at_a_module_that_exists():
    for tool in _ported_tools():
        src = Layout.TOOLS_DIR / tool / Layout.SRC
        for citation in _registry.load(tool).citations:
            named = re.findall(r"src/(\w+)\.py", citation.ported_to)
            assert named, f"{citation.id}: ported_to names no src module"
            for module in named:
                assert (src / f"{module}.py").is_file(), \
                    f"{citation.id}: src/{module}.py does not exist"


#: What `ported_to` is written in: `Owner.first, SECOND, third()`, one clause
#: per `;`. A bare name counts as a reference only when it is unmistakably
#: one -- SHOUTED or called -- so the prose around it is not read as a symbol.
QUALIFIED = re.compile(r"\b([A-Z]\w+)\.(\w+)")
REFERENCE = re.compile(r"\b[A-Z]\w+\.\w+|\b\w+\(\)|\b[A-Z][A-Z0-9_]{2,}\b")


def _references(ported_to: str) -> list[tuple[str, str]]:
    """Every (owner, attribute) a ported_to names."""

    found: list[tuple[str, str]] = []
    # Clauses are separated by `;` and nothing else. The prose is wrapped for
    # width inside a TOML multi-line string, so a newline carries no meaning,
    # and resetting the owner on one dropped half of every list.
    for clause in ported_to.split(";"):
        owner = ""
        for token in REFERENCE.finditer(clause):
            text = token.group(0)
            if QUALIFIED.fullmatch(text):
                owner, attr = text.split(".", 1)
                found.append((owner, attr))
            elif owner:
                found.append((owner, text.rstrip("()")))
    return found


def test_every_ported_rule_points_at_code_that_still_exists():
    # The half no upstream check can cover. A constant renamed on this side
    # leaves the citation quoting a rule nothing implements any more, and the
    # weekly check would go on reporting it healthy for ever.
    #
    # It earned its place immediately: it caught WebBuilder.GECKO_TEMPLATE
    # and Platform.navigator, two names written into the citations from
    # memory that the code had never had.
    checked = 0
    for tool in _ported_tools():
        classes = _tool_classes(tool)
        for citation in _registry.load(tool).citations:
            named = _references(citation.ported_to)
            assert named, f"{citation.id}: ported_to names no symbol at all"
            for owner, attr in named:
                if owner not in classes:          # prose, not a reference
                    continue
                checked += 1
                assert attr in classes[owner], \
                    f"{citation.id}: {owner}.{attr} is gone"

    # A guard that resolved nothing would pass just as quietly.
    assert checked >= 20, checked


def test_a_citation_declares_every_part_of_its_promise(tmp_path, monkeypatch):
    # A citation with nothing to look for would pass every week while the
    # rule it quotes was rewritten underneath it.
    folder = tmp_path / "fake_tool"
    (folder / Layout.SOURCES).mkdir(parents=True)
    (folder / Layout.SOURCES / Layout.REGISTRY_FILE).write_text(
        '[tool]\nname = "fake_tool"\n', encoding="utf-8")
    (folder / Layout.PORTED).mkdir()
    (folder / Layout.PORTED / Layout.CITATIONS_FILE).write_text(
        '[[citation]]\nid = "x"\nurl = "https://example.com/a.cpp"\n'
        'ported_to = "src/x.py :: X"\non_drift = "everything"\n',
        encoding="utf-8")
    monkeypatch.setattr(Layout, "TOOLS_DIR", tmp_path)

    with pytest.raises(_registry.RegistryError, match="anchors is required"):
        _registry.load("fake_tool")


def test_one_body_cannot_be_both_a_source_and_a_citation(tmp_path, monkeypatch):
    # They are opposite promises about the same bytes: a source is parsed on
    # every build and may change, a citation is quoted once and must not.
    folder = tmp_path / "fake_tool"
    (folder / Layout.SOURCES).mkdir(parents=True)
    (folder / Layout.SOURCES / Layout.REGISTRY_FILE).write_text(
        '[tool]\nname = "fake_tool"\n\n'
        '[[source]]\nid = "both"\nurl = "https://example.com/a"\n'
        'cache = "a"\nconsumed_by = "x"\non_removal = "x"\n', encoding="utf-8")
    (folder / Layout.PORTED).mkdir()
    (folder / Layout.PORTED / Layout.CITATIONS_FILE).write_text(
        '[[citation]]\nid = "both"\nurl = "https://example.com/a"\n'
        'anchors = ["x"]\nported_to = "src/x.py :: X"\non_drift = "y"\n',
        encoding="utf-8")
    monkeypatch.setattr(Layout, "TOOLS_DIR", tmp_path)

    with pytest.raises(_registry.RegistryError, match="both a source and a citation"):
        _registry.load("fake_tool")


def test_a_ported_rule_is_probed_as_a_text_contract():
    # No second code path: a citation is structurally a probe-only source
    # whose contract is the lines it quotes, so the machinery that turns "a
    # required string is missing" into a fatal, stated failure already
    # applies, and the janitor leaves it alone because it caches nothing.
    citation = _model.Citation(
        id="c", url="https://example.com/a.cpp", anchors=("one", "two"),
        ported_to="src/x.py :: X.y", on_drift="everything")
    source = citation.as_source()

    assert source.target == citation.url
    assert source.contract.kind == "text"
    assert source.contract.must_contain == citation.anchors
    assert source.fingerprint is None
    assert not source.cache and not source.is_cached


def test_a_rule_that_moved_stops_the_build(tmp_path):
    # The gate, not just the exit code. A port whose premise is gone would
    # otherwise regenerate the catalog from rules the client has replaced,
    # and every string it wrote would look perfectly plausible.
    broken = Report(tool="t", network=Health.OK, first_run=False, verdicts=(
        Verdict(source_id="libbase_model_rules", state=State.CONTRACT_BROKEN,
                contract_errors=("does not contain 'x'",)),))

    assert not broken.may_proceed()
    assert not broken.may_proceed(allow_flaky=True)
    assert _cli.Preflight.code(broken) == _cli.Exit.DEAD


def test_a_ported_rule_is_locked_apart_from_a_source(tmp_path):
    # So the diff stays readable: a line under `sources` means data moved, a
    # line under `citations` means a rule did and a port needs re-reading.
    source = Source(id="feed", url="https://example.com/a",
                    cache="a.json", consumed_by="x", on_removal="x")
    citation = _model.Citation(
        id="rule", url="https://example.com/a.cpp", anchors=("one",),
        ported_to="src/x.py :: X.y", on_drift="everything")
    registry = Registry(tool="t", tool_dir=tmp_path,
                        cache_dir=tmp_path / ".cache",
                        sources=(source,), citations=(citation,))
    lock = Lock(tmp_path / "sources.lock.json")

    rebuilt = lock.rebuild(registry, [
        _verdict(source, State.NEW, now=1),
        _verdict(citation.as_source(), State.NEW),
    ])

    assert set(rebuilt["sources"]) == {"feed"}
    assert set(rebuilt[Lock.CITATIONS]) == {"rule"}


def test_a_ported_rule_declares_no_cache_to_clean(tmp_path):
    citation = _model.Citation(
        id="rule", url="https://example.com/a.cpp", anchors=("one",),
        ported_to="src/x.py :: X.y", on_drift="everything")
    registry = Registry(tool="t", tool_dir=tmp_path,
                        cache_dir=tmp_path / ".cache", citations=(citation,))

    assert registry.declared_cache_files == frozenset()
    assert len(registry.probes) == 1


def test_the_report_keeps_ported_rules_in_their_own_section(tmp_path):
    citation = _model.Citation(
        id="rule", url="https://example.com/a.cpp", anchors=("one",),
        ported_to="src/x.py :: X.y", on_drift="the whole desktop catalog")
    source = Source(id="feed", url="https://example.com/a", cache="a.json",
                    consumed_by="x", on_removal="x")
    registry = Registry(tool="t", tool_dir=tmp_path,
                        cache_dir=tmp_path / ".cache",
                        sources=(source,), citations=(citation,))
    report = Report(tool="t", network=Health.OK, first_run=False, verdicts=(
        Verdict(source_id="feed", state=State.OK),
        Verdict(source_id="rule", state=State.CONTRACT_BROKEN,
                contract_errors=("does not contain 'one'",))))

    text = TextReport.render(report, registry)
    sources_at = text.index("sources -- t")
    ported_at = text.index("ported rules")

    assert sources_at < ported_at
    assert text.index("  feed") < ported_at
    assert text.index("rule") > ported_at
    # And the failure says what to do with it, which is the opposite of what
    # a dead source needs.
    assert "a rule that moved is read, not retried" in text
    assert "has to be removed by hand" not in text
    assert citation.ported_to in text
    assert citation.on_drift in text
