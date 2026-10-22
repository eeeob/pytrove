from __future__ import annotations as _annotations

from collections import ChainMap
from types import MappingProxyType
from typing import is_typeddict

import pytest

from pytrove.models import CompiledEachLine, CompiledLine
from pytrove.models.template_models._internal import (
    _CompiledEachButtonDict,
    _CompiledEachLineDict,
    _CompiledRichMessageDict,
    _CompiledTemplateDict,
    _chain_mappings,
    _compile_lines,
    _format_lines,
    _is_each_button,
    _is_each_line,
)


@pytest.mark.parametrize(
    ("shape", "keys"),
    [
        (_CompiledEachLineDict, {"each", "item"}),
        (_CompiledEachButtonDict, {"each", "item", "row_width"}),
        (
            _CompiledRichMessageDict,
            {"default_keys", "html", "markdown", "is_rtl", "skip_entity_detection"},
        ),
        (
            _CompiledTemplateDict,
            {"default_keys", "message", "buttons", "parse_mode", "rich_message", "key_time"},
        ),
    ],
)
def test_compiled_shapes_are_typeddicts_with_the_raw_keys(shape: type, keys: set[str]) -> None:
    assert is_typeddict(shape)
    assert set(shape.__required_keys__) | set(shape.__optional_keys__) == keys


@pytest.mark.parametrize("is_each", [_is_each_line, _is_each_button])
def test_is_each_needs_a_mapping_with_a_truthy_each(is_each: object) -> None:
    assert is_each({"each": "xs", "item": "x"})
    assert is_each(MappingProxyType({"each": "xs"}))
    assert not is_each({"each": "", "item": "x"})
    assert not is_each({"text": "x"})
    assert not is_each("each")
    assert not is_each([{"each": "xs"}])


def test_chain_mappings_layers_without_copying() -> None:
    first, second = {"a": 1}, MappingProxyType({"a": 0, "b": 2})
    chained = _chain_mappings(first, second)

    assert isinstance(chained, ChainMap)
    assert dict(chained) == {"a": 1, "b": 2}
    first["c"] = 3
    assert chained["c"] == 3
    assert dict(_chain_mappings()) == {}


def test_compile_and_format_line_blocks() -> None:
    lines = _compile_lines(["a", {"text": "{b}", "any_of": ["b"]}, {"each": "xs", "item": "{x}"}])
    assert [type(line) for line in lines] == [CompiledLine, CompiledLine, CompiledEachLine]
    assert _format_lines(lines, {"xs": [{"x": 1}]}) == "a\n1"
    assert _compile_lines([]) is None and _compile_lines(None) is None
    assert _format_lines(None, {}) is None
