"""Converting values to text, cleaning it, and changing its case style."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, Any

from .._internal import _is_given
from ..validate_tools import is_container
from ._internal import _SNAKE1_PATTERN, _SNAKE2_PATTERN, _SPACES_PATTERN, _WHITESPACE_PATTERN
from .split import smart_split

if TYPE_CHECKING:
    from ..typings import _T


def to_str(value: _T) -> str | _T:
    """Turn a value into a string, leaving strings, bytes, bools, `None` and containers as they are.

    Bytes stay bytes rather than becoming their `repr`, since no encoding is known.

    Args:
        value: The value to convert.

    Returns:
        `str(value)`, or `value` itself when it is `None`, a bool, a string,
        bytes-like (`bytes`, `bytearray`, `memoryview`) or a container.

    Example:
        >>> to_str(5)
        '5'
        >>> to_str([5])
        [5]
        >>> to_str(b"ab")
        b'ab'
    """
    # Returned as `unchanged`: narrowing `value` through `is_container` would lose that it is a `_T`.
    unchanged: _T = value

    if (
        value is None
        or isinstance(value, (bool, str, bytes, bytearray, memoryview))
        or is_container(value)
    ):
        return unchanged
    return str(value)


def clean_spaces(text: Any, include_newlines: bool = True) -> str:
    r"""Remove whitespace from text.

    Args:
        text: The text, or a value `to_str` turns into text.
        include_newlines: Whether `\n` goes too; when false, every other
            whitespace, `\r` included, is still removed.

    Returns:
        The text without whitespace.

    Raises:
        TypeError: If `text` is not a string and `to_str` leaves it unconverted.

    Example:
        >>> clean_spaces(" a b\nc ")
        'abc'
        >>> clean_spaces(" a b\nc ", include_newlines=False)
        'ab\nc'
    """
    text = to_str(text)
    if not isinstance(text, str):
        msg = f"clean_spaces: text must be a str or a value `to_str` turns into one, not {type(text).__name__!r}"
        raise TypeError(msg)
    return (_WHITESPACE_PATTERN if include_newlines else _SPACES_PATTERN).sub("", text)


def split_part(
    value: str,
    sep: str,
    part: int = 0,
    strip: bool = True,
    remove_spaces: bool = False,
    default: _T | type[object] = object,
) -> str | _T:
    """Split `value` on `sep` and return one part.

    Args:
        value: The text to split.
        sep: The separator.
        part: The index of the part to return.
        strip: Whether to strip surrounding whitespace from the part.
        remove_spaces: Whether to remove all whitespace from the part.
        default: What to return when `part` is out of range; `value` itself when omitted.

    Returns:
        The selected part, cleaned as asked.

    Example:
        >>> split_part("a, b, c", ",", 1)
        'b'
        >>> split_part("a,b", ",", 5)
        'a,b'
        >>> split_part("a,b", ",", 5, default=None) is None
        True
    """
    try:
        return smart_split(value, part, strip=strip, remove_spaces=remove_spaces, separator=sep)
    except IndexError:
        return default if _is_given(default) else value


def to_snake_case(text: str) -> str:
    """Turn `camelCase` or `PascalCase` into `snake_case`.

    Only ASCII capitals start a word, and a capital right after `_` adds no
    second underscore.

    Args:
        text: The text to convert.

    Returns:
        The text in lowercase, with an underscore before each word that began with a capital.

    Example:
        >>> to_snake_case("userId")
        'user_id'
        >>> to_snake_case("HTTPServerError")
        'http_server_error'
    """
    return _SNAKE2_PATTERN.sub(r"\1_\2", _SNAKE1_PATTERN.sub(r"\1_\2", text)).lower()


def to_pascal_case(text: str) -> str:
    """Turn `snake_case` or `camelCase` into `PascalCase`.

    Words are the `to_snake_case` words; only their first character is
    capitalised, so a letter after a digit or a `-` stays lowercase.

    Args:
        text: The text to convert.

    Returns:
        Each word capitalised and joined with no separator.

    Example:
        >>> to_pascal_case("user_id")
        'UserId'
        >>> to_pascal_case("user_2fa")
        'User2fa'
    """
    return "".join(word[:1].upper() + word[1:] for word in to_snake_case(text).split("_") if word)


__all__ = (
    "to_str",
    "clean_spaces",
    "split_part",
    "to_snake_case",
    "to_pascal_case",
)
