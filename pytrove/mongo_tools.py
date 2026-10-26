"""A MongoDB index model that compares by value."""

from __future__ import annotations as _annotations

import sys
from typing import Any

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

try:
    from pymongo import IndexModel  # type: ignore[import-not-found]  # Optional: the `mongo` extra.
except ImportError:
    HAS_PYMONGO = False
else:
    HAS_PYMONGO = True

from ._internal import _has_requirement, _unavailable_class

# Importable is not enough: a release older than the extra allows may be installed outside it.
HAS_PYMONGO = HAS_PYMONGO and _has_requirement("mongo", "pymongo")

if HAS_PYMONGO:

    class MongoIndex(IndexModel):
        """A `pymongo.IndexModel` that hashes and compares by its definition."""

        @classmethod
        def from_dict(cls, dct: dict[str, Any]) -> Self:
            """Build an index from a document as `index_information()` lists it.

            Args:
                dct: The index document; `v` and `name` are dropped, `key` is required.

            Returns:
                The index.
            """
            dct.pop("v", None)
            dct.pop("name", None)
            return cls(dct.pop("key"), **dct)

        @property
        def name(self) -> str:
            """The index's name."""
            return self.document["name"]

        @property
        def key(self) -> str:
            """The indexed field names, joined by `_`."""
            return "_".join(self.document["key"].keys())

        def __hash__(self) -> int:
            """Hash the definition."""
            return hash(repr(self))

        def __eq__(self, other: object) -> bool:
            """Compare definitions.

            Args:
                other: The other index.

            Returns:
                Whether they define the same index.
            """
            if not isinstance(other, MongoIndex):
                return NotImplemented
            return repr(self) == repr(other)

else:
    MongoIndex = _unavailable_class("MongoIndex", "mongo")

__all__ = ("MongoIndex",)
