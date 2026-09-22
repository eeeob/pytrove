from __future__ import annotations as _annotations

from typing import (
    Mapping,
    Any, Literal,
    Callable, overload, cast,
    Final,
)

from .typings import (
    Container, ContainerWithoutMapping, 
    NestedContainer, 
    _KT, _VT, _T
)

from .enums import TgMessageLength

from .validate_tools import is_mapping, is_container
from .iter_tools import to_list, flat_cont

import re


_SNAKE1_PATTERN: Final[re.Pattern[str]] = re.compile(r"(.)([A-Z][a-z]+)")
_SNAKE2_PATTERN: Final[re.Pattern[str]] = re.compile(r"([a-z0-9])([A-Z])")


_NOT_SET: Final = object()


def to_str(value: _T) -> str | _T:
    return (
        value 
        if value is None or isinstance(value, (bool, str)) or is_container(value) 
        else str(value)
    )

def clean_spaces(text: Any, with_lines: bool = True) -> str:
    text = to_str(text)
    return re.sub(r"\s+", "", text) if with_lines else re.sub(r"[^\S\n]+", "", text)

def split_part(
    value: str, 
    sep: str, 
    part: int = 0, 
    strip: bool = True, 
    remove_spaces: bool = False, 
    default: _T = cast(str, _NOT_SET)
    ) -> str | _T:

    try:
        value = value.split(sep)[part]

        if strip:
            value = value.strip()
        
        if remove_spaces:
            value = clean_spaces(value)

        return value
    except IndexError:
        return value if default is _NOT_SET else default

def chunk_text(text: str, max_length: int = TgMessageLength.TEXT) -> list[str]:
    """Split `text` into pieces of at most `max_length` characters, preferring
    to break on a newline, then a space, so words/lines aren't cut mid-way.

    Break point priority within one `max_length`-sized window:
      1. the last newline in it, if any;
      2. else the last space, but only if it falls in the later 90% of the
         window (`> len(chunk) // 10`) -- a space found near the very start
         would produce a near-empty chunk and barely shrink `remaining`,
         so a match that close to the front is treated as "no usable space"
         and falls through to the hard cut instead;
      3. else a hard cut at exactly `max_length`, mid-word if necessary.
    """

    if len(text) <= max_length:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        chunk = remaining[:max_length]

        if len(remaining) <= max_length:
            remaining = ""
        elif (last_newline := chunk.rfind('\n')) > 0:
            chunk = chunk[:last_newline]
            remaining = remaining[last_newline + 1:]
        elif (last_space := chunk.rfind(" ")) > len(chunk) // 10:
            chunk = chunk[:last_space]
            remaining = remaining[last_space + 1:]
        else:
            remaining = remaining[max_length:]

        if chunk.strip():
            chunks.append(chunk.strip())

    return chunks

def format_exc_tree(exc: BaseException) -> str:
    """Render `exc` and its chained causes/contexts as an indented tree, one
    line per exception, deepest cause last.

    `__cause__ or __context__` follows whichever chaining Python actually
    used: `__cause__` is set by explicit `raise X from Y`, `__context__` is
    set implicitly whenever an exception is raised while another is already
    being handled. Preferring `__cause__` matches how the traceback module
    itself decides which chain to print.
    """

    def iter_exc():
        current = exc
        level = 0

        while current is not None:
            yield level, current

            current = current.__cause__ or current.__context__
            level += 1

    return "\n".join(
        f"{'    ' * level}└─ {type(error).__name__}: {error}"
        for level, error in iter_exc()
    )


@overload
def numbering(
    values: 'ContainerWithoutMapping[_T]', 
    start: int = 1, 
    line_parser: Callable[[_T, int], str] | None = None, 
    line_sep: str = "\n", 
    ) -> str : ... 
@overload
def numbering(
    values: Mapping[_KT, _VT], 
    start: int = 1, 
    line_parser: Callable[[_KT, _VT, int], str] | None = None, 
    line_sep: str = "\n", 
    ) -> str : ... 
@overload
def numbering(
    values: 'ContainerWithoutMapping[_T]',
    start: int = 1,
    line_parser: Callable[[_T, int], str] | None = None,
    *, 
    line_sep: Literal[None],
) -> list[str]: ...
@overload
def numbering(
    values: Mapping[_KT, _VT],
    start: int = 1,
    line_parser: Callable[[_KT, _VT, int], str] | None = None,
    *, 
    line_sep: Literal[None],
) -> list[str]: ...
def numbering(
    values: Container, 
    start: int = 1, 
    line_parser: Callable[..., str] | None = None, 
    line_sep: str | None = "\n", 
    ):

    is_map = is_mapping(values)

    if is_map:
        values = values.items()
    
    values = to_list(values)
    
    if line_parser is None:
        line_parser = (lambda k, v, c: f"{c}. {k} - {v}") if is_map else (lambda v, c: f"{c}. {v}")
    
    if is_map:
        values = [
            line_parser(key, value, counter)
            for counter, (key, value) in enumerate(values, start)
        ]
    else:
        values = [
            line_parser(value, counter)
            for counter, value in enumerate(values, start)
        ]
    
    if line_sep is not None:
        values = line_sep.join(values)

    return values



def _smart_split_helper(
    text, 
    filter, 
    strip, 
    remove_spaces, 
    resolver
    ):

    if filter is not None and not filter(text):
        return _NOT_SET

    if remove_spaces:
        text = clean_spaces(text)
    elif strip:
        text = text.strip()

    if resolver is not None:
        text = resolver(text)

    return text


@overload
def smart_split(
    text: NestedContainer[str],
    indexing: int,
    part_resolver: Callable[[str], _T],
    strip: bool = ...,
    remove_spaces: bool = ...,
    max_split: int = ...,
    part_filter: Callable[[str], bool] | None = ...,
    *,
    separator: str | Callable[[], str],
) -> _T: ...
@overload
def smart_split(
    text: NestedContainer[str],
    indexing: int,
    *,
    strip: bool = ...,
    remove_spaces: bool = ...,
    max_split: int = ...,
    part_filter: Callable[[str], bool] | None = ...,
    separator: str | Callable[[], str],
) -> str: ...
@overload
def smart_split(
    text: NestedContainer[str],
    indexing: slice,
    part_resolver: Callable[[str], _T],
    strip: bool = ...,
    remove_spaces: bool = ...,
    max_split: int = ...,
    part_filter: Callable[[str], bool] | None = ...,
    *,
    separator: str | Callable[[], str],
) -> list[_T]: ...
@overload
def smart_split(
    text: NestedContainer[str],
    indexing: slice,
    *,
    strip: bool = ...,
    remove_spaces: bool = ...,
    max_split: int = ...,
    part_filter: Callable[[str], bool] | None = ...,
    separator: str | Callable[[], str],
) -> list[str]: ...
@overload
def smart_split(
    text: NestedContainer[str],
    *,
    part_resolver: Callable[[str], _T],
    strip: bool = ...,
    remove_spaces: bool = ...,
    max_split: int = ...,
    part_filter: Callable[[str], bool] | None = ...,
    separator: str | Callable[[], str],
) -> list[_T]: ...
@overload
def smart_split(
    text: NestedContainer[str],
    *,
    strip: bool = ...,
    remove_spaces: bool = ...,
    max_split: int = ...,
    part_filter: Callable[[str], bool] | None = ...,
    separator: str | Callable[[], str],
) -> list[str]: ...
def smart_split(
    text: NestedContainer[str],
    indexing = None,
    part_resolver = None,
    strip = False,
    remove_spaces = False,
    max_split = -1,
    part_filter = None,
    *,
    separator,
    ):
    """Split `text` on `separator`, then optionally index/strip/filter/convert
    the parts.

    `text` may already be a container of strings instead of a single string
    -- in that case `separator`/`max_split` are skipped and the container is
    just flattened, so this doubles as "accept either a string to split or an
    already-split sequence of parts" for callers that don't know which they
    have. `separator` may be a zero-arg callable, resolved once per call, for
    separators that need to be computed (e.g. a compiled regex's pattern).
    `indexing` (an int or slice) then narrows down to specific part(s); an int
    index returns that single part unwrapped rather than a one-item list.

    `part_filter`, if given, runs on the raw part -- *before* strip/
    remove_spaces, not after -- and always before `part_resolver` (so it
    always sees a plain string, regardless of what part_resolver converts
    to); parts it rejects are dropped entirely rather than cleaned or
    resolved. That ordering means a whitespace-only part (e.g. `" "`) is
    *not* rejected by `part_filter=bool` on its own -- it's only blank once
    `strip`/`remove_spaces` has run on it, which happens after the filter
    already let it through. Filter on the cleaned form explicitly (e.g.
    `part_filter=lambda t: bool(t.strip())`) if that's what you want. With
    `indexing` as an int, filtering out the one selected part leaves nothing
    to unwrap and raises IndexError, same as indexing past the end of
    `texts` already does.
    """

    if callable(separator):
        separator = separator()

    texts = text.split(separator, max_split) if isinstance(text, str) else flat_cont(text)

    if indexing is not None:
        texts = to_list(texts[indexing])

    texts = [
        txt for t in texts
        if (txt := _smart_split_helper(t, part_filter, strip, remove_spaces, part_resolver)) is not _NOT_SET
    ]

    return texts[0] if isinstance(indexing, int) else texts



def y_or_n(value: Any) -> Literal["✅", "❌"]:
    return "✅" if value else "❌"

def en_or_dis(value: Any) -> Literal["مفعل ✅", "معطل ❌"]:
    return "مفعل ✅" if value else "معطل ❌"

def op_or_cl(value: Any) -> Literal["مفتوح ✅", "مغلق ❌"]:
    return "مفتوح ✅" if value else "مغلق ❌"


def to_snake_case(text: str) -> str:
    return _SNAKE2_PATTERN.sub(
        r"\1_\2", _SNAKE1_PATTERN.sub(r"\1_\2", text)
    ).lower()


def to_pascal_case(text: str) -> str:
    return "".join(
        i.title() 
        for i in to_snake_case(text).split("_")
        if i
    )


__all__ = (
    "clean_spaces",
    "to_str",
    "y_or_n",
    "en_or_dis",
    "op_or_cl",
    "split_part",
    "numbering",
    "format_exc_tree", 
    "smart_split", 
    "chunk_text", 
    "to_snake_case", 
    "to_pascal_case", 
    
)