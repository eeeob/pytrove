from __future__ import annotations as _annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Final

import pytest

ROOT: Final[Path] = Path(__file__).resolve().parents[3]

# Each optional distribution, mapped to the top-level modules it installs.
OPTIONAL: Final[dict[str, tuple[str, ...]]] = {
    "cryptography": ("cryptography",),
    "pymongo": ("pymongo", "bson", "gridfs"),
    "pycountry": ("pycountry",),
    "phonenumbers": ("phonenumbers",),
    "kurigram": ("pyrogram",),
    "aioimaplib": ("aioimaplib",),
    "beautifulsoup4": ("bs4",),
    "typeguard": ("typeguard",),
    "wrapt": ("wrapt",),
    "babel": ("babel",),
    "jsonref": ("jsonref",),
    "orjson": ("orjson",),
    "zstandard": ("zstandard",),
    "fastzip": ("fastzip",),
    "pathspec": ("pathspec",),
}

# Runs in a fresh interpreter: hide every optional dependency, then exercise the library.
SCRIPT: Final[str] = textwrap.dedent(
    """
    import asyncio
    import importlib
    import importlib.metadata as md
    import pkgutil
    import re
    import sys
    import tempfile
    from pathlib import Path

    DISTS, MODULES = {dists!r}, {modules!r}
    for name in MODULES:
        sys.modules[name] = None

    _distribution = md.distribution

    def distribution(name):
        if name in DISTS:
            raise md.PackageNotFoundError(name)
        return _distribution(name)

    md.distribution = distribution

    import pytrove
    import pytrove.models

    for info in pkgutil.walk_packages(pytrove.__path__, "pytrove."):
        if info.name.endswith("_core_py312") and sys.version_info < (3, 12):
            continue
        importlib.import_module(info.name)

    def needs(extra, use):
        try:
            result = use()
            if asyncio.iscoroutine(result):
                asyncio.run(result)
        except ImportError as exc:
            named = re.search(r"pytrove\\[([^\\]]*)\\]", str(exc))
            if named is None or extra not in named.group(1).split(", "):
                raise SystemExit(f"{{extra}}: wrong message: {{exc}}")
        else:
            raise SystemExit(f"{{extra}}: no ImportError")

    needs("crypto", lambda: pytrove.encrypt(b"x", "p"))
    needs("country", lambda: pytrove.get_countries())
    needs("locale", lambda: pytrove.get_clanguage_code("SA"))
    needs("phone", lambda: pytrove.cc_from_rc("SA"))
    needs("bs4", lambda: pytrove.parse_email_bytes(b""))
    needs("imap", lambda: pytrove.is_accessible_received_email("a@b.c", "p"))
    needs("jsonref", lambda: pytrove.resolve_json_refs({{}}))
    needs("tg", lambda: pytrove.parse_tg_target("x"))
    needs("tg", lambda: pytrove.models.CompiledTemplate())
    needs("typecheck", lambda: pytrove.validate_type(1, int))
    needs("proxy", lambda: pytrove.RestrictedProxy(object()))
    needs("mongo", lambda: pytrove.MongoIndex())

    from pytrove.archive_tools._internal import backends

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp, "src")
        src.mkdir()
        Path(src, "a.txt").write_text("a", encoding="utf-8")
        Path(src, "b.log").write_text("b", encoding="utf-8")

        # `fastjson`: JSON I/O falls back to the standard library.
        pytrove.write_json(Path(tmp, "x.json"), {{"k": 1}})
        assert pytrove.read_json(Path(tmp, "x.json")) == {{"k": 1}}

        # `archive`: zip and globs fall back to `zipfile` and `fnmatch`.
        out = pytrove.compress_folder(src, Path(tmp, "out.zip"), include="*.txt", workers=2)
        assert pytrove.extract_archive(out, Path(tmp, "x")) is not None
        assert [p.name for p in Path(tmp, "x").rglob("*") if p.is_file()] == ["a.txt"]

        if backends.std_zstd is None:
            needs("archive", lambda: pytrove.compress_folder(src, Path(tmp, "out.tar.zst")))

    print("ok")
    """
)


def test_the_library_works_without_any_extra() -> None:
    modules = sorted(m for names in OPTIONAL.values() for m in names)
    script = SCRIPT.format(dists=sorted(OPTIONAL), modules=modules)
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().endswith("ok")


def test_every_optional_dependency_is_hidden_by_the_check() -> None:
    tomllib = pytest.importorskip("tomllib")
    extras = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    declared = {
        re.match(r"[A-Za-z0-9_.-]+", req).group()
        for name, reqs in extras.items()
        if name not in {"dev", "full"}
        for req in reqs
    }
    assert declared == set(OPTIONAL)
