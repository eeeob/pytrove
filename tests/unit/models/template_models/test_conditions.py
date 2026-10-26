from __future__ import annotations as _annotations

from collections import ChainMap

import pytest

from pytrove.models import CompiledConditional, CompiledDefaults


def test_defaults_sit_beneath_the_passed_values() -> None:
    merged = CompiledDefaults({"a": 0, "b": 2}).with_defaults({"a": 1})
    assert isinstance(merged, ChainMap)
    assert dict(merged) == {"a": 1, "b": 2}


@pytest.mark.parametrize("defaults", [None, {}])
def test_with_defaults_returns_kw_itself_without_defaults(defaults: dict | None) -> None:
    kw = {"a": 1}
    assert CompiledDefaults(defaults).with_defaults(kw) is kw


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        (None, None),
        ([], None),
        (frozenset(), None),
        ("c", frozenset({"c"})),
        (["a", "b"], frozenset({"a", "b"})),
        (frozenset({"a"}), frozenset({"a"})),
    ],
)
def test_conditional_normalises_its_keys(keys: object, expected: frozenset | None) -> None:
    part = CompiledConditional(any_of=keys, all_of=keys)
    assert part.any_of == expected
    assert part.all_of == expected


def test_conditional_post_init_sets_up_the_field_meta() -> None:
    CompiledConditional(any_of=["a"])
    assert "__public_field_names__" in vars(CompiledConditional)
    assert CompiledConditional.__public_field_names__ == ["default_keys", "any_of", "all_of"]


def test_conditional_checks_its_keys() -> None:
    part = CompiledConditional(any_of=["a", "b"], all_of="c")
    assert part.can_format({"a": 1, "c": 1})
    assert not part.can_format({"a": 1})
    assert not part.can_format({"c": 1})
    assert CompiledConditional().can_format({})


def test_a_key_holding_none_counts_as_present() -> None:
    assert CompiledConditional(all_of=["a"]).can_format({"a": None})
    assert CompiledConditional(any_of=["a"]).can_format({"a": None})


def test_keys_filled_by_the_defaults_satisfy_the_conditions() -> None:
    part = CompiledConditional(default_keys={"a": 1}, all_of=["a"], any_of=["a", "b"])
    assert not part.can_format({})
    assert part.can_format(part.with_defaults({}))
