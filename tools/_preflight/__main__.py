"""Entry point for `python -m tools._preflight`, run from the repo root."""

from __future__ import annotations as _annotations

from .cli import main

raise SystemExit(main())
