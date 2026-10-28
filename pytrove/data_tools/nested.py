"""Reading nested dicts by a dotted key path, and resolving JSON `$ref`s."""

from __future__ import annotations as _annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal

try:
    import jsonref  # type: ignore[import-not-found]  # Optional: the `json` extra.
except ImportError:
    pass

from .._internal import _optional_import

if TYPE_CHECKING:
    from ..typings import JsonValue, NestedStrKeyDict, _T


def get_nested_dict_value(dct: NestedStrKeyDict[_T], path: str, sep: str = ".") -> _T:
    """Walk a nested dict down a `sep`-joined key path.

    There is no default and no escaping: a key containing `sep` needs another separator.

    Args:
        dct: The nested dict.
        path: The keys, joined by `sep`.
        sep: The separator between keys.

    Returns:
        The value at the end of the path.

    Raises:
        KeyError: If a key is missing; it names the key.
        TypeError: If the path runs into something that is not a mapping.

    Example:
        >>> get_nested_dict_value({"a": {"b": 1}}, "a.b")
        1
        >>> get_nested_dict_value({"a.b": {"c": 2}}, "a.b/c", sep="/")
        2
    """
    value: Any = dct

    for key in path.split(sep):
        value = value[key]

    return value


def get_nested_dict_key(path_dct: NestedStrKeyDict[Literal[True, 1]], sep: str = ".") -> str:
    """Return the key path a single-branch dict marks.

    The inverse of `get_nested_dict_value`: each key is joined as its `str`,
    an empty one included.

    Args:
        path_dct: A dict with one key per level, ending in `True` or `1`.
        sep: The separator to join keys with.

    Returns:
        The keys along the branch, joined by `sep`.

    Raises:
        TypeError: If a level, at any depth, holds other than one key, or the
            leaf is not `True` or `1`.

    Example:
        >>> get_nested_dict_key({"a": {"b": True}})
        'a.b'
    """
    keys: list[str] = []
    level: Any = path_dct

    while True:
        if len(level) != 1:
            msg = f"len nested dict must be 1 not {len(level)}, at {sep.join(keys)!r}"
            raise TypeError(msg)

        key, level = next(iter(level.items()))
        keys.append(str(key))

        if not isinstance(level, Mapping):
            break

    path = sep.join(keys)

    if level is not True and level != 1:
        msg = f"leaf at {path!r} must be True or 1, not {level!r}"
        raise TypeError(msg)

    return path


@_optional_import("json")
def resolve_json_refs(content: JsonValue, **kw: Any) -> JsonValue:
    """Replace every `$ref` in an already-parsed JSON document.

    Two jsonref defaults are reversed so the result behaves as plain data:
    `proxies=False` substitutes real objects, and `lazy_load=False` resolves
    everything now so a broken ref fails here. A relative ref needs `base_uri`.

    Args:
        content: The parsed document.
        **kw: Extra `jsonref.replace_refs` arguments.

    Returns:
        The document with every reference replaced.
    """
    kw.setdefault("proxies", False)
    kw.setdefault("lazy_load", False)
    return jsonref.replace_refs(content, **kw)


__all__ = (
    "get_nested_dict_value",
    "get_nested_dict_key",
    "resolve_json_refs",
)
