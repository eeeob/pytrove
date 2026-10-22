"""The base class every platform step derives from."""

from __future__ import annotations as _annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from .cache import Cache
    from .catalog import Catalog

# ============================== builders ==============================


class Builder(ABC):
    """One platform step.

    `key` is its `--only` name and `platform` is the catalog it writes; they
    are the same word today but are kept apart because `key` is a CLI token
    and `platform` is part of the data contract.
    """

    key: ClassVar[str]
    platform: ClassVar[str]

    def __init__(self, cache: Cache) -> None:
        """Keep the cache every source of this step is read through."""
        self.cache = cache

    @abstractmethod
    def build(self) -> list[Catalog]:
        """Produce every catalog this step owns."""

    def run(self) -> None:
        """Build every catalog this step owns and write it to disk."""
        for catalog in self.build():
            catalog.write()
