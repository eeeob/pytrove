import pytest
from pytrove.misc_tools import walk_subclasses
from pytrove import generate_secret, patch_cls


def test_walk_subclasses_yields_a_diamond_once():
    class Base: ...
    class Left(Base): ...
    class Right(Base): ...
    class Bottom(Left, Right): ...

    names = [c.__name__ for c in walk_subclasses(Base)]

    assert sorted(names) == ["Bottom", "Left", "Right"]


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
