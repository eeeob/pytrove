from __future__ import annotations as _annotations

import importlib.util

import pytest

from pytrove.errors import ValidationError
from pytrove.phone_tools import (
    cc_from_phone,
    cc_from_rc,
    parse_phone,
    rc_from_cc,
    rc_from_phone,
    resolve_rc,
)

HAS_PHONENUMBERS = importlib.util.find_spec("phonenumbers") is not None

needs_phone = pytest.mark.skipif(not HAS_PHONENUMBERS, reason="needs the phone extra")


@needs_phone
def test_parse_phone_normalises_to_e164() -> None:
    assert parse_phone("00966 50-123-4567") == "+966501234567"
    assert parse_phone(966501234567) == "+966501234567"
    assert parse_phone("+966501234567", return_numobj=True).country_code == 966


@needs_phone
def test_parse_phone_accepts_a_parsed_number() -> None:
    phonenumbers = pytest.importorskip("phonenumbers")
    parsed = phonenumbers.parse("+966501234567")
    assert parse_phone(parsed) == "+966501234567"
    assert parse_phone(parsed, return_numobj=True) is parsed


@needs_phone
def test_parse_phone_can_skip_the_cleaning() -> None:
    assert parse_phone("+966 50 123 4567", clean=False) == "+966501234567"
    assert parse_phone("966501234567", clean=False) == "+966501234567"


@needs_phone
def test_parse_phone_rejects_an_invalid_number() -> None:
    with pytest.raises(ValidationError, match="Invalid PhoneNumber"):
        parse_phone("+123")

    with pytest.raises(ValidationError, match="Invalid PhoneNumber"):
        parse_phone(["+966501234567"])


@needs_phone
def test_parse_phone_wraps_an_unparsable_number_in_validation_error() -> None:
    phonenumbers = pytest.importorskip("phonenumbers")

    with pytest.raises(ValidationError, match="Invalid PhoneNumber") as info:
        parse_phone("abc")

    assert isinstance(info.value.__cause__, phonenumbers.NumberParseException)

    for call in (cc_from_phone, rc_from_phone):
        with pytest.raises(ValidationError, match="Invalid PhoneNumber"):
            call("abc")


@needs_phone
def test_cc_from_rc_reads_a_region_in_any_case() -> None:
    assert cc_from_rc("SA") == 966
    assert cc_from_rc("sa") == 966


@needs_phone
def test_cc_from_rc_raises_validation_error_for_an_invalid_region() -> None:
    with pytest.raises(ValidationError, match="invalid region code"):
        cc_from_rc("zz")


@needs_phone
def test_cc_from_phone_reads_text_an_int_or_a_parsed_number() -> None:
    phonenumbers = pytest.importorskip("phonenumbers")
    assert cc_from_phone("+966501234567") == 966
    assert cc_from_phone(966501234567) == 966
    assert cc_from_phone(phonenumbers.parse("+966501234567")) == 966


@needs_phone
def test_cc_from_phone_rejects_a_parsed_number_without_a_calling_code() -> None:
    phonenumbers = pytest.importorskip("phonenumbers")

    with pytest.raises(ValidationError, match="Invalid PhoneNumber"):
        cc_from_phone(phonenumbers.PhoneNumber())


@needs_phone
def test_rc_from_cc_reads_the_main_region() -> None:
    assert rc_from_cc(966) == "sa"
    assert rc_from_cc(1) == "us"

    with pytest.raises(ValidationError, match="invalid country code"):
        rc_from_cc(999999)


@needs_phone
def test_rc_from_phone_reads_text_an_int_or_a_parsed_number() -> None:
    phonenumbers = pytest.importorskip("phonenumbers")
    assert rc_from_phone("+966501234567") == "sa"
    assert rc_from_phone(966501234567) == "sa"
    assert rc_from_phone(phonenumbers.parse("+966501234567")) == "sa"


@needs_phone
def test_rc_from_phone_rejects_a_parsed_number_without_a_region() -> None:
    phonenumbers = pytest.importorskip("phonenumbers")

    with pytest.raises(ValidationError, match="Invalid PhoneNumber"):
        rc_from_phone(phonenumbers.PhoneNumber(country_code=999, national_number=12345))


@needs_phone
def test_resolve_rc_reads_letters_digits_and_numbers() -> None:
    phonenumbers = pytest.importorskip("phonenumbers")

    assert resolve_rc("SA") == "sa"
    assert resolve_rc("zz") is None
    assert resolve_rc("+966") == "sa"
    assert resolve_rc(966) == "sa"
    assert resolve_rc("966501234567") == "sa"
    assert resolve_rc("+1 650-253-0000") == "us"
    assert resolve_rc(phonenumbers.parse("+966501234567")) == "sa"
    assert resolve_rc("12ab") is None


@needs_phone
def test_resolve_rc_returns_none_for_an_unknown_calling_code() -> None:
    assert resolve_rc(999999) is None
    assert resolve_rc("999999") is None


@pytest.mark.skipif(HAS_PHONENUMBERS, reason="the phone extra is installed")
def test_the_phone_tools_name_the_phone_extra_when_phonenumbers_is_missing() -> None:
    for call in (
        lambda: parse_phone("+966501234567"),
        lambda: cc_from_rc("sa"),
        lambda: cc_from_phone("+966501234567"),
        lambda: rc_from_cc(966),
        lambda: rc_from_phone("+966501234567"),
        lambda: resolve_rc("sa"),
    ):
        with pytest.raises(ImportError, match=r"pytrove\[phone\]"):
            call()


@needs_phone
def test_parse_phone_without_cleaning_still_reads_dashes() -> None:
    assert parse_phone("+966-50-123-4567", clean=False) == "+966501234567"


@needs_phone
def test_parse_phone_rejects_a_plus_00_prefix() -> None:
    with pytest.raises(ValidationError, match="Invalid PhoneNumber"):
        parse_phone("+00966501234567")


@needs_phone
def test_cc_from_rc_wraps_a_non_text_region_in_validation_error() -> None:
    with pytest.raises(ValidationError, match="invalid region code") as info:
        cc_from_rc(966)

    assert isinstance(info.value.__cause__, AttributeError)


@needs_phone
def test_cc_from_phone_validates_a_parsed_number() -> None:
    phonenumbers = pytest.importorskip("phonenumbers")

    with pytest.raises(ValidationError, match="Invalid PhoneNumber"):
        cc_from_phone(phonenumbers.PhoneNumber(country_code=999, national_number=1))


@needs_phone
def test_rc_from_cc_rejects_a_non_geographic_code() -> None:
    with pytest.raises(ValidationError, match="invalid country code"):
        rc_from_cc(800)


@needs_phone
def test_rc_from_phone_rejects_a_non_geographic_number() -> None:
    with pytest.raises(ValidationError, match="invalid PhoneNumber"):
        rc_from_phone("+80012345678")


@needs_phone
def test_resolve_rc_reads_an_int_phone_number() -> None:
    assert resolve_rc(966501234567) == "sa"
    assert resolve_rc(16502530000) == "us"


@needs_phone
def test_resolve_rc_refuses_a_bool() -> None:
    assert resolve_rc(True) is None
    assert resolve_rc(False) is None


@needs_phone
def test_resolve_rc_returns_none_for_an_invalid_parsed_number() -> None:
    phonenumbers = pytest.importorskip("phonenumbers")

    assert resolve_rc(phonenumbers.PhoneNumber(country_code=999, national_number=1)) is None


@needs_phone
def test_resolve_rc_returns_none_for_a_non_geographic_number() -> None:
    assert resolve_rc("+80012345678") is None
    assert resolve_rc(800) is None
