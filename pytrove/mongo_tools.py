"""A MongoDB index model that compares by value."""

from __future__ import annotations as _annotations

import sys
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from collections.abc import Hashable

# Importable is not enough: a release older than the extra allows may be installed outside it.
HAS_PYMONGO = HAS_PYMONGO and _has_requirement("mongo", "pymongo")

if HAS_PYMONGO:

    class MongoIndex(IndexModel):
        """A `pymongo.IndexModel` that hashes and compares by its definition.

        The definition is the key, in order, and every option, name included,
        in any order.
        """

        @classmethod
        def from_dict(cls, dct: Mapping[str, Any]) -> Self:
            """Build an index from an index document, such as one `list_indexes()` yields.

            A `name` in the document is kept. An `index_information()` entry has
            none, since its name is the outer key: pass `{**info, "name": name}`,
            or the default name applies.

            Args:
                dct: The index document, left unchanged; `v` is dropped and
                    `key` is required. A dict or a list of `(field, direction)`
                    pairs works as the key.

            Returns:
                The index.
            """
            options = {k: v for k, v in dct.items() if k not in {"v", "key"}}
            return cls(dct["key"], **options)

        @property
        def name(self) -> str:
            """The index's name."""
            return self.document["name"]

        @property
        def key(self) -> str:
            """The indexed field names, joined by `_`."""
            return "_".join(self.document["key"].keys())

        def _definition(self) -> tuple[Hashable, ...]:
            """Return the definition in a form that ignores the order of the options.

            Returns:
                The key pairs in order, then the options as a set of `(name, value)` pairs.
            """
            options = frozenset(
                (k, self._normalise(v)) for k, v in self.document.items() if k != "key"
            )
            return tuple(self.document["key"].items()), options

        @staticmethod
        def _normalise(value: Any) -> Hashable:
            """Turn an option value into a hashable form that a server copy matches.

            The server returns a nested document as a `SON`, so any mapping
            becomes its items, in order, and any list or tuple a tuple.

            Args:
                value: The option value.

            Returns:
                The value, with every mapping and sequence in it made a tuple.
            """
            if isinstance(value, Mapping):
                return tuple((k, MongoIndex._normalise(v)) for k, v in value.items())
            if isinstance(value, (list, tuple)):
                return tuple(MongoIndex._normalise(v) for v in value)
            return value

        def __hash__(self) -> int:
            """Hash the definition."""
            return hash(self._definition())

        def __eq__(self, other: object) -> bool:
            """Compare definitions.

            Args:
                other: The other index.

            Returns:
                Whether they define the same index.
            """
            if not isinstance(other, MongoIndex):
                return NotImplemented
            return self._definition() == other._definition()

else:
    MongoIndex = _unavailable_class("MongoIndex", "mongo")

__all__ = ("MongoIndex",)
