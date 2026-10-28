from __future__ import annotations as _annotations

import pytest

from pytrove.models import CompiledEachLine, CompiledLine


def test_line_compiles_from_text_or_definition_and_honours_defaults() -> None:
    assert CompiledLine.compile("hi {name}").format({"name": "x"}) == "hi x"

    line = CompiledLine.compile({"text": "{a}{b}", "all_of": ["b"], "default_keys": {"b": "!"}})
    assert line.format({"a": "x"}) == "x!"
    assert CompiledLine.compile({"text": "{a}", "any_of": ["a"]}).format({}) is None


def test_line_compile_drops_none_fields_and_needs_text() -> None:
    line = CompiledLine.compile({"text": "x", "all_of": None, "default_keys": None})
    assert (line.all_of, line.default_keys) == (None, None)

    with pytest.raises(TypeError, match="text"):
        CompiledLine.compile({"all_of": ["a"]})


def test_line_format_errors_and_escapes() -> None:
    with pytest.raises(KeyError, match="missing"):
        CompiledLine.compile("{missing}").format({})
    assert CompiledLine.compile("{{literal}} {a}").format({"a": 1}) == "{literal} 1"


def test_each_line_renders_one_line_per_mapping_element() -> None:
    line = CompiledEachLine.compile(
        {"each": "items", "item": {"text": "{n} {sep}", "all_of": ["n"]}}
    )
    kw = {"sep": "-", "items": [{"n": 1}, "skip", {}, {"n": 2}]}

    assert line.format(kw) == "1 -\n2 -"
    assert line.format({"items": [{}]}) is None
    assert line.format({"items": 5}) is None
    assert line.format({}) is None


def test_each_line_element_wins_over_kw_and_defaults_sit_beneath_both() -> None:
    line = CompiledEachLine.compile(
        {"each": "items", "item": {"text": "{n} {m}", "default_keys": {"n": "d", "m": "d"}}}
    )
    kw = {"n": "outer", "items": [{"n": "inner"}, {}]}
    assert line.format(kw) == "inner d\nouter d"


@pytest.mark.parametrize("each", ["ab", {"n": 1}])
def test_each_line_ignores_non_mapping_elements_of_a_str_or_dict(each: object) -> None:
    # A str yields characters and a dict its keys: neither element is a mapping.
    line = CompiledEachLine.compile({"each": "items", "item": "{n}"})
    assert line.format({"items": each}) is None


@pytest.mark.parametrize("each", ["", 1])
def test_each_line_compile_rejects_an_invalid_each(each: object) -> None:
    with pytest.raises(ValueError, match="each must name"):
        CompiledEachLine.compile({"each": each, "item": "x"})


def test_lines_work_without_the_tg_extra() -> None:
    assert CompiledLine.compile("still works").format({}) == "still works"


def test_each_line_compile_rewrites_the_dict_in_place() -> None:
    raw = {"each": "xs", "item": "{x}"}
    line = CompiledEachLine.compile(raw)
    assert isinstance(raw["item"], CompiledLine)
    assert line.item is raw["item"]
