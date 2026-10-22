"""Checking that a body still looks the way the tool expects.

Pure functions over bytes: no network, no disk, no tool knowledge. Each check
is declared per source in `sources.toml`, so adding a source means describing
its shape, not editing this file.

This is the layer that catches the one failure a status code cannot reveal --
a feed that answers 200 with a reshaped payload. The build would consume it
without complaint and write silently wrong data, which is worse than a crash
because nothing tells you it happened.
"""

from __future__ import annotations as _annotations

import csv
import io
import json
import re
from typing import TYPE_CHECKING, Any, ClassVar

from .enums import ContractKind

if TYPE_CHECKING:
    from collections.abc import Callable

    from .models import Contract

# ============================== the checker ==============================


class ContractCheck:
    """Runs one source's declared contract over its body.

    Returns the list of ways it failed -- empty means it held. A list rather
    than a bool because a reshaped feed usually breaks several expectations at
    once, and a developer deciding whether a source died wants all of them.
    """

    #: A decoded body is kept under this length for error messages.
    SNIPPET: ClassVar[int] = 120

    #: One method per declared kind, so an unknown one is a stated failure
    #: rather than a `KeyError`. A test holds this against `ContractKind`:
    #: a kind that can be declared but not run cannot exist.
    KINDS: ClassVar[dict[ContractKind, str]] = {
        ContractKind.CSV: "_csv",
        ContractKind.JSON_LIST: "_json_list",
        ContractKind.JSON_OBJECT: "_json_object",
        ContractKind.TEXT: "_text",
        ContractKind.GIT_REFS: "_git_refs",
    }

    @classmethod
    def run(cls, contract: Contract | None, body: bytes) -> tuple[str, ...]:
        """Every way the body failed its contract. Never raises.

        A body that cannot even be parsed enough to be judged *is* a contract
        failure, and saying so is the whole job: a malformed CSV used to raise
        `csv.Error: field larger than field limit` out of here and end the run
        in a traceback, which reports nothing, cleans nothing and leaves the
        exit code to chance. The same discipline `fingerprint` already keeps.
        """
        if contract is None:
            return ()

        check = cls.KINDS.get(contract.kind)
        if check is None:
            return ((f"unknown contract kind {contract.kind}; known: {sorted(cls.KINDS)}"),)

        errors = cls._guard(getattr(cls, check), contract, body)

        # `must_contain` and `must_match` apply to every kind, not just text:
        # a JSON feed can be required to still mention a key by name.
        if contract.kind is not ContractKind.TEXT:
            errors += cls._guard(cls._literals, contract, body)

        return tuple(errors)

    @staticmethod
    def _guard(
        check: Callable[[Contract, bytes], list[str]], contract: Contract, body: bytes
    ) -> list[str]:
        """Run one check, turning anything it raises into a stated failure."""
        try:
            return check(contract, body)
        except Exception as exc:  # noqa: BLE001
            return [(f"could not be read as {contract.kind}: {type(exc).__name__}: {exc}")]

    # --- helpers ----------------------------------------------------------

    @classmethod
    def _decode(cls, contract: Contract, body: bytes) -> str:
        return body.decode(contract.encoding, "replace")

    @classmethod
    def _load_json(cls, contract: Contract, body: bytes) -> tuple[Any, list[str]]:
        try:
            return json.loads(cls._decode(contract, body)), []
        except json.JSONDecodeError as exc:
            head = cls._decode(contract, body)[: cls.SNIPPET].replace("\n", " ")
            return None, [f"not JSON ({exc.msg} at line {exc.lineno}): {head!r}"]

    @classmethod
    def _literals(cls, contract: Contract, body: bytes) -> list[str]:
        errors: list[str] = []
        if not (contract.must_contain or contract.must_match):
            return errors

        text = cls._decode(contract, body)
        for needle in contract.must_contain:
            if needle not in text:
                errors.append(f"does not contain {needle!r}")

        if contract.must_match:
            found = len(re.findall(contract.must_match, text, re.M))
            if found < max(contract.min_matches, 1):
                errors.append(
                    f"{found} match(es) for {contract.must_match!r}, "
                    f"expected at least {max(contract.min_matches, 1)}"
                )
        return errors

    # --- one per kind -----------------------------------------------------

    @classmethod
    def _csv(cls, contract: Contract, body: bytes) -> list[str]:
        errors: list[str] = []
        text = cls._decode(contract, body)
        reader = csv.DictReader(io.StringIO(text))

        columns = set(reader.fieldnames or ())
        missing = [c for c in contract.must_have_columns if c not in columns]
        if missing:
            errors.append(f"missing column(s) {missing}; has {sorted(columns)[:6]}")

        rows = sum(1 for _ in reader)
        if rows < contract.min_rows:
            errors.append(f"{rows} rows, expected at least {contract.min_rows}")
        return errors

    @classmethod
    def _json_list(cls, contract: Contract, body: bytes) -> list[str]:
        data, errors = cls._load_json(contract, body)
        if errors:
            return errors
        if not isinstance(data, list):
            return [f"expected a JSON list, got {type(data).__name__}"]

        if len(data) < contract.min_items:
            errors.append(f"{len(data)} items, expected at least {contract.min_items}")

        if contract.item_keys:
            # Every key must appear on at least one item: a feed that renamed
            # a field is what this catches, and requiring it on *every* item
            # would fail on the legitimately sparse ones (appledb omits
            # `released` for unreleased hardware).
            seen: set[str] = set()
            for item in data:
                if isinstance(item, dict):
                    seen |= set(item)
            absent = [k for k in contract.item_keys if k not in seen]
            if absent:
                errors.append(f"no item carries key(s) {absent}")
        return errors

    @classmethod
    def _json_object(cls, contract: Contract, body: bytes) -> list[str]:
        data, errors = cls._load_json(contract, body)
        if errors:
            return errors
        if not isinstance(data, dict):
            return [f"expected a JSON object, got {type(data).__name__}"]

        absent = [k for k in contract.object_keys if k not in data]
        if absent:
            errors.append(f"missing key(s) {absent}")
        if len(data) < contract.min_items:
            errors.append(f"{len(data)} keys, expected at least {contract.min_items}")
        return errors

    @classmethod
    def _text(cls, contract: Contract, body: bytes) -> list[str]:
        return cls._literals(contract, body)

    @classmethod
    def _git_refs(cls, contract: Contract, body: bytes) -> list[str]:
        """A git smart-HTTP ref advertisement.

        Checked structurally rather than by literal, because the response is
        a pkt-line stream: the service header first, then one line per ref.
        An empty advertisement means the remote answered but has no refs,
        which for a repository we clone is as useless as a 404.
        """
        text = cls._decode(contract, body)
        errors: list[str] = []
        if "service=git-upload-pack" not in text:
            errors.append("not a git-upload-pack advertisement")
        if not re.search(r"[0-9a-f]{40}", text):
            errors.append("advertises no refs")
        return errors + cls._literals(contract, body)
