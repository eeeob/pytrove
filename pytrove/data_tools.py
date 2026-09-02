from typing import Union, Dict, Any, Mapping, Literal, Tuple, Type, overload
from enum import Enum

from .typings import _T, _KT, _VT, _EnumT, Container, NestedContainer, NestedStrKeyDict, JsonValue
from .errors import ValidationError
from .validate_tools import is_container, is_mapping
from .iter_tools import iter_flat_cont, to_frozenset
from ._optional import _optional_import
from ._data_tools import _MESS, _reconstruct, _reconstruct_mapping

try:
    import jsonref
except ImportError:
    pass


def _none_cleaner(v):
    """clean_none_values' per-value step: drop a None, recurse into the rest."""

    if v is None:
        return _MESS

    return clean_none_values(v)


def enum_to_value(data: _T) -> _T:
    """Replace every Enum member in `data` with its `.value`, recursively.

    The inverse of value_to_enum, and the step that makes a structure
    serialisable: an Enum member is not JSON, and `.value` is what it was
    standing for. Anything that is not an Enum and not a container is handed
    back untouched. Both sides of a mapping are converted.

    Containers and mappings keep their own type wherever possible; see
    _data_tools._reconstruct/_reconstruct_mapping for the exceptions -- a
    container that cannot be rebuilt is returned un-transformed with a
    warning, a mapping that cannot falls back to dict silently.
    """

    if isinstance(data, Enum):
        return data.value

    elif is_mapping(data):
        return _reconstruct_mapping(data, enum_to_value, enum_to_value)

    elif is_container(data):
        return _reconstruct(data, enum_to_value)

    else:
        return data


@overload
def value_to_enum(
    values: Mapping[_KT, _VT],
    enum_classes: NestedContainer[Type[_EnumT]],
    map_resolve_type: Literal["k", "K"],
    ) -> Mapping[Union[_KT, _EnumT], _VT]: ...
@overload
def value_to_enum(
    values: Mapping[_KT, _VT],
    enum_classes: NestedContainer[Type[_EnumT]],
    map_resolve_type: Literal["v", "V"] = "v",
    ) -> Mapping[_KT, Union[_EnumT, _VT]]: ...
@overload
def value_to_enum(
    values: 'Container[ _T]',
    enum_classes: NestedContainer[Type[_EnumT]],
    ) -> 'Container[Union[_EnumT, _T]]': ...
@overload
def value_to_enum(
    values: _T,
    enum_classes: NestedContainer[Type[_EnumT]],
    ) -> Union[_EnumT, _T]: ...
def value_to_enum(
    values: Any,
    enum_classes: NestedContainer[Type[_EnumT]],
    map_resolve_type = "v"
    ):
    """Recursively replace raw values with their matching enum member,
    wherever one of `enum_classes` has a member with that value.

    `enum_map` is built once from every class's `_value2member_map_`, so
    later classes silently win over earlier ones on a value collision.
    Values with no matching member pass through unchanged -- best-effort,
    not validating.

    `map_resolve_type` picks which side of a mapping gets converted: `"k"`
    converts keys, `"v"` (default) converts values -- only one side per call.

    Containers and mappings keep their own type wherever possible; see
    _data_tools._reconstruct/_reconstruct_mapping for the exceptions -- a
    container that cannot be rebuilt is returned un-transformed with a
    warning, a mapping that cannot falls back to dict silently.

    The lookup is by value alone. An enum with unhashable member values
    raises on the `enum_map` build; one whose values collide with ordinary
    data in the structure converts that data too.
    """

    map_resolve_type = map_resolve_type.lower()

    if map_resolve_type not in ("v", "k"):
        raise ValidationError(f"map_resolve_type must be k or v not {map_resolve_type}")

    enum_map = {}

    for enum_cls in to_frozenset(iter_flat_cont(enum_classes)):
        enum_map.update(enum_cls._value2member_map_)

    def convert(v):
        if is_mapping(v):
            return _reconstruct_mapping(
                v,
                convert if map_resolve_type == "k" else None,
                convert if map_resolve_type == "v" else None
            )

        elif is_container(v):
            return _reconstruct(v, convert)

        return enum_map.get(v, v)

    return convert(values)

def clean_none_values(data: _T) -> _T:
    """Remove every None from `data`, recursively, keeping its shape.

    A mapping loses the whole entry whose *value* is None (keys are never
    judged); a container loses the item itself. Recurses, and an entry that
    ends up an empty container after cleaning is kept -- empty is not None.

    What comes back is the same type wherever possible; see
    _data_tools._reconstruct/_reconstruct_mapping. A namedtuple is the shape
    this bites: dropping a field leaves it un-buildable, so it comes back
    whole -- None included -- with a warning, rather than as some other,
    shortened type.

    Anything that is not a container is returned as it is -- including a
    bare None. Callers wanting "None or nothing" should test the value
    itself rather than expect this to answer for it.
    """

    if is_mapping(data):
        return _reconstruct_mapping(data, value_func=_none_cleaner)

    elif is_container(data):
        return _reconstruct(data, _none_cleaner)

    return data

def clean_none_kw(**kwargs) -> Dict[str, Any]:
    """clean_none_values over keyword arguments, for building a call's kwargs.

    The shape this exists for is forwarding optional arguments onward without
    a chain of `if x is not None` around every one of them:

        client.request(**clean_none_kw(limit=limit, offset=offset))

    An argument left at None disappears instead of being passed as None, so
    the callee sees its own default rather than an override that means
    "unset". Nested values are cleaned too, since it is clean_none_values
    doing the work.
    """

    return clean_none_values(kwargs)

def get_nested_dict_value(dct: NestedStrKeyDict[_T], path: str, sep: str = ".") -> _T:
    """Walk `dct` down a `sep`-joined path of keys and return what is there.

        get_nested_dict_value({"a": {"b": 1}}, "a.b")   ->  1

    Deliberately not forgiving: a missing key raises KeyError naming that key,
    and a path that runs into a non-mapping raises TypeError. Both say which
    step failed, which a `.get()` chain returning None does not -- and None is
    itself a legitimate stored value, so there is no default that could be
    told apart from a real one. Wrap the call if a default is what you want.

    `sep` is what splits the path, so a key containing a dot needs a different
    one. There is no escaping.
    """

    for key in path.split(sep):
        dct = dct[key]
    return dct

def get_nested_dict_key(path_dct: NestedStrKeyDict[Literal[True, 1]], sep: str = ".") -> str:
    """Inverse of get_nested_dict_value(): given a single-branch nested dict
    that marks one path with a leaf of `True`/`1` (e.g. `{"a": {"b": True}}`),
    return that path joined by `sep` (`"a.b"`).

    NOTE: the leaf-value check below (`value != 1: value = value.numerator`)
    only rejects non-numeric leaves -- `.numerator` raises AttributeError for
    those, but for any *other* number (e.g. a leaf of `2`) `.numerator`
    succeeds and its result is discarded, so an invalid leaf like `2` is
    silently accepted instead of rejected. This looks like leftover/incomplete
    validation rather than intended behavior; flagging here rather than
    silently treating it as correct.
    """

    def flatten(current_dict: NestedStrKeyDict[Literal[True, 1]], current_path: str = "") -> Tuple[str, Literal[1]]:
        key, value = next(iter(current_dict.items()))

        new_path = f"{current_path}{sep}{key}" if current_path else key

        if isinstance(value, dict):
            return flatten(value, new_path)

        if value != 1:
            value = value.numerator

        return new_path

    if len(path_dct) != 1:
        raise TypeError(f"len nested dict must be 1 not {len(path_dct)}")

    return flatten(path_dct)


@_optional_import(("jsonref", "jsonref"))
def resolve_json_refs(content: JsonValue, **kw) -> JsonValue:
    """Replace every `$ref` inside an already-parsed JSON structure.

    files_tools.load_ref_json is the same thing for a file on disk; this is
    for a document already in memory -- one that arrived over the network, or
    was assembled in code.

    Two of jsonref's defaults are reversed, and both for the same reason: what
    comes back should behave like ordinary data rather than like jsonref.
    `proxies=False` substitutes the real object in place of a lazy proxy, so
    `isinstance`, `==` and json.dumps all see what they expect, and
    `lazy_load=False` resolves everything now, so a broken ref fails here
    instead of somewhere later that has forgotten where the document came
    from. Pass either explicitly to get jsonref's own behaviour back.

    A relative `$ref` has nothing to resolve against unless `base_uri` is
    given -- there is no file for it to be relative to. Needs the `jsonref`
    extra.
    """

    kw.setdefault("proxies", False)
    kw.setdefault("lazy_load", False)
    return jsonref.replace_refs(content, **kw)


__all__ = (
    "enum_to_value",
    "clean_none_values",
    "value_to_enum",
    "clean_none_kw",
    "get_nested_dict_value",
    "get_nested_dict_key",
    "resolve_json_refs",

)
