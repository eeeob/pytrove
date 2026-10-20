"""The package version, read by `pyproject.toml` at build time."""

from __future__ import annotations as _annotations

from typing import Final

__version__: Final[str] = "1.1.2"
"""The released version; `[tool.hatch.version]` reads it with a pattern, so keep this line's shape."""

__all__ = ("__version__",)
