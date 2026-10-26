"""Each extra missing on its own: the rest of the library works and its feature names the cure."""

from __future__ import annotations as _annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Final, NamedTuple

import pytest

ROOT: Final[Path] = Path(__file__).resolve().parents[3]


class Extra(NamedTuple):
    """What one extra installs, and how to reach a feature it gates.

    Attributes:
        dists: The distributions the extra installs.
        modules: The top-level modules those distributions provide.
        use: A Python expression, run in the subprocess, that uses a gated feature.
            Empty when the extra only speeds things up and nothing raises without it.
    """

    dists: tuple[str, ...]
    modules: tuple[str, ...]
    use: str


EXTRAS: Final[dict[str, Extra]] = {
    "mongo": Extra(("pymongo",), ("pymongo", "bson", "gridfs"), "pytrove.MongoIndex()"),
    "country": Extra(
        ("pycountry", "phonenumbers"), ("pycountry", "phonenumbers"), "pytrove.get_countries()"
    ),
    "crypto": Extra(("cryptography",), ("cryptography",), "pytrove.encrypt(b'x', 'p')"),
    "bs4": Extra(("beautifulsoup4",), ("bs4",), "pytrove.parse_email_bytes(b'')"),
    "imap": Extra(
        ("aioimaplib",), ("aioimaplib",), "pytrove.is_accessible_received_email('a@b.c', 'p')"
    ),
    "phone": Extra(("phonenumbers",), ("phonenumbers",), "pytrove.cc_from_rc('SA')"),
    "tg": Extra(("kurigram",), ("pyrogram",), "pytrove.parse_tg_target('x')"),
    "typecheck": Extra(("typeguard",), ("typeguard",), "pytrove.validate_type(1, int)"),
    "proxy": Extra(("wrapt",), ("wrapt",), "pytrove.RestrictedProxy(object())"),
    "locale": Extra(("babel",), ("babel",), "pytrove.get_clanguage_code('SA')"),
    # `orjson` only speeds JSON I/O up; `jsonref` is the part that raises without the extra.
    "json": Extra(("jsonref", "orjson"), ("jsonref", "orjson"), "pytrove.resolve_json_refs({})"),
    # zstd is in the standard library from 3.14, so only older versions reach the gate.
    "archive": Extra(
        ("zstandard", "fastzip", "pathspec"),
        ("zstandard", "fastzip", "pathspec"),
        "pytrove.compress_folder(src, Path(tmp, 'out.tar.zst'))"
        if sys.version_info < (3, 14)
        else "",
    ),
}

# Runs in a fresh interpreter: hide one extra, check an unrelated tool, then use the gated feature.
SCRIPT: Final[str] = textwrap.dedent(
    """
    import asyncio
    import importlib.metadata as md
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

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp, "src")
        src.mkdir()
        Path(src, "a.txt").write_text("a", encoding="utf-8")

        if list(pytrove.iter_flat_cont([1, [2, 3]])) != [1, 2, 3]:
            raise SystemExit("unrelated tool broke")
        pytrove.write_json(Path(tmp, "x.json"), {{"k": 1}})
        if pytrove.read_json(Path(tmp, "x.json")) != {{"k": 1}}:
            raise SystemExit("JSON fallback broke")

        def use():
            return {use}

        try:
            result = use()
            if asyncio.iscoroutine(result):
                asyncio.run(result)
        except ImportError as exc:
            print(exc)
        else:
            print("no gate" if result is None else "no ImportError")
    """
)


def _run(extra: Extra) -> str:
    """Run `SCRIPT` with `extra` hidden and return its output.

    Args:
        extra: The extra to hide.

    Returns:
        The subprocess stdout.
    """
    script = SCRIPT.format(
        dists=list(extra.dists), modules=list(extra.modules), use=extra.use or "None"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout


@pytest.mark.parametrize("name", list(EXTRAS), ids=list(EXTRAS))
def test_a_missing_extra_breaks_only_its_own_feature(name: str) -> None:
    """Without `name`, unrelated tools still work and its gated feature names the extra and the cure."""
    extra = EXTRAS[name]
    output = _run(extra)

    if not extra.use:
        assert output.strip() == "no gate"
        return

    assert f"Run: pip install -U 'pytrove[{name}]'" in output
    missing = re.search(r"^Missing  : (.+)$", output, re.MULTILINE)
    assert missing is not None, output
    named = set(re.findall(r"'([A-Za-z0-9_.-]+)", missing.group(1)))
    assert named, output
    assert named <= set(extra.dists)


def test_the_cases_cover_every_declared_extra() -> None:
    """`EXTRAS` lists exactly the extras, and their distributions, declared in `pyproject.toml`."""
    tomllib = pytest.importorskip("tomllib")
    extras = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "optional-dependencies"
    ]
    declared = {
        name: {re.match(r"[A-Za-z0-9_.-]+", req).group() for req in reqs}
        for name, reqs in extras.items()
        if name not in {"dev", "full"}
    }
    assert declared == {name: set(extra.dists) for name, extra in EXTRAS.items()}
