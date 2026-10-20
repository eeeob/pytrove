import asyncio
import inspect
import json
from dataclasses import dataclass
from datetime import timedelta

import pytest

from pytrove import (
    cc_from_rc,
    date_utc_3,
    format_exc_tree,
    raise_if,
    resolve_rc,
    rand_tg_device,
)
from pytrove.country_tools import get_countries_by_cc
from pytrove.enums import PlatformDevice
from pytrove.errors import ValidationError
from pytrove.data_tools import get_nested_dict_key
from pytrove.misc_tools import walk_subclasses
from pytrove.models import BaseDataClass, JsonContainer
from pytrove.tg_tools import fetch_tg_email_code
from pytrove.validate_tools import is_tg_bot_token
from pytrove._optional import _optional_import


@pytest.mark.parametrize("platform", list(PlatformDevice))
def test_rand_tg_device_works_for_every_platform(platform):
    device = rand_tg_device(platform)
    assert device.model and device.version


def test_format_exc_tree_terminates_on_a_context_cycle():
    a = ValueError("a")
    b = KeyError("b")
    a.__context__ = b
    b.__context__ = a

    assert format_exc_tree(a).count("└─") == 2


def test_date_utc_3_is_labelled_three_hours_ahead():
    value = date_utc_3(with_tzinfo=True)

    assert value.utcoffset() == timedelta(hours=3)


def test_walk_subclasses_yields_a_diamond_once():
    class Base: ...
    class Left(Base): ...
    class Right(Base): ...
    class Bottom(Left, Right): ...

    names = [c.__name__ for c in walk_subclasses(Base)]

    assert sorted(names) == ["Bottom", "Left", "Right"]


def test_raise_if_does_not_crash_on_an_unhashable_result():
    @raise_if(ValueError, values=[None])
    def returns_list():
        return [1]

    assert returns_list() == [1]


def test_base_dataclass_survives_an_unresolvable_annotation():
    @dataclass
    class Model(BaseDataClass):
        value: "NameThatIsNotImportableHere | None" = None

    Model._ensure_field_meta()

    assert Model.__enums_types__ == frozenset()


def test_json_container_delete_saves_removing_a_none_value(tmp_path):
    path = tmp_path / "store.json"
    container = JsonContainer(path)

    container.set("k", None, save_now=True)
    container.delete("k", save_now=True)

    assert json.loads(path.read_text(encoding="utf-8")) == {}


def test_get_nested_dict_key_rejects_an_invalid_leaf():
    with pytest.raises(TypeError):
        get_nested_dict_key({"a": {"b": 2}})


def test_get_nested_dict_key_accepts_true_and_one():
    assert get_nested_dict_key({"a": {"b": True}}) == "a.b"
    assert get_nested_dict_key({"a": {"b": 1}}) == "a.b"


def test_resolve_rc_returns_none_for_an_unknown_calling_code():
    assert resolve_rc(999999) is None


def test_cc_from_rc_raises_validation_error_for_an_invalid_region():
    with pytest.raises(ValidationError):
        cc_from_rc("zz")


def test_get_countries_by_cc_keeps_every_region_sharing_a_calling_code():
    assert len(get_countries_by_cc()[1]) > 1


def test_is_tg_bot_token_still_accepts_a_well_formed_token():
    assert is_tg_bot_token("123456:ABC")


def test_optional_import_keeps_coroutine_functions_as_coroutines():
    @_optional_import(("json", "json"))
    async def coro():
        return 1

    assert inspect.iscoroutinefunction(coro)


def test_optional_import_raises_on_await_when_the_package_is_missing():
    @_optional_import(("no_such_package_for_pytrove", "nope"))
    async def coro():
        return 1

    async def run():
        with pytest.raises(ImportError):
            await coro()

    asyncio.run(run())


async def test_fetch_tg_email_code_matches_a_six_digit_code(monkeypatch):
    async def fake_fetch(*args, **kwargs):
        yield "Hello Ali Hassan, your code is 123456"

    monkeypatch.setattr("pytrove.tg_tools.fetch_emails_from", fake_fetch)
    monkeypatch.setattr(
        "pytrove.tg_tools.detect_email_provider",
        lambda email: None,
    )

    assert await fetch_tg_email_code("a@gmail.com", "pw", "Ali Hassan", 6) == "123456"
