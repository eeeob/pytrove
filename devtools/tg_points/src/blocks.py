"""The randomized id blocks: their bounds, their openings, and the file they go to."""

from __future__ import annotations as _annotations

import ast
from datetime import date
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from .points import Point, Points

#: One block: its lowest id, the id it stops before, and the UTC day it opened.
Block = tuple[int, int, str]


class Blocks:
    """Date each randomized id block by the day it opened, into `tg_blocks.json`.

    Since 2024-02 Telegram opens a range of ids and hands them out at random
    across the whole range, so an id inside a block says which block it is in
    and nothing more. The bounds are LyAdminBot's `randomizedBlocks`. The rule
    that dates them is LyAdminBot's too, and its source contract quotes it: a
    block opened on the earliest day any account inside it was seen, and closed
    when the next one opened. So only the opening is stored; the last block is
    still open.

    ssleg's `tg_account_age` divides the same ids into pools of its own, found
    independently. It is a cross-check printed beside the openings and never
    an input: it lives on a personal server, and it is Python source, which is
    read here as a syntax tree and never run.
    """

    SSLEG_URL: ClassVar[str] = (
        "https://git.ssleg.tech/anton/tg_account_age/raw/branch/master/tg_account_age.py"
    )
    SSLEG_FILE: ClassVar[str] = "ssleg_pools.txt"
    OUT_FILE: ClassVar[str] = "tg_blocks.json"
    #: A pool starting this many days away from its block's opening is flagged.
    #: Today the two agree to within one to nine days.
    DRIFT_DAYS: ClassVar[int] = 14

    def __init__(self, points: Points) -> None:
        """Share `points`' cache, output directory and row checks."""
        self.points = points

    # --- the openings -------------------------------------------------------

    def bounds(self) -> list[tuple[int, int]]:
        """LyAdminBot's `randomizedBlocks`, checked to be sorted, contiguous id ranges."""
        rows = self.points.lyadminbot().get("randomizedBlocks")
        where = f"{self.points.LYADMINBOT_FILE} randomizedBlocks"
        if not isinstance(rows, list) or not rows:
            msg = f"{where}: expected a non-empty list of [low, high] ranges"
            raise SystemExit(msg)

        found: list[tuple[int, int]] = []
        for row in rows:
            match row:
                case [int() as lo, int() as hi] if (
                    0 <= lo < hi and not isinstance(lo, bool) and not isinstance(hi, bool)
                ):
                    pass
                case _:
                    msg = f"{where}: malformed range {row!r}"
                    raise SystemExit(msg)
            if found and found[-1][1] != lo:
                msg = f"{where}: {found[-1]} and {row} are not back to back"
                raise SystemExit(msg)
            found.append((lo, hi))
        return found

    def build(self, today: date) -> list[Block]:
        """Date every block by the earliest observation or constraint inside it.

        Raises:
            SystemExit: A block holds no row to date it by, or the openings do
                not move strictly forward, or one falls outside Telegram's
                lifetime. Nothing has been written by then.
        """
        seen: list[Point] = [
            row
            for name in ("observations", "constraints")
            for rows in self.points.groups(name).values()
            for row in rows
        ]
        blocks: list[Block] = []
        for lo, hi in self.bounds():
            inside = [day for uid, day in seen if lo <= uid < hi]
            if not inside:
                msg = f"block {lo}..{hi} holds no observation or constraint to date its opening"
                raise SystemExit(msg)
            opened = min(inside)
            if blocks and opened <= blocks[-1][2]:
                msg = f"block {lo}..{hi} opened {opened}, not after the block before it"
                raise SystemExit(msg)
            if not self.points.FIRST_DAY <= opened <= today.isoformat():
                msg = f"block {lo}..{hi} opened {opened}, outside Telegram's lifetime"
                raise SystemExit(msg)
            blocks.append((lo, hi, opened))
        return blocks

    # --- the cross-check ----------------------------------------------------

    def pools(self) -> dict[int, str]:
        """Return ssleg's pools as `{highest id: first day}`, read from its syntax tree alone.

        Only `uid_dict = {int: (date(y, m, d), date(y, m, d)), ...}` is accepted;
        any other shape stops the read, and nothing in the file is executed.
        """
        raw = self.points.cache.fetch(self.SSLEG_FILE, self.SSLEG_URL)
        # Every way an untrusted file can fail to parse becomes the one exception the
        # cross-check skips on: bytes that are not UTF-8 (`UnicodeDecodeError` is a
        # `ValueError`), a NUL byte on 3.10/3.11 (`ValueError`), and source nested too
        # deep for CPython's parser, which it reports as `MemoryError` or `RecursionError`.
        try:
            tree = ast.parse(raw.decode("utf-8"))
        except (SyntaxError, ValueError, MemoryError, RecursionError) as exc:
            msg = f"{self.SSLEG_FILE} is not Python ({type(exc).__name__}: {exc})"
            raise SystemExit(msg) from exc

        for node in ast.walk(tree):
            match node:
                case ast.Assign(targets=[ast.Name(id="uid_dict")], value=ast.Dict() as table):
                    return {
                        self.pool_key(k): self.pool_start(v)
                        for k, v in zip(table.keys, table.values, strict=True)
                    }
        msg = f"{self.SSLEG_FILE}: no `uid_dict = {{...}}` assignment"
        raise SystemExit(msg)

    def pool_key(self, node: ast.expr | None) -> int:
        """The highest id of one pool: an int literal and nothing else."""
        match node:
            case ast.Constant(value=int() as uid) if not isinstance(uid, bool):
                return uid
        msg = f"{self.SSLEG_FILE}: a pool key is not an int literal"
        raise SystemExit(msg)

    def pool_start(self, node: ast.expr) -> str:
        """The first day of one pool: `(date(y, m, d), date(y, m, d))` and nothing else."""
        match node:
            case ast.Tuple(
                elts=[
                    ast.Call(
                        func=ast.Name(id="date"),
                        args=[
                            ast.Constant(value=int() as y),
                            ast.Constant(value=int() as m),
                            ast.Constant(value=int() as d),
                        ],
                        keywords=[],
                    ),
                    ast.Call(func=ast.Name(id="date")),
                ]
            ):
                try:
                    return date(y, m, d).isoformat()
                except (OverflowError, ValueError):
                    pass  # a day no calendar holds is as malformed as a wrong shape
        msg = f"{self.SSLEG_FILE}: a pool is not (date(y, m, d), date(y, m, d))"
        raise SystemExit(msg)

    def cross_check(self, blocks: list[Block]) -> None:
        """Print each opening beside the start of ssleg's pool for the same ids.

        Report-only. ssleg is never an input, so its outage or a change in its
        shape costs the cross-check and not the build.
        """
        try:
            pools = self.pools()
        except SystemExit as exc:
            print(f"  ssleg cross-check skipped: {exc.code}")
            return

        for lo, hi, opened in blocks:
            start = pools.get(hi)
            if start is None:
                print(f"    {lo / 1e9:.1f}-{hi / 1e9:.1f}e9  opened {opened}  ssleg: no pool")
                continue
            drift = (date.fromisoformat(start) - date.fromisoformat(opened)).days
            flag = "  !" if abs(drift) >= self.DRIFT_DAYS else ""
            print(
                f"    {lo / 1e9:.1f}-{hi / 1e9:.1f}e9  opened {opened}  "
                f"ssleg {start} ({drift:+d}d){flag}"
            )

    def collect(self, today: date) -> list[Block]:
        """Build the blocks and print the cross-check; the caller writes."""
        blocks = self.build(today)
        print(f"  {len(blocks)} randomized id blocks, the last opened {blocks[-1][2]}")
        self.cross_check(blocks)
        return blocks

    # --- output -------------------------------------------------------------

    def write(self, blocks: list[Block]) -> None:
        """Write one `[low, high, "opened"]` block per line, in id order."""
        lines = ",\n".join(f'  [{lo}, {hi}, "{opened}"]' for lo, hi, opened in blocks)
        out = self.points.data_dir / self.OUT_FILE
        out.write_text(f"[\n{lines}\n]\n", encoding="utf-8", newline="\n")
        print(f"tg_blocks: {len(blocks)} blocks -> {out}")
