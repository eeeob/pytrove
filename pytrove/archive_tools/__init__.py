"""Archive helpers, re-exported flat from one place."""

from __future__ import annotations as _annotations

from . import compress, extract
from .compress import *
from .extract import *

__all__ = (
    *compress.__all__,
    *extract.__all__,
)
