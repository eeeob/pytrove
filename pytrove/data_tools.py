from typing import Union, Dict, Any, Callable, Mapping, Literal, Optional, Tuple, Type, TypeVar, overload
from enum import Enum

from .typings import (
    _T, _KT, _VT, 
    _EnumT, 
    Container, NestedContainer, NestedContainerMappingValue, NestedStrKeyDict, JsonValue
)
from .errors import ValidationError
from .validate_tools import is_container, is_mapping
from .iter_tools import iter_flat_cont, to_frozenset
from ._optional import _optional_import
from ._data_tools import _MESS, _reconstruct, _reconstruct_mapping

try:
    import jsonref
except ImportError:
    pass


_R = TypeVar("_R")
_RK = TypeVar("_RK")


def _none_cleaner(v):
    """clean_none_values' per-value step: drop a None, recurse into the rest."""

    if v is None:
        return _MESS

    return clean_none_values(v)



@overload
def map_deep(
    data: Mapping[_KT, NestedContainerMappingValue[_KT, _VT]],
    func: Callable[[Union[_KT, _VT]], _R],
    ) -> Mapping[_R, NestedContainerMappingValue[_R, _R]]: ...
@overload
def map_deep(data: NestedContainer[_T], func: Callable[[_T], _R]) -> NestedContainer[_R]: ...
def map_deep(data, func):
    """`func`, applied to every leaf under `data` -- and, for a mapping, to
    every key too, not only its values -- keeping the same shape.

    snapshot, enum_to_value and to_int_deep (num_tools) are all this with
    `func` fixed to one thing -- the identity, an Enum's `.value`, to_int
    -- so each used to carry its own copy of the walk this now does once.
    Write the same kind of thing yourself by passing your own `func` here
    rather than another copy of it:

        map_deep(data, str.upper)
        map_deep(data, lambda v: v.strip() if isinstance(v, str) else v)

    Recursed with _data_tools._reconstruct/_reconstruct_mapping: a
    container or mapping that cannot be rebuilt as its own type is
    returned un-transformed (a warning names it) or falls back to a plain
    dict, respectively -- see that module for exactly which types fall
    which way. Both walk lazily, one item at a time, so a type whose
    constructor rejects its argument outright (range, defaultdict's
    factory position) never costs a single nested map_deep() call that
    goes on to be thrown away.

    Nothing about `func` is assumed beyond taking one value and returning
    one back -- what it does with a value that is itself a container is
    its own business, since this only ever calls it on what is_mapping and
    is_container both say no to. A `func` that raises is not caught here;
    it reaches the caller exactly as it left `func`.

    The two overloads split the same way iter_flat_map's do, mapping
    against plain container: a mapping offers `func` both its keys
    (`_KT`) and its values' own leaves (`_VT` -- NestedContainerMappingValue's
    leaf, not a nested value whole) and is typed back as `Mapping[_R,
    NestedContainerMappingValue[_R, _R]]` -- a key is always a bare `_R`,
    but a value that was itself nested stays nested, just with `_R` where
    `_KT`/`_VT` were; see _reconstruct_mapping for why `Mapping` -- not
    `Dict` -- is the most that can be promised for the mapping itself,
    since `data`'s own type is kept wherever possible and only a dict on the
    fallback path. Anything else follows `NestedContainer[_T]` in and
    `NestedContainer[_R]` back out the same way, `_T` alone covering the
    case where `data` is itself a bare leaf with nothing to recurse into.
    """

    def step(value):
        return map_deep(value, func)

    if is_mapping(data):
        return _reconstruct_mapping(data, step, step)

    elif is_container(data):
        return _reconstruct(data, step)

    else:
        return func(data)


@overload
def map_deep_kv(
    data: Mapping[_KT, NestedContainerMappingValue[_KT, _VT]],
    value_func: Callable[[_VT], _R],
    key_func: Callable[[_KT], _RK],
    ) -> Mapping[_RK, NestedContainerMappingValue[_RK, _R]]: ...
@overload
def map_deep_kv(
    data: Mapping[_KT, NestedContainerMappingValue[_KT, _VT]],
    value_func: Callable[[_VT], _R],
    key_func: None = None,
    ) -> Mapping[_KT, NestedContainerMappingValue[_KT, _R]]: ...
@overload
def map_deep_kv(
    data: NestedContainer[_T],
    value_func: Callable[[_T], _R],
    key_func: Optional[Callable[[Any], Any]] = None,
    ) -> NestedContainer[_R]: ...
def map_deep_kv(data, value_func, key_func=None):
    """map_deep, with a mapping's two sides given their own function instead
    of sharing one -- `value_func` for every value's own leaves, `key_func`
    for a key that is itself a leaf, defaulting to None, which leaves every
    key exactly as it was.

    value_to_enum is the reason this exists: its `map_resolve_type` picks
    one side of a mapping to convert, never both, because there was only
    ever one function to hand either side. This is that limitation lifted --
    pass both and both convert, in one pass, each through its own rule:

        map_deep_kv(data, str.upper, key_func=str.lower)

    `value_func` is the one this falls back to everywhere a plain container
    is involved, key or no key -- a container has items, not keys, so
    key_func has nothing to apply to inside one. Concretely: a mapping's
    *keys* go through key_func only when a key is a bare leaf; a key that is
    itself a container (a tuple, most commonly -- a mapping cannot be one,
    since mappings are not hashable) is rebuilt with value_func applied to
    its own items instead, the same as any other container this walks.
    Every value, whatever shape it turns out to be -- leaf, plain container,
    or a nested mapping with its own keys and values -- recurses back through
    map_deep_kv itself, so a nested mapping reached through a value keeps
    splitting key_func/value_func the same way at every depth.

    Reconstruction is _data_tools._reconstruct/_reconstruct_mapping, exactly
    as map_deep uses it -- same laziness, same un-transformed-with-warning /
    plain-dict fallbacks. See map_deep for what that means in full; this only
    changes which function a given leaf is offered.
    """

    def key_step(key):
        if is_container(key):
            return _reconstruct(key, value_step)

        return key_func(key) if key_func is not None else key

    def value_step(value):
        return map_deep_kv(value, value_func, key_func)

    if is_mapping(data):
        return _reconstruct_mapping(data, key_step, value_step)

    elif is_container(data):
        return _reconstruct(data, value_step)

    else:
        return value_func(data)


def snapshot(data: _T) -> _T:
    """map_deep with the identity as `func` -- a copy of `data` in a
    structure of the same shape that shares nothing mutable with it,
    since nothing under it was changed, only rebuilt.

    A key is walked exactly as a value is here, not skipped -- see
    map_deep. A key that is itself a container (a tuple, most commonly)
    comes back a fresh, equal one rather than the same object, the same
    as any other container this walks; one that is not comes back exactly
    as it was, since there was nothing under it to rebuild. Either way,
    nothing under `data` keeps its old identity -- which is the point --
    and a key has to be hashable to begin with, so it can never hide a
    mutable dict or list this exists to decouple `data` from.
    """

    return map_deep(data, lambda value: value)


def enum_to_value(data: _T) -> _T:
    """map_deep with a `func` that reads off an Enum member's `.value` and
    leaves anything else exactly as it was -- the inverse of value_to_enum,
    and the step that makes a structure serialisable: an Enum member is
    not JSON, and `.value` is what it was standing for. Both sides of a
    mapping are converted, `.value` included as a key -- see map_deep for
    what "converted" means for a type that cannot be rebuilt as its own.
    """

    return map_deep(data, lambda value: value.value if isinstance(value, Enum) else value)


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
    "snapshot",
    "map_deep",
    "map_deep_kv",
    "enum_to_value",
    "clean_none_values",
    "value_to_enum",
    "clean_none_kw",
    "get_nested_dict_value",
    "get_nested_dict_key",
    "resolve_json_refs",

)
