import pytest
from pytrove import (
    cc_from_rc,
    resolve_rc,
)
from pytrove.errors import ValidationError


def test_resolve_rc_returns_none_for_an_unknown_calling_code():
    assert resolve_rc(999999) is None


def test_cc_from_rc_raises_validation_error_for_an_invalid_region():
    with pytest.raises(ValidationError):
        cc_from_rc("zz")
