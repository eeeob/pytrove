from __future__ import annotations as _annotations


import pytest

from pytrove.models import CompiledButton, CompiledButtonRow, CompiledEachButton
from pytrove.models.template_models.template import HAS_PYROGRAM

needs_pyrogram = pytest.mark.skipif(not HAS_PYROGRAM, reason="needs the tg extra")
without_pyrogram = pytest.mark.skipif(
    HAS_PYROGRAM, reason="checks the error raised without the tg extra"
)


def _button(text: str = "{name}", **extra: object) -> dict[str, object]:
    """Return a callback button definition."""
    return {"text": text, "type": "callback_data", "value": "id:{name}", **extra}


def _texts(rows: list[list[object]] | None) -> list[list[str]] | None:
    """Return the labels of rendered rows."""
    return None if rows is None else [[b.text for b in row] for row in rows]


@needs_pyrogram
def test_button_renders_and_restores_meta_enums() -> None:
    from pyrogram.enums import ButtonStyle  # noqa: PLC0415 - optional `pyrogram`, present only when `needs_pyrogram` lets the test run

    button = CompiledButton.compile(_button(meta={"style": ButtonStyle.DANGER.value}))
    assert button.meta == {"style": ButtonStyle.DANGER}
    rendered = button.format({"name": "a"})
    assert (rendered.text, rendered.callback_data, rendered.style) == (
        "a",
        "id:a",
        ButtonStyle.DANGER,
    )
    assert CompiledButton.compile(_button(all_of=["x"])).format({"name": "a"}) is None


@needs_pyrogram
def test_button_compile_converts_only_the_meta_style() -> None:
    from pyrogram.enums import ButtonStyle  # noqa: PLC0415 - optional `pyrogram`, present only when `needs_pyrogram` lets the test run

    meta = {"switch_inline_query": "link", "style": "danger"}
    button = CompiledButton.compile(_button(meta=meta))
    assert button.meta == {"switch_inline_query": "link", "style": ButtonStyle.DANGER}
    assert type(button.meta["switch_inline_query"]) is str
    assert meta["style"] == "danger"
    assert CompiledButton.compile(_button(meta={"x": "link"})).meta == {"x": "link"}


@needs_pyrogram
def test_button_compile_converts_only_meta_to_enums() -> None:
    button = CompiledButton.compile(
        {
            "text": "danger",
            "type": "callback_data",
            "value": "primary",
            "all_of": ["link"],
            "default_keys": {"s": "success"},
        }
    )
    assert (button.text, button.value) == ("danger", "primary")
    assert type(button.text) is str and type(button.value) is str
    assert button.all_of == frozenset({"link"})
    assert button.default_keys == {"s": "success"}
    assert type(button.default_keys["s"]) is str

    rendered = button.format({"link": 1})
    assert (rendered.text, rendered.callback_data) == ("danger", "primary")
    assert CompiledButton.compile(_button("{s}", default_keys={"s": "success"})).format(
        {"name": "n"}
    ).text == ("success")


@needs_pyrogram
def test_button_renders_a_url_button_and_applies_defaults_first() -> None:
    button = CompiledButton.compile(
        {
            "text": "{name}",
            "type": "url",
            "value": "https://x/{name}",
            "all_of": ["name"],
            "default_keys": {"name": "d"},
        }
    )
    rendered = button.format({})
    assert (rendered.text, rendered.url, rendered.callback_data) == ("d", "https://x/d", None)
    assert CompiledButton.compile(_button(meta=None)).meta is None
    assert CompiledButton(**_button(), meta=None).format({"name": "a"}).text == "a"


@needs_pyrogram
@pytest.mark.parametrize("button_type", ["nope", "text"])
def test_button_rejects_a_type_that_is_not_a_value_argument(button_type: str) -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        CompiledButton(text="t", type=button_type, value="v").format({})


@needs_pyrogram
def test_button_drops_unknown_and_colliding_meta_keys_with_a_warning() -> None:
    from pyrogram.enums import ButtonStyle  # noqa: PLC0415 - optional `pyrogram`, present only when `needs_pyrogram` lets the test run

    button = CompiledButton.compile(
        _button(meta={"unknown": 1, "text": "x", "callback_data": "y", "style": "primary"})
    )
    with pytest.warns(UserWarning, match="callback_data, text, unknown") as caught:
        rendered = button.format({"name": "a"})
    assert (rendered.text, rendered.callback_data, rendered.style) == (
        "a",
        "id:a",
        ButtonStyle.PRIMARY,
    )
    # The warning points at the caller, past the `_optional_import` wrapper.
    assert caught[0].filename == __file__


@needs_pyrogram
def test_buttons_params_is_cached() -> None:
    params = CompiledButton._buttons_params
    assert params[0] == "text"  # The label comes first, as the signature lists it.
    assert {"url", "callback_data"} <= set(params)
    assert CompiledButton._buttons_params is params


@needs_pyrogram
@pytest.mark.parametrize(
    ("row_width", "count", "expected"),
    [
        (None, 5, ["01", "23", "4"]),
        (1, 3, ["0", "1", "2"]),
        (2, 4, ["01", "23"]),
        (3, 4, ["012", "3"]),
        (3, 6, ["012", "345"]),
    ],
)
def test_each_button_wraps_rows_at_row_width(
    row_width: int | None, count: int, expected: list[str]
) -> None:
    definition = {"each": "people", "item": _button()}
    if row_width is not None:
        definition["row_width"] = row_width
    each = CompiledEachButton.compile(definition)
    rows = each.format({"people": [{"name": str(n)} for n in range(count)]})
    assert _texts(rows) == [list(row) for row in expected]


@needs_pyrogram
def test_each_button_hidden_and_non_mapping_elements_do_not_fill_a_row() -> None:
    each = CompiledEachButton.compile({"each": "people", "item": _button(all_of=["show"])})
    people = [{"name": "a", "show": 1}, {"name": "hidden"}, "skip", {"name": "b", "show": 1}]
    assert _texts(each.format({"people": people})) == [["a", "b"]]


@needs_pyrogram
def test_each_button_element_wins_over_kw() -> None:
    each = CompiledEachButton.compile({"each": "people", "item": _button()})
    assert _texts(each.format({"name": "outer", "people": [{"name": "inner"}, {}]})) == [
        ["inner", "outer"]
    ]


@needs_pyrogram
@pytest.mark.parametrize(
    "kw", [{}, {"people": []}, {"people": 5}, {"people": "ab"}, {"people": {"a": 1}}]
)
def test_each_button_renders_nothing_without_mapping_elements(kw: dict[str, object]) -> None:
    each = CompiledEachButton.compile({"each": "people", "item": _button()})
    assert each.format(kw) is None


def test_each_button_rejects_invalid_definitions() -> None:
    with pytest.raises(ValueError, match="each must name"):
        CompiledEachButton.compile({"each": "", "item": _button()})
    for row_width in (0, -1):
        with pytest.raises(ValueError, match="row_width must be at least 1"):
            CompiledEachButton.compile({"each": "xs", "item": _button(), "row_width": row_width})
    assert CompiledEachButton.DEFAULT_ROW_WIDTH == 2


@needs_pyrogram
def test_button_row_drops_hidden_buttons() -> None:
    row = CompiledButtonRow.compile(_button())
    assert [b.text for b in row.format({"name": "z"})] == ["z"]
    assert CompiledButtonRow.compile([_button(any_of=["x"])]).format({"name": "z"}) is None

    partial = CompiledButtonRow.compile([_button("a", any_of=["x"]), _button("b")])
    assert [b.text for b in partial.format({"name": "z"})] == ["b"]

    empty = CompiledButtonRow.compile([])
    assert empty.buttons == []
    assert empty.format({}) is None


@without_pyrogram
def test_button_parts_need_the_tg_extra() -> None:
    with pytest.raises(ImportError, match="pytrove\\[tg\\]"):
        CompiledButton(text="t", type="url", value="v").format({})
    with pytest.raises(ImportError, match="pytrove\\[tg\\]"):
        CompiledButton._buttons_params  # noqa: B018 - the property access is what raises
    with pytest.raises(ImportError, match="pytrove\\[tg\\]"):
        CompiledEachButton.compile({"each": "xs", "item": _button()}).format({"xs": [{}]})
    with pytest.raises(ImportError, match="pytrove\\[tg\\]"):
        CompiledButtonRow.compile(_button()).format({})


def test_each_button_compile_rewrites_the_dict_in_place() -> None:
    raw = {"each": "xs", "item": {"text": "t", "type": "url", "value": "v"}}
    button = CompiledEachButton.compile(raw)
    assert isinstance(raw["item"], CompiledButton)
    assert button.item is raw["item"]
