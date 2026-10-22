from __future__ import annotations as _annotations

import importlib.util

import pytest

from pytrove.models import CompiledButton, CompiledButtonRow, CompiledEachButton

HAS_PYROGRAM = importlib.util.find_spec("pyrogram") is not None
needs_pyrogram = pytest.mark.skipif(not HAS_PYROGRAM, reason="needs the tg extra")


def _button(text: str = "{name}", **extra: object) -> dict[str, object]:
    """Return a callback button definition."""
    return {"text": text, "type": "callback_data", "value": "id:{name}", **extra}


@needs_pyrogram
def test_button_renders_and_rejects_bad_types() -> None:
    from pyrogram.enums import ButtonStyle  # noqa: PLC0415 - optional `pyrogram`, present only when `needs_pyrogram` lets the test run

    button = CompiledButton.compile(_button(meta={"style": ButtonStyle.DANGER.value}))
    assert button.meta == {"style": ButtonStyle.DANGER}
    rendered = button.format({"name": "a"})
    assert (rendered.text, rendered.callback_data, rendered.style) == ("a", "id:a", ButtonStyle.DANGER)
    assert CompiledButton.compile(_button(all_of=["x"])).format({"name": "a"}) is None
    assert "url" in CompiledButton._buttons_params

    with pytest.raises(ValueError, match="Unsupported"):
        CompiledButton(text="t", type="nope", value="v").format({})

    with pytest.warns(UserWarning, match="unknown"):
        assert CompiledButton.compile(_button(meta={"unknown": 1})).format({"name": "a"}) is not None


@needs_pyrogram
def test_each_button_wraps_rows_and_button_row_drops_hidden_buttons() -> None:
    each = CompiledEachButton.compile({"each": "people", "item": _button(), "row_width": 2})
    rows = each.format({"people": [{"name": n} for n in "abc"] + ["skip"]})
    assert [[b.text for b in row] for row in rows] == [["a", "b"], ["c"]]
    assert each.format({"people": []}) is None
    assert each.format({"people": 5}) is None
    conditional = CompiledEachButton.compile({"each": "people", "item": _button(all_of=["name"])})
    assert conditional.format({"people": [{"other": 1}]}) is None
    assert CompiledEachButton.DEFAULT_ROW_WIDTH == 2

    row = CompiledButtonRow.compile(_button())
    assert [b.text for b in row.format({"name": "z"})] == ["z"]
    hidden = CompiledButtonRow.compile([_button(any_of=["x"])])
    assert hidden.format({"name": "z"}) is None


@pytest.mark.skipif(HAS_PYROGRAM, reason="checks the error raised without the tg extra")
def test_button_format_needs_the_tg_extra() -> None:
    with pytest.raises(ImportError, match="pytrove\\[tg\\]"):
        CompiledButton(text="t", type="url", value="v").format({})


@needs_pyrogram
def test_each_button_compile_rewrites_the_dict_in_place() -> None:
    raw = {"each": "xs", "item": {"text": "t", "type": "url", "value": "v"}}
    button = CompiledEachButton.compile(raw)
    assert isinstance(raw["item"], CompiledButton)
    assert button.item is raw["item"]
