from __future__ import annotations as _annotations

from collections import ChainMap

from pytrove.models import CompiledConditional, CompiledDefaults


def test_defaults_sit_beneath_the_passed_values() -> None:
    assert CompiledDefaults().with_defaults({"a": 1}) == {"a": 1}
    merged = CompiledDefaults({"a": 0, "b": 2}).with_defaults({"a": 1})
    assert isinstance(merged, ChainMap)
    assert dict(merged) == {"a": 1, "b": 2}


def test_conditional_normalises_and_checks_its_keys() -> None:
    part = CompiledConditional(any_of=["a", "b"], all_of="c")
    assert part.any_of == frozenset({"a", "b"}) and part.all_of == frozenset({"c"})
    assert CompiledConditional(any_of=[]).any_of is None

    assert part.can_format({"a": 1, "c": 1})
    assert not part.can_format({"a": 1})
    assert not part.can_format({"c": 1})
    assert CompiledConditional().can_format({})
