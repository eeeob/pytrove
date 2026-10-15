"""Object and class utilities, re-exported flat from one place."""

from __future__ import annotations as _annotations

from . import descriptors, patching, proxies, registry
from .descriptors import *
from .patching import *
from .proxies import *
from .registry import *

__all__ = (
    *patching.__all__,
    *descriptors.__all__,
    *registry.__all__,
    *proxies.__all__,
)
