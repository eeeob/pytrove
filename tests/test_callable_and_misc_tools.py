import pytest

from pytrove import safe_call, raise_if, to_coroutine, set_func_attrs, juxt
from pytrove import generate_secret, patch_cls


def test_safe_call_returns_result_on_success():
    assert safe_call(lambda x: x + 1, 1) == 2


def test_safe_call_swallows_exception_by_default():
    assert safe_call(lambda: 1 / 0) is None


def test_safe_call_return_exc():
    result = safe_call(lambda: 1 / 0, return_exc=True)
    assert isinstance(result, ZeroDivisionError)


def test_raise_if_bool_value_sync():
    @raise_if(ValueError, bool_value=False)
    def check(x):
        return x

    assert check(True) is True
    with pytest.raises(ValueError):
        check(False)


def test_raise_if_values_set_sync():
    @raise_if(ValueError, values=[None, "banned"])
    def check(x):
        return x

    assert check("ok") == "ok"
    with pytest.raises(ValueError):
        check("banned")


async def test_raise_if_async():
    @raise_if(ValueError, bool_value=False)
    async def check(x):
        return x

    assert await check(True) is True
    with pytest.raises(ValueError):
        await check(False)


async def test_to_coroutine_wraps_sync_function():
    coro_func = to_coroutine(lambda x, y: x + y)
    result = await coro_func(2, 3)
    assert result == 5


def test_set_func_attrs_as_decorator():
    @set_func_attrs(tag="hello")
    def f():
        pass

    assert f.tag == "hello"


def test_set_func_attrs_direct_call():
    def f():
        pass

    result = set_func_attrs(f, tag="direct")
    assert result is f
    assert f.tag == "direct"


def test_generate_secret_length_and_charset():
    secret = generate_secret(16)
    assert len(secret) == 16


def test_generate_secret_rejects_non_positive_length():
    with pytest.raises(ValueError):
        generate_secret(0)


def test_generate_secret_rejects_no_charset():
    with pytest.raises(ValueError):
        generate_secret(8, use_upper=False, use_lower=False, use_digits=False, use_symbols=False)


def test_generate_secret_only_digits():
    secret = generate_secret(10, use_upper=False, use_lower=False, use_symbols=False)
    assert secret.isdigit()
    assert len(secret) == 10


def test_patch_cls_merges_methods_into_base():
    class Base:
        def greet(self):
            return "base"

    class Patch(Base):
        def greet(self):
            return "patched"

    patch_cls(Patch)
    assert Base().greet() == "patched"


def test_patch_cls_requires_single_base():
    with pytest.raises(TypeError):
        class Multi:
            pass

        @patch_cls
        class BadPatch(Multi, dict):
            pass


def test_juxt_fans_one_call_across_every_function():
    assert juxt(str.upper, str.lower, len)("Ab") == ("AB", "ab", 2)


def test_juxt_passes_through_args_and_kwargs():
    fanned = juxt(
        lambda a, b, c=0: a + b + c,
        lambda a, b, c=0: a * b * (c or 1),
    )
    assert fanned(2, 3, c=4) == (9, 24)


def test_juxt_with_no_functions_returns_an_empty_tuple():
    assert juxt()(1, 2, 3) == ()


def test_juxt_result_is_reusable():
    fanned = juxt(len, lambda s: s[0])
    assert fanned("abc") == (3, "a")
    assert fanned("xy") == (2, "x")


def test_juxt_does_not_swallow_a_raising_function():
    with pytest.raises(ZeroDivisionError):
        juxt(len, lambda _: 1 / 0)("abc")
