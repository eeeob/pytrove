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


def test_parse_phone_normalises_to_e164():
    from pytrove import parse_phone

    assert parse_phone("00966 50-123-4567") == "+966501234567"
    assert parse_phone(966501234567) == "+966501234567"
    assert parse_phone("+966501234567", return_numobj=True).country_code == 966


def test_parse_phone_rejects_an_invalid_number():
    from pytrove import parse_phone

    with pytest.raises(ValidationError, match="Invalid PhoneNumber"):
        parse_phone("+123")


def test_code_conversions():
    from pytrove import cc_from_phone, rc_from_cc, rc_from_phone

    assert cc_from_rc("SA") == 966
    assert cc_from_phone("+966501234567") == 966
    assert rc_from_cc(966) == "sa"
    assert rc_from_phone("+966501234567") == "sa"
    assert cc_from_phone(966501234567) == 966
    assert rc_from_phone(966501234567) == "sa"

    with pytest.raises(ValidationError, match="invalid country code"):
        rc_from_cc(999999)


def test_resolve_rc_reads_letters_digits_and_numbers():
    import phonenumbers

    assert resolve_rc("SA") == "sa"
    assert resolve_rc("zz") is None
    assert resolve_rc("+966") == "sa"
    assert resolve_rc(966) == "sa"
    assert resolve_rc("966501234567") == "sa"
    assert resolve_rc(phonenumbers.parse("+966501234567")) == "sa"
    assert resolve_rc("12ab") is None
