"""Data-structure helpers, re-exported flat from one place."""

from __future__ import annotations as _annotations

from . import mappings, nested, walk
from .mappings import *
from .nested import *
from .walk import *

__all__ = (
    *walk.__all__,
    *nested.__all__,
    *mappings.__all__,
)
