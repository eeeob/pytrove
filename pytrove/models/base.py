from __future__ import annotations

from typing import (
    Any, ClassVar,
    get_args, get_type_hints, get_origin
)

try:
    from typing import Self
except ImportError:  # Python < 3.11
    from typing_extensions import Self

from enum import EnumMeta as EnumType  # EnumType is only an alias for EnumMeta added in 3.11
from dataclasses import dataclass, fields, asdict, is_dataclass

from ..data_tools import clean_none_values, enum_to_value, value_to_enum
from ..iter_tools import to_frozenset, iter_flat_cont
    

import json



@dataclass
class BaseDataClass:
    """Dataclass base providing dict (de)serialization with two conventions:

      - a leading underscore on a field name (`_foo`) makes it "private": a
        `foo` property proxying to `_foo` is auto-generated, and to_dict()/
        from_dict() (but not the *_raw_dict variants) expose/accept it under
        the public `foo` name instead of `_foo`;
      - enum-typed fields (found anywhere in a field's type hint, including
        nested inside Optional/List/etc.) can be round-tripped between enum
        members and their raw values via `enums_to_values`/`values_to_enums`.

    All of this is computed once per subclass and cached as class attributes
    by _ensure_field_meta() -- see there for how fields/enums are discovered.
    """

    __public_field_names__: ClassVar[list[str]]
    __private_field_names__: ClassVar[list[str]]
    __raw_private_fields__: ClassVar[frozenset[str]]
    __enums_types__: ClassVar[frozenset[EnumType]]

    @classmethod
    def _ensure_field_meta(cls) -> None:
        """Compute and cache, once per subclass, which fields are public vs.
        private and which enum classes appear anywhere in the field
        annotations -- both to_dict()/from_dict() and the enum conversion in
        data_tools.value_to_enum()/enum_to_value() rely on this.

        Cached on `cls` itself via `"__public_field_names__" in vars(cls)`
        (not `hasattr`, which would also see an inherited base's cache) so
        each subclass gets its own metadata instead of silently reusing a
        parent's.

        `_deep_extract` walks a field's type hint recursively via
        get_origin()/get_args() to find every Enum class inside it -- so
        `SomeEnum | None`, `list[SomeEnum]`, `dict[str, SomeEnum]` etc. are
        all detected, not just a bare `SomeEnum` annotation.
        """

        if "__public_field_names__" in vars(cls):
            return

        if not is_dataclass(cls):
            raise TypeError(
                f"{cls.__name__} must be dataclass"
            )

        public = []
        private = []

        def _deep_extract(value):
            if isinstance(value, EnumType):
                yield value
            elif (origin := get_origin(value)) is not None:
                for a in (*(get_args(value) or ()), origin):
                    yield from _deep_extract(a)

        cls.__enums_types__ = to_frozenset(
            iter_flat_cont(
                _deep_extract(t)
                for t in get_type_hints(cls).values()
                )
            )

        for f in fields(cls):
            name = f.name
            pname = name.lstrip("_")

            if name.startswith("_"):
                private.append(pname)

                if not hasattr(cls, pname):
                    prop = property(
                        fget=lambda self, _n=name: getattr(self, _n),
                        fset=lambda self, value, _n=name: setattr(self, _n, value),
                        fdel=lambda self, _n=name: delattr(self, _n),
                    )

                    setattr(cls, pname, prop)

            else:
                public.append(name)

        cls.__raw_private_fields__ = frozenset(f"_{n}" for n in private)
        cls.__public_field_names__ = public
        cls.__private_field_names__ = private

    def __post_init__(self) -> None:
        # Guarantees the private-field property proxies (e.g. `.b` for `_b`) exist
        # as soon as an instance is created, without requiring to_dict/from_dict
        # to be called first. Subclasses that define their own __post_init__ must
        # call super().__post_init__() to keep this guarantee.
        self.__class__._ensure_field_meta()

    def to_raw_dict(
        self, 
        without_none_values: bool = False, 
        enums_to_values: bool = False, 
        ) -> dict[str, Any]:

        dct = asdict(self)

        if without_none_values:
            dct = clean_none_values(dct)
        if enums_to_values:
            dct = enum_to_value(dct)

        return dct

    def to_dict(
        self,
        without_none_values: bool = False,
        enums_to_values: bool = False,
        ) -> dict[str, Any]:

        self.__class__._ensure_field_meta()

        dct = (
            {name: getattr(self, name) for name in self.__class__.__public_field_names__} | 
            {name: getattr(self, name) for name in self.__class__.__private_field_names__}
        )

        if without_none_values:
            dct = clean_none_values(dct)
        if enums_to_values:
            dct = enum_to_value(dct)

        return dct
        
    @classmethod
    def from_raw_dict(
        cls, 
        data: dict, 
        without_none_values: bool = False,
        values_to_enums: bool = False,
        ) -> Self:

        cls._ensure_field_meta()

        _private = cls.__raw_private_fields__
        _public = cls.__public_field_names__
        data = {
            k: v for k, v in data.items() 
            if k in _private or k in _public
            }

        if without_none_values:
            data = clean_none_values(data)
        
        if values_to_enums and cls.__enums_types__:
            data = value_to_enum(data, cls.__enums_types__, "v")
        
        return cls(**data)
    
    @classmethod
    def from_dict(
        cls, 
        data: dict, 
        without_none_values: bool = False,
        values_to_enums: bool = False,
        ) -> Self:

        cls._ensure_field_meta()

        _private = cls.__private_field_names__
        _public = cls.__public_field_names__

        data = {
            k: v for k, v in data.items() 
            if k in _private or k in _public
            }

        for name in cls.__private_field_names__:
            if name in data:
                data[f"_{name}"] = data.pop(name)


        if without_none_values:
            data = clean_none_values(data)

        if values_to_enums and cls.__enums_types__:
            data = value_to_enum(data, cls.__enums_types__, "v")

        
        return cls(**data)
    
    def copy(self) -> Self:
        return self.__class__.from_raw_dict(self.to_raw_dict())
    
    def __str__(self):
        return json.dumps(self.to_dict(True, True), indent=4, ensure_ascii=False, default=str)



__all__ = (
    "BaseDataClass", 
)