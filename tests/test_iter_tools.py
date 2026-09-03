from typing import Generic, Iterable, Iterator, TypeVar

from pytrove import (to_list, to_tuple, to_set, to_frozenset, flat_cont,
                     flat_cont_by, iter_flat_cont_by, flat_map,
                     iter_flat_map)

_T = TypeVar("_T")


def test_to_list_with_mapping_returns_keys():
    assert to_list({"a": 1, "b": 2}) == ["a", "b"]


def test_to_tuple_preserves_order():
    assert to_tuple([3, 1, 2]) == (3, 1, 2)


def test_to_set_deduplicates():
    assert to_set([1, 1, 2, 2, 3]) == {1, 2, 3}


def test_to_frozenset_is_immutable_type():
    result = to_frozenset([1, 2])
    assert isinstance(result, frozenset)


def test_flat_cont_ignores_none_entries():
    assert flat_cont([1, None, 2, None, [3, None]]) == [1, 2, 3]


def test_flat_cont_deeply_nested():
    nested = [1, [2, [3, [4, [5]]]]]
    assert flat_cont(nested) == [1, 2, 3, 4, 5]


def test_flat_cont_treats_strings_as_atomic():
    # str is explicitly excluded from Container (NotContainer), so it must
    # not be exploded into individual characters.
    assert flat_cont(["ab", ["cd"]]) == ["ab", "cd"]


def test_flat_cont_multiple_container_args():
    assert flat_cont([1, 2], [3, 4], None) == [1, 2, 3, 4]


def test_flat_cont_keeps_none_when_asked():
    assert flat_cont([1, None, 2, [3, None]], exclude_none=False) == [1, None, 2, 3, None]


def test_flat_cont_excludes_none_by_default():
    # The default is the long-standing behaviour, unchanged by adding the
    # option to keep None.
    assert flat_cont([1, None, 2]) == [1, 2]


class _Box(Generic[_T], Iterable[_T]):
    """A container the built-in is_container does not recognise -- it is
    not a Collection, an Iterator, a Sequence or a Mapping, so it can only
    be unwrapped by a caller-supplied predicate.

    Generic with a typed __iter__ on purpose: that is what lets a type
    checker walk through it and land on the real element type. A class
    with a bare untyped __iter__ works identically at runtime and reads as
    Iterable[Any] statically.
    """

    def __init__(self, *items: _T):
        self.items = items

    def __iter__(self) -> Iterator[_T]:
        return iter(self.items)


def _is_box(x) -> bool:
    return isinstance(x, _Box)


def test_flat_cont_by_uses_the_given_predicate_instead_of_is_container():
    assert flat_cont_by(_Box(1, 2, [3, 4]), is_container=_is_box) == [1, 2, [3, 4]]


def test_flat_cont_by_applies_the_predicate_at_every_depth():
    nested = _Box(1, _Box(2, _Box(3)), 4)
    assert flat_cont_by(nested, is_container=_is_box) == [1, 2, 3, 4]


def test_flat_cont_by_ignores_what_the_default_predicate_would_have_unwrapped():
    # A plain list is not a _Box, so under this predicate it is a leaf --
    # the opposite of what flat_cont would do with it.
    assert flat_cont_by([1, [2, 3]], is_container=_is_box) == [[1, [2, 3]]]


def test_flat_cont_by_defaults_to_is_container():
    assert flat_cont_by([1, None, 2, [3, None]]) == [1, 2, 3]


def test_flat_cont_by_ignores_none_entries():
    assert flat_cont_by(_Box(1, None, 2), is_container=_is_box) == [1, 2]


def test_flat_cont_by_keeps_none_when_asked():
    assert flat_cont_by(_Box(1, None, 2), is_container=_is_box, exclude_none=False) == [1, None, 2]


def test_iter_flat_cont_by_is_a_generator():
    result = iter_flat_cont_by(_Box(1, 2), is_container=_is_box)
    assert list(result) == [1, 2]
    assert list(result) == []  # exhausted, like any generator


def test_flat_cont_by_accepts_a_type_guard_predicate():
    # TypeGuard/TypeIs return types are subtypes of bool, so a narrowing
    # predicate is accepted wherever a plain bool one is -- and neither
    # changes what the element type is inferred to be.
    from pytrove.validate_tools import TypeIs

    def is_box(x) -> "TypeIs[_Box]":
        return isinstance(x, _Box)

    assert flat_cont_by(_Box(1, _Box(2, 3)), is_container=is_box) == [1, 2, 3]


def test_a_narrowing_predicate_really_does_stop_at_the_first_layer():
    # The runtime half of the caveat in the docstring: a predicate that
    # refuses what is_container would have taken leaves the inner
    # structure whole, whatever a type checker reads the call as.
    nested = [1, [2, 3]]

    assert flat_cont_by(nested, is_container=_is_box) == [nested]


def test_flat_map_yields_both_keys_and_values():
    # flat_cont walks a mapping's keys alone -- iterating a dict does that,
    # and flat_cont has no special case for one. This is the special case:
    # both sides come out.
    assert flat_map({"a": 1, "b": 2}) == ["a", 1, "b", 2]


def test_flat_map_recurses_into_a_nested_mapping():
    assert flat_map({"a": {"b": 2}}) == ["a", "b", 2]


def test_flat_map_recurses_into_a_mapping_reached_through_a_container():
    assert flat_map([1, {"a": 2}, 3]) == [1, "a", 2, 3]


def test_flat_map_still_flattens_a_plain_container():
    assert flat_map([1, [2, 3], None]) == [1, 2, 3]


def test_iter_flat_map_is_a_generator():
    result = iter_flat_map({"a": 1})
    assert list(result) == ["a", 1]
    assert list(result) == []  # exhausted, like any generator


def test_flat_map_excludes_none_by_default():
    assert flat_map({"a": None, "b": 1}) == ["a", "b", 1]


def test_flat_map_keeps_none_when_asked():
    assert flat_map({"a": None, "b": 1}, exclude_none=False) == ["a", None, "b", 1]
