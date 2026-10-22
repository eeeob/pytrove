from __future__ import annotations as _annotations

from pytrove.models import CompiledEachLine, CompiledLine


def test_line_compiles_from_text_or_definition_and_honours_defaults() -> None:
    assert CompiledLine.compile("hi {name}").format({"name": "x"}) == "hi x"

    line = CompiledLine.compile({"text": "{a}{b}", "all_of": ["b"], "default_keys": {"b": "!"}})
    assert line.format({"a": "x"}) == "x!"
    assert CompiledLine.compile({"text": "{a}", "any_of": ["a"]}).format({}) is None


def test_each_line_renders_one_line_per_mapping_element() -> None:
    line = CompiledEachLine.compile(
        {"each": "items", "item": {"text": "{n} {sep}", "all_of": ["n"]}}
    )
    kw = {"sep": "-", "items": [{"n": 1}, "skip", {}, {"n": 2}]}

    assert line.format(kw) == "1 -\n2 -"
    assert line.format({"items": [{}]}) is None
    assert line.format({"items": 5}) is None
    assert line.format({}) is None


def test_lines_work_without_the_tg_extra() -> None:
    assert CompiledLine.compile("still works").format({}) == "still works"


def test_each_line_compile_rewrites_the_dict_in_place() -> None:
    raw = {"each": "xs", "item": "{x}"}
    line = CompiledEachLine.compile(raw)
    assert isinstance(raw["item"], CompiledLine)
    assert line.item is raw["item"]
