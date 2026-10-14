"""Reducing a body to the one value worth watching.

Pure functions over bytes, like `contract`, and declared per source the same
way -- but answering a different question. The contract asks *is this still
valid*; the fingerprint asks *what is it now*, so two runs can be compared.

Why not just hash the body: a hash changes whenever anything upstream moves,
including a reordered field or a reformatted line, and it can only ever say
"something changed". A semantic value says what changed and by how much:

    chrome_releases_win   156 -> 157
    play_catalog          28431 -> 28502 rows
    linuxhw_dmi_repo      a1b2c3d -> 9f8e7d6

The first reads as a sentence on a dashboard and tells you whether a rebuild
is worth it. The hash is still recorded in the lock, as the fallback for
bodies with no natural scalar and as a tiebreaker.
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any, Callable, ClassVar

from .model import Fingerprint

# ============================== extraction ==============================

class FingerprintValue:
    """Computes one source's declared fingerprint.

    Returns `None` when the body cannot yield the value. That is deliberately
    not an error: a fingerprint is a comparison aid, and a source whose body
    is malformed has already failed its contract, which is the loud signal.
    """

    #: csv_rows decodes the whole body; the Play catalog is UTF-16 and ~5 MB,
    #: so the encoding has to come from the declaration, not be assumed.
    DEFAULT_ENCODING: ClassVar[str] = "utf-8"

    @classmethod
    def of(cls, fingerprint: Fingerprint | None, body: bytes,
           *, encoding: str = DEFAULT_ENCODING) -> Any:
        if fingerprint is None or body is None:
            return None

        kinds: dict[str, Callable[..., Any]] = {
            "bytes_len": cls._bytes_len,
            "csv_rows": cls._csv_rows,
            "json_len": cls._json_len,
            "regex_count": cls._regex_count,
            "regex_max_int": cls._regex_max_int,
            "git_head": cls._git_head,
        }
        try:
            return kinds[fingerprint.kind](body, fingerprint.pattern, encoding)
        except Exception:                                 # noqa: BLE001
            return None

    # --- the kinds --------------------------------------------------------

    @staticmethod
    def _bytes_len(body: bytes, _pattern: str, _encoding: str) -> int:
        return len(body)

    @staticmethod
    def _csv_rows(body: bytes, _pattern: str, encoding: str) -> int:
        reader = csv.reader(io.StringIO(body.decode(encoding, "replace")))
        next(reader, None)                                # the header
        return sum(1 for _ in reader)

    @staticmethod
    def _json_len(body: bytes, _pattern: str, encoding: str) -> int:
        return len(json.loads(body.decode(encoding, "replace")))

    @staticmethod
    def _regex_count(body: bytes, pattern: str, encoding: str) -> int:
        return len(re.findall(pattern, body.decode(encoding, "replace"), re.M))

    @staticmethod
    def _regex_max_int(body: bytes, pattern: str, encoding: str) -> int | None:
        found = re.findall(pattern, body.decode(encoding, "replace"), re.M)
        numbers = [int(m if isinstance(m, str) else m[0]) for m in found
                   if (m if isinstance(m, str) else m[0]).isdigit()]
        return max(numbers) if numbers else None

    @staticmethod
    def _git_head(body: bytes, _pattern: str, _encoding: str) -> str | None:
        """The SHA a git remote advertises for HEAD.

        The advertisement lists `<sha> HEAD` first, then the branches. Taking
        HEAD rather than the first SHA keeps the value stable when a remote
        reorders its refs.
        """

        text = body.decode("utf-8", "replace")
        head = re.search(r"([0-9a-f]{40})\s+HEAD", text)
        if head:
            return head.group(1)
        first = re.search(r"([0-9a-f]{40})", text)
        return first.group(1) if first else None
