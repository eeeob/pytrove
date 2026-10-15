from __future__ import annotations as _annotations

import logging
import math
from typing import TYPE_CHECKING

import pytest

from pytrove.enums import TimeUnit
from pytrove.errors import ValidationError
from pytrove.models._internal import _INV_PHI, _LoggerModel, _resolved_hints

if TYPE_CHECKING:
    from decimal import Decimal


class _Base:
    """Annotated with an importable type."""

    unit: TimeUnit


class _Child(_Base):
    """Adds an annotation naming a type imported only for type checking."""

    amount: Decimal
    count: int


def test_resolved_hints_skips_unresolvable_annotations() -> None:
    assert _resolved_hints(_Child) == {"unit": TimeUnit, "count": int}


def test_inv_phi_is_the_golden_ratio_step() -> None:
    assert math.isclose(_INV_PHI, (5**0.5 - 1) / 2)


def test_logger_model_resolves_the_logger() -> None:
    model = _LoggerModel(logger="pytrove.test.internal")
    assert model.resolve_logger() is logging.getLogger("pytrove.test.internal")
    assert model.logger is logging.getLogger("pytrove.test.internal")

    with pytest.raises(ValidationError):
        _LoggerModel(logger=object()).resolve_logger()
