"""Reading nested dicts by a dotted key path, and resolving JSON `$ref`s."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, Any, Literal

try:
    import jsonref
except ImportError:
    pass

from .._internal._optional import _optional_import

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

    The inverse of `get_nested_dict_value`.

    Args:
        path_dct: A dict with one key per level, ending in `True` or `1`.
        sep: The separator to join keys with.

    Returns:
        The keys along the branch, joined by `sep`.

    Raises:
        TypeError: If a level holds more than one key, or the leaf is not `True` or `1`.

    Example:
        >>> get_nested_dict_key({"a": {"b": True}})
        'a.b'
    """

    def flatten(current_dict: NestedStrKeyDict[Literal[True, 1]], current_path: str = "") -> str:
        """Follow the branch one level down.

        Args:
            current_dict: The current level.
            current_path: The keys walked so far.

        Returns:
            The full path.

        Raises:
            TypeError: If the leaf is not `True` or `1`.
        """
        key, value = next(iter(current_dict.items()))
        new_path = f"{current_path}{sep}{key}" if current_path else key

        if isinstance(value, dict):
            return flatten(value, new_path)

        if value is not True and value != 1:
            msg = f"leaf at {new_path!r} must be True or 1, not {value!r}"
            raise TypeError(msg)

        return new_path

    if len(path_dct) != 1:
        msg = f"len nested dict must be 1 not {len(path_dct)}"
        raise TypeError(msg)

    return flatten(path_dct)


@_optional_import(("jsonref", "json"))
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
