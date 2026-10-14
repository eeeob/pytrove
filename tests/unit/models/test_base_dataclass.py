"""Regression tests for the BaseDataClass field-discovery ordering bug.

__init_subclass__ fires when the `class Foo(BaseDataClass):` statement
executes, i.e. BEFORE any decorator applied to Foo itself (like @dataclass)
runs. Discovering dataclass fields there silently sees an empty field list
for any subclass that ISN'T decorated with @dataclass(slots=True) (which
happens to rebuild the class and re-trigger the hook afterwards). Plain
`@dataclass` subclasses used to lose all field data silently:
to_dict() returned {} and from_dict() ignored every key.

These tests must pass identically for both slotted and non-slotted
subclasses, and regardless of whether an instance was created before
from_dict()/to_dict() is first called.
"""
from dataclasses import dataclass

from pytrove.models import BaseDataClass


@dataclass
class PlainModel(BaseDataClass):
    a: int = 1
    _b: int = 2


@dataclass(slots=True)
class SlottedModel(BaseDataClass):
    a: int = 1
    _b: int = 2


def test_plain_dataclass_field_discovery_not_empty():
    inst = PlainModel(a=10, _b=20)
    assert inst.to_dict() == {"a": 10, "b": 20}
    assert inst.to_raw_dict() == {"a": 10, "_b": 20}


def test_slotted_dataclass_field_discovery_not_empty():
    inst = SlottedModel(a=10, _b=20)
    assert inst.to_dict() == {"a": 10, "b": 20}
    assert inst.to_raw_dict() == {"a": 10, "_b": 20}


def test_plain_and_slotted_from_dict_roundtrip_identically():
    plain = PlainModel.from_dict({"a": 99, "b": 88})
    slotted = SlottedModel.from_dict({"a": 99, "b": 88})
    assert plain.to_dict() == {"a": 99, "b": 88}
    assert slotted.to_dict() == {"a": 99, "b": 88}


def test_from_dict_works_without_prior_instantiation():
    # Cold path: from_dict() must trigger field discovery itself, without
    # requiring an instance to have been created (via __post_init__) first.
    @dataclass
    class ColdModel(BaseDataClass):
        a: int = 1
        _b: int = 2

    result = ColdModel.from_dict({"a": 5, "b": 6})
    assert result.to_dict() == {"a": 5, "b": 6}


def test_private_field_property_proxy_available_after_construction():
    inst = PlainModel(a=1, _b=42)
    assert inst.b == 42
    inst.b = 100
    assert inst._b == 100


def test_copy_roundtrip():
    inst = PlainModel(a=1, _b=2)
    duplicate = inst.copy()
    assert duplicate is not inst
    assert duplicate.to_dict() == inst.to_dict()


def test_multi_level_inheritance_each_class_gets_its_own_fields():
    # Regression: a naive "already computed?" check based on hasattr() (which
    # walks the MRO) would make a subclass-of-a-subclass see its parent's
    # already-cached field list and skip discovering its own extra fields.
    @dataclass
    class Parent(BaseDataClass):
        x: int = 1

    @dataclass
    class Child(Parent):
        x: int = 1
        y: int = 2

    parent = Parent(x=10)
    assert parent.to_dict() == {"x": 10}

    child = Child(x=10, y=20)
    assert child.to_dict() == {"x": 10, "y": 20}


def test_without_none_values_and_enums_to_values():
    from enum import Enum

    class Status(Enum):
        OK = "ok"

    @dataclass
    class WithEnum(BaseDataClass):
        status: Status = Status.OK
        note: str = None

    inst = WithEnum()
    assert inst.to_dict(without_none_values=True, enums_to_values=True) == {
        "status": "ok"
    }


def test_base_dataclass_survives_an_unresolvable_annotation():
    @dataclass
    class Model(BaseDataClass):
        value: "NameThatIsNotImportableHere | None" = None

    Model._ensure_field_meta()

    assert Model.__enums_types__ == frozenset()
