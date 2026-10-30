"""The include/exclude ladder both directions of `archive_tools` are filtered by."""

from __future__ import annotations as _annotations

import os
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Any, NamedTuple, cast

from ...errors import ValidationError
from ...iter_tools import dedupe, iter_flat_cont
from . import backends

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from ..._internal import _RawEntry, _Rule
    from ...typings import NestedContainer


class _Rules(NamedTuple):
    """One side's rules, sorted onto the rungs they are tested on.

    Names and whole paths sit in sets, one hash lookup each however many
    there are; only real globs reach a matcher.
    """

    paths: frozenset[str] = frozenset()
    """Whole relative posix paths, anchored at the root."""

    funcs: tuple[Callable[[str, _RawEntry], bool], ...] = ()
    """Predicates over `(relative path, entry)`."""

    names: frozenset[str] = frozenset()
    """Bare names, matched at any depth."""

    globs: tuple[str, ...] = ()
    """Patterns for `fnmatch`; empty when `spec` holds them instead."""

    spec: Any = None
    """The globs compiled as a `pathspec.PathSpec` (gitignore style) when `pathspec` is installed, else `None`."""

    def __bool__(self) -> bool:
        """Tell whether this side has any rule at all."""
        return any(self)


@dataclass(slots=True)
class _Filter:
    """Decides which entries an archive operation keeps.

    The ladder, first match wins: include path, exclude path, include
    predicate, exclude predicate, include name, exclude name, exclude glob,
    include glob. With no include rule everything else is kept; with one,
    only what matches.
    """

    include_rules: _Rules
    """The include side; empty means everything not excluded is kept."""

    exclude_rules: _Rules
    """The exclude side; the only side `enter` consults."""

    who: str = "compress_folder"
    """The public function's name, for error messages."""

    _has_include: bool = field(init=False, repr=False, compare=False)
    """Whether the include side holds a rule; fixed, since both sides are immutable."""

    _has_exclude: bool = field(init=False, repr=False, compare=False)
    """Whether the exclude side holds a rule; fixed, since both sides are immutable."""

    def __post_init__(self) -> None:
        """Weigh each side once, rather than on every entry the filter is asked about."""
        self._has_include = bool(self.include_rules)
        self._has_exclude = bool(self.exclude_rules)

    @staticmethod
    @lru_cache(maxsize=256, typed=True)
    def sort(items: Iterable[_Rule]) -> _Rules:
        """Sort one side's rules onto their rungs, cached on the rules themselves.

        Anything with `*`, `?` or `[` is a glob; else anything whose text has a
        `/` is a path, so `./logs` and `logs/` are paths too; else it is a bare
        name. That is decided on the text as given, then paths are normalised
        to posix, without a leading `./` or trailing `/`; a glob that began with
        `./` gets a leading `/` instead, which anchors it at `src`. A `PurePath` (of
        either flavour) is read as its posix text and any other `os.PathLike`
        as its `os.fspath`. A predicate built per call (a closure) never hits
        the cache, which holds it until 256 newer keys push it out.

        Args:
            items: The rules, as a hashable tuple.

        Returns:
            The sorted rules.

        Raises:
            ValidationError: For a rule that is neither a pattern nor a callable,
                or one naming no entry (``, `.`, `/`).
        """
        paths, funcs, names, globs = set(), [], set(), []

        for rule in items:
            if callable(rule):
                funcs.append(rule)
                continue

            text: object = (
                rule.as_posix()
                if isinstance(rule, PurePath)
                else os.fspath(rule)
                if isinstance(rule, os.PathLike)
                else rule
            )
            msg = f"{rule!r} is not a pattern or a callable"

            if not isinstance(text, str) or not text:
                raise ValidationError(msg)

            if (item := Path(text).as_posix()).strip("/") in ("", "."):
                raise ValidationError(msg)

            # Judged on `text` too, since `Path` drops the `/` of `./x` and `x/`;
            # `item` catches a Windows `\`, which `Path` turned into `/`.
            if any(c in item for c in ("*", "?", "[")):
                # `Path` drops the `./` that anchors `./*.log`; a leading `/` keeps the anchor.
                globs.append(f"/{item}" if text[:2] in ("./", f".{os.sep}") else item)
            elif "/" in text or "/" in item:
                paths.add(item.lstrip("/"))
            else:
                names.add(item)

        spec = (
            None
            if backends.PathSpec is None or not globs
            else backends.PathSpec.from_lines(
                "gitignore", (("\\" + g if g[:1] in ("#", "!") else g) for g in globs)
            )
        )

        if spec is not None:
            globs.clear()

        return _Rules(frozenset(paths), tuple(funcs), frozenset(names), tuple(globs), spec)

    @classmethod
    def from_rules(
        cls,
        include: NestedContainer[_Rule] | None,
        exclude: NestedContainer[_Rule] | None,
        who: str = "compress_folder",
    ) -> _Filter:
        """Build a filter from both sides, naming the caller in any complaint.

        Args:
            include: The include rules, at any nesting; `None` for none.
            exclude: The exclude rules, at any nesting; `None` for none.
            who: The public function's name.

        Returns:
            The filter.

        Raises:
            ValidationError: For a malformed rule, prefixed with `who`.
        """
        # `ty` binds `_T` to the container arm of the recursive `NestedContainer[_T]`, so
        # it cannot recover the leaf type (astral-sh/ty#1703); the parameter states it.
        includes = cast("Iterator[_Rule]", iter_flat_cont(include))
        excludes = cast("Iterator[_Rule]", iter_flat_cont(exclude))

        try:
            return cls(cls.sort(tuple(dedupe(includes))), cls.sort(tuple(dedupe(excludes))), who)
        except ValidationError as exc:
            msg = f"{who}: {exc}"
            raise ValidationError(msg) from None

    @staticmethod
    def glob_hit(rel: str, rules: _Rules) -> bool:
        """Tell whether one side's globs match, through whichever backend holds them.

        Args:
            rel: The relative posix path.
            rules: The side to ask.

        Returns:
            Whether any glob matches.
        """
        if rules.spec is not None:
            return rules.spec.match_file(rel)

        if not rules.globs:
            return False

        # An anchored `/pat` matches only at its own depth: with as many `/` as
        # `rel`, `fnmatch`'s `*` cannot cross one.
        depth = rel.count("/")
        return any(
            fnmatchcase(rel, pat[1:]) and pat.count("/") - 1 == depth
            if pat[:1] == "/"
            else fnmatchcase(rel, pat)
            for pat in rules.globs
        )

    def __bool__(self) -> bool:
        """Tell whether either side has any rule."""
        return self._has_include or self._has_exclude

    @staticmethod
    def _ask(fn: Callable[[str, _RawEntry], Any], rel: str, raw: _RawEntry, side: str) -> bool:
        """Put one entry to a caller's predicate, naming the rule if it raises.

        The second argument differs by direction (`os.DirEntry` when
        compressing, `ZipInfo`/`TarInfo`/`None` when extracting), so a rule
        written for one can fail on the other.

        Args:
            fn: The predicate.
            rel: The relative path.
            raw: The entry.
            side: The public function's name.

        Returns:
            The predicate's answer.

        Raises:
            ValidationError: If the predicate raised, with the original as cause.
        """
        try:
            return bool(fn(rel, raw))
        except Exception as exc:
            msg = (
                f"{side}: the rule {getattr(fn, '__name__', fn)!r} raised {type(exc).__name__} on {rel!r} -- note "
                f"the second argument is an os.DirEntry while a folder is walked and the archive's own header "
                f"(ZipInfo/TarInfo, or None for an implied directory) while one is read, so a rule that reads it "
                f"has to handle both"
            )
            raise ValidationError(msg) from exc

    def matches(self, rel: str, raw: _RawEntry = None) -> bool:
        """Tell whether an entry belongs in the result, walking the ladder.

        A rule is matched against this entry only: `sub/*` is sub's direct
        children, `sub/**` its subtree. Exclusions reach further down only by
        pruning, which is `enter`'s job.

        Args:
            rel: The relative posix path.
            raw: The entry, handed to predicates.

        Returns:
            Whether it is kept.
        """
        if not (self._has_include or self._has_exclude):
            return True

        inc, exc = self.include_rules, self.exclude_rules

        if rel in inc.paths:
            return True
        if rel in exc.paths:
            return False

        for fn in inc.funcs:
            if self._ask(fn, rel, raw, self.who):
                return True
        for fn in exc.funcs:
            if self._ask(fn, rel, raw, self.who):
                return False

        base = rel.rsplit("/", 1)[-1]

        if base in inc.names:
            return True
        if base in exc.names:
            return False

        if self.glob_hit(rel, exc):
            return False
        if self.glob_hit(rel, inc):
            return True

        return not self._has_include

    def enter(self, rel: str, raw: _RawEntry = None) -> bool:
        """Tell whether a walk should descend into a directory.

        Only the exclude side answers: an include match may lie at any depth
        below, and a pruned directory takes its whole subtree with it.

        Args:
            rel: The directory's relative posix path.
            raw: The entry, handed to predicates.

        Returns:
            Whether to descend.
        """
        if not self._has_exclude:
            return True

        exc = self.exclude_rules

        if rel in exc.paths:
            return False

        for fn in exc.funcs:
            if self._ask(fn, rel, raw, self.who):
                return False

        if rel.rsplit("/", 1)[-1] in exc.names:
            return False

        return not self.glob_hit(rel, exc)


__all__ = (
    "_Filter",
    "_Rules",
)
