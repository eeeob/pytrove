from __future__ import annotations as _annotations

import importlib.util
import sys
import types
import warnings
from collections import ChainMap
from types import MappingProxyType
from typing import is_typeddict

import pytest

from pytrove.models import CompiledEachLine, CompiledLine
from pytrove.models._internal import _to_enums
from pytrove.models.template_models import _internal
from pytrove.models.template_models._internal import (
    _CompiledButtonMeta,
    _CompiledEachButtonDict,
    _CompiledEachLineDict,
    _CompiledRichMessageDict,
    _CompiledTemplateDict,
    _chain_mappings,
    _check_each,
    _compile_lines,
    _copy_templates,
    _format_lines,
    _is_each_button,
    _is_each_line,
)


@pytest.mark.parametrize(
    ("shape", "required", "optional"),
    [
        (_CompiledButtonMeta, set(), {"style", "icon_custom_emoji_id"}),
        (_CompiledEachLineDict, {"each", "item"}, set()),
        (_CompiledEachButtonDict, {"each", "item"}, {"row_width"}),
        (
            _CompiledRichMessageDict,
            {"html", "markdown"},
            {"default_keys", "is_rtl", "skip_entity_detection"},
        ),
        (
            _CompiledTemplateDict,
            {"message", "buttons", "parse_mode", "rich_message", "key_time"},
            {"default_keys"},
        ),
    ],
)
def test_compiled_shapes_report_their_required_and_optional_keys_at_runtime(
    shape: type, required: set[str], optional: set[str]
) -> None:
    assert is_typeddict(shape)
    assert shape.__required_keys__ == required
    assert shape.__optional_keys__ == optional


@pytest.mark.parametrize("is_each", [_is_each_line, _is_each_button])
def test_is_each_needs_a_mapping_with_an_each_key(is_each: object) -> None:
    assert is_each({"each": "xs", "item": "x"})
    assert is_each(MappingProxyType({"each": "xs"}))
    # An empty or non-string `each` still marks a repeated part, which `_check_each` rejects.
    assert is_each({"each": "", "item": "x"})
    assert is_each({"each": 1, "item": "x"})
    assert not is_each({"text": "x"})
    assert not is_each("each")
    assert not is_each([{"each": "xs"}])


@pytest.mark.parametrize("each", ["", 1, None, ["xs"]])
def test_check_each_rejects_anything_but_a_non_empty_string(each: object) -> None:
    with pytest.raises(ValueError, match="each must name"):
        _check_each({"each": each})
    with pytest.raises(ValueError, match="each must name"):
        _check_each({})
    assert _check_each({"each": "xs"}) is None


def test_chain_mappings_layers_without_copying() -> None:
    first, second = {"a": 1}, MappingProxyType({"a": 0, "b": 2})
    chained = _chain_mappings(first, second)

    assert isinstance(chained, ChainMap)
    assert dict(chained) == {"a": 1, "b": 2}
    first["c"] = 3
    assert chained["c"] == 3
    assert dict(_chain_mappings()) == {}


def test_chain_mappings_writes_land_in_the_first_map() -> None:
    first, second = {"a": 1}, {"b": 2}
    chained = _chain_mappings(first, second)
    assert isinstance(chained, ChainMap)

    chained["b"] = 3
    assert first == {"a": 1, "b": 3}
    assert second == {"b": 2}


def test_compile_and_format_line_blocks() -> None:
    lines = _compile_lines(["a", {"text": "{b}", "any_of": ["b"]}, {"each": "xs", "item": "{x}"}])
    assert [type(line) for line in lines] == [CompiledLine, CompiledLine, CompiledEachLine]
    assert _format_lines(lines, {"xs": [{"x": 1}]}) == "a\n1"
    assert _compile_lines([]) is None and _compile_lines(None) is None
    assert _format_lines(None, {}) is None


def test_format_lines_is_none_when_every_line_opts_out() -> None:
    lines = _compile_lines([{"text": "x", "all_of": ["k"]}, {"text": "y", "any_of": ["k"]}])
    assert _format_lines(lines, {}) is None


@pytest.mark.parametrize("each", ["", 1])
def test_compile_lines_rejects_a_repeated_line_without_a_valid_each(each: object) -> None:
    with pytest.raises(ValueError, match="each must name"):
        _compile_lines([{"each": each, "item": "x"}])


@pytest.mark.parametrize("each", [None, "", 0])
def test_compile_lines_rejects_a_plain_line_with_a_falsy_each(each: object) -> None:
    with pytest.raises(ValueError, match="each must name"):
        _compile_lines([{"each": each, "text": "x"}])


def test_copy_templates_copies_only_what_compiling_reaches() -> None:
    shared = {"message": ["x"]}
    cycle: dict[str, object] = {"text": "x"}
    cycle["child"] = cycle
    templates = {
        "$defs": {"node": cycle},
        "parse_mode": "html",
        "a": shared,
        "b": shared,
        "group": {"nested": True, "inner": shared, "$skip": cycle, "scalar": 5},
        "flat": {"nested": False, "message": ["f"]},
    }

    copied = _copy_templates(templates)
    assert copied == {
        "a": shared,
        "b": shared,
        "group": {"inner": shared, "nested": True},
        "flat": {"nested": False, "message": ["f"]},
    }
    assert copied["a"] is not shared and copied["a"]["message"] is not shared["message"]
    assert copied["a"] is not copied["b"]
    assert copied["group"]["inner"] is not shared


def test_compiled_button_meta_converts_only_its_style() -> None:
    pyrogram_enums = pytest.importorskip("pyrogram.enums")
    button_style = getattr(pyrogram_enums, "ButtonStyle", None)

    if button_style is None:
        pytest.skip("the installed pyrogram has no ButtonStyle")

    meta = {"style": "danger", "icon_custom_emoji_id": "danger", "other": "danger"}
    assert _to_enums(meta, _CompiledButtonMeta) == {
        "style": button_style.DANGER,
        "icon_custom_emoji_id": "danger",
        "other": "danger",
    }


def test_button_style_falls_back_to_str_without_pyrogram_button_style(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "pyrogram.enums", types.ModuleType("pyrogram.enums"))
    name = "pytrove.models.template_models._internal_probe"
    spec = importlib.util.spec_from_file_location(name, _internal.__file__)
    assert spec is not None and spec.loader is not None
    probe = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, probe)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        spec.loader.exec_module(probe)

    assert probe.ButtonStyle is str
    # As `str`, the style is a plain string: nothing to convert, nothing raised.
    assert _to_enums({"style": "danger"}, probe._CompiledButtonMeta) == {"style": "danger"}
