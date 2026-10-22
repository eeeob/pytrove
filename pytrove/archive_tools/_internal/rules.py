"""The include/exclude ladder both directions of `archive_tools` are filtered by."""

from __future__ import annotations as _annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from ...errors import ValidationError
from ...iter_tools import dedupe
from . import backends

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from ..._internal._types import _RawEntry, _Rule


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

    @staticmethod
    @lru_cache(maxsize=256, typed=True)
    def sort(items: Iterable[_Rule]) -> _Rules:
        """Sort one side's rules onto their rungs, cached on the rules themselves.

        A bare name is a name rung; anything with a `/` is a path; anything with
        `*`, `?` or `[` is a glob. Paths are normalised to posix, without a
        leading `./` or trailing `/`. A predicate built per call (a closure)
        never hits the cache, which holds it until 256 newer keys push it out.

        Args:
            items: The rules, as a hashable tuple.

        Returns:
            The sorted rules.

        Raises:
            ValidationError: For a rule that is neither a pattern nor a callable.
        """
        paths, funcs, names, globs = set(), [], set(), []

        for rule in items:
            item = Path(rule) if isinstance(rule, str) else rule
            if isinstance(item, Path):
                item = "" if (pos := item.as_posix()) in (".", "/") else pos

            if callable(item):
                funcs.append(item)
            elif not isinstance(item, str) or not item:
                msg = f"{item!r} is not a pattern or a callable"
                raise ValidationError(msg)
            elif any(c in item for c in ("*", "?", "[")):
                globs.append(item)
            elif "/" in item:
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
        cls, include: Iterable[_Rule], exclude: Iterable[_Rule], who: str = "compress_folder"
    ) -> _Filter:
        """Build a filter from both sides, naming the caller in any complaint.

        Args:
            include: The include rules.
            exclude: The exclude rules.
            who: The public function's name.

        Returns:
            The filter.

        Raises:
            ValidationError: For a malformed rule, prefixed with `who`.
        """
        try:
            return cls(cls.sort(tuple(dedupe(include))), cls.sort(tuple(dedupe(exclude))), who)
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

        return any(fnmatchcase(rel, pat) for pat in rules.globs)

    def __bool__(self) -> bool:
        """Tell whether either side has any rule."""
        return bool(self.include_rules or self.exclude_rules)

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
        if not self:
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

        return not bool(inc)

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
        exc = self.exclude_rules

        if not exc:
            return True

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
