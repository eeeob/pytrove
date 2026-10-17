from __future__ import annotations as _annotations

import importlib.util
from collections import ChainMap
from types import MappingProxyType
from typing import is_typeddict

import pytest

from pytrove.models import CompiledButton, CompiledEachButton, CompiledEachLine, CompiledLine, CompiledRichMessage
from pytrove.models.template_models._internal import (
    _chain_mappings,
    _CompiledEachButtonDict,
    _CompiledEachLineDict,
    _CompiledRichMessageDict,
    _CompiledTemplateDict,
    _is_each_button,
    _is_each_line,
)

HAS_PYROGRAM = importlib.util.find_spec("pyrogram") is not None
needs_pyrogram = pytest.mark.skipif(not HAS_PYROGRAM, reason="needs the tg extra")


@pytest.mark.parametrize(
    ("shape", "keys"),
    [
        (_CompiledEachLineDict, {"each", "item"}),
        (_CompiledEachButtonDict, {"each", "item", "row_width"}),
        (_CompiledRichMessageDict, {"default_keys", "html", "markdown", "is_rtl", "skip_entity_detection"}),
        (_CompiledTemplateDict, {"default_keys", "message", "buttons", "parse_mode", "rich_message", "key_time"}),
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


def test_line_and_rich_message_compile_rewrite_the_dict_in_place() -> None:
    raw = {"each": "xs", "item": "{x}"}
    line = CompiledEachLine.compile(raw)
    assert isinstance(raw["item"], CompiledLine)
    assert line.item is raw["item"]

    raw_rich = {"html": ["a"]}
    rich = CompiledRichMessage.compile(raw_rich)
    assert raw_rich["markdown"] is None
    assert raw_rich["html"] == rich.html
    assert [type(line) for line in raw_rich["html"]] == [CompiledLine]


@needs_pyrogram
def test_each_button_compile_rewrites_the_dict_in_place() -> None:
    raw = {"each": "xs", "item": {"text": "t", "type": "url", "value": "v"}}
    button = CompiledEachButton.compile(raw)
    assert isinstance(raw["item"], CompiledButton)
    assert button.item is raw["item"]
