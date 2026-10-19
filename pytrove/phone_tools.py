"""Parsing phone numbers and converting between region and calling codes."""

from __future__ import annotations as _annotations

from functools import partial
from typing import Any, overload

try:
    from phonenumbers import (
        NumberParseException,
        PhoneNumber as PhoneNumberObj,
        PhoneNumberFormat,
        country_code_for_valid_region,
        format_number,
        parse,
        region_code_for_country_code,
        region_code_for_number,
        UNKNOWN_REGION,
    )
except ImportError:
    pass

from ._internal._optional import _optional_import
from .callable_tools import safe_call
from .errors import ValidationError
from .text_tools import clean_spaces, to_str
from .typings import PhoneNumber, RegionCode, _True
from .validate_tools import is_phone_number, is_rc, validation


@overload
def parse_phone(phone_number: PhoneNumber | int | PhoneNumberObj, clean: bool = True) -> PhoneNumber: ...
@overload
def parse_phone(
    phone_number: PhoneNumber | int | PhoneNumberObj, clean: bool = True, *, return_numobj: _True,
) -> PhoneNumberObj: ...
@_optional_import(("phonenumbers", "phone"))
def parse_phone(phone_number: Any, clean: bool = True, return_numobj: bool = False) -> Any:
    """Parse and validate an international phone number.

    A `00` prefix becomes `+`, and a missing `+` is added.

    Args:
        phone_number: The number as text, an int or a parsed `PhoneNumber`.
        clean: Whether to remove whitespace and dashes first.
        return_numobj: Whether to return the parsed object instead of text.

    Returns:
        The number in E.164 form (`+966501234567`), or the parsed object.

    Raises:
        ValidationError: If it is not a valid number, including text that
            `phonenumbers` cannot parse at all.
    """
    if not isinstance(phone_number, PhoneNumberObj):
        phone_number = to_str(phone_number)
        validation(isinstance(phone_number, str), f"Invalid PhoneNumber - {phone_number}")

        if clean:
            phone_number = clean_spaces(phone_number).replace("-", "")

        if phone_number.startswith("00"):
            phone_number = phone_number[2:]

        if not phone_number.startswith("+"):
            phone_number = "+" + phone_number

        try:
            phone_number = parse(phone_number)
        except NumberParseException as exc:
            msg = f"Invalid PhoneNumber - {phone_number}"
            raise ValidationError(msg) from exc

    validation(is_phone_number(phone_number, remove_spaces=False, resolve=False), f"Invalid PhoneNumber - {phone_number}")
    return phone_number if return_numobj else format_number(phone_number, PhoneNumberFormat.E164)


@_optional_import(("phonenumbers", "phone"))
def cc_from_rc(rc: RegionCode) -> int:
    """Return a region's international calling code: `"sa"` gives 966.

    Args:
        rc: The two-letter region code, in any case.

    Returns:
        The calling code.

    Raises:
        ValidationError: If the region is not valid.
    """
    try:
        return country_code_for_valid_region(rc.lower())
    except Exception as exc:
        msg = f"invalid region code {rc!r}"
        raise ValidationError(msg) from exc


@_optional_import(("phonenumbers", "phone"))
def cc_from_phone(phone_number: PhoneNumber | int | PhoneNumberObj) -> int:
    """Return a phone number's calling code.

    Args:
        phone_number: The number, as text or parsed.

    Returns:
        The calling code.

    Raises:
        ValidationError: If it is not a valid number.
    """
    if not isinstance(phone_number, PhoneNumberObj):
        phone_number = parse_phone(phone_number, return_numobj=True)

    cc = phone_number.country_code

    if cc is None:
        msg = f"invalid PhoneNumber {phone_number}"
        raise ValidationError(msg)

    return cc


@_optional_import(("phonenumbers", "phone"))
def rc_from_cc(cc: int) -> RegionCode:
    """Return the main region using a calling code: 966 gives `"sa"`.

    Args:
        cc: The calling code.

    Returns:
        The lowercase region code.

    Raises:
        ValidationError: If no region uses the code.
    """
    rc = region_code_for_country_code(cc)
    validation(rc != UNKNOWN_REGION, f"invalid country code {cc}")
    return rc.lower()


@_optional_import(("phonenumbers", "phone"))
def rc_from_phone(phone_number: PhoneNumber | int | PhoneNumberObj) -> RegionCode:
    """Return the region a phone number belongs to.

    Args:
        phone_number: The number, as text or parsed.

    Returns:
        The lowercase region code.

    Raises:
        ValidationError: If it is not a valid number or has no region.
    """
    if not isinstance(phone_number, PhoneNumberObj):
        phone_number = parse_phone(phone_number, return_numobj=True)

    rc = region_code_for_number(phone_number)

    if rc is None:
        msg = f"invalid PhoneNumber {phone_number}"
        raise ValidationError(msg)

    return rc.lower()


@_optional_import(("phonenumbers", "phone"))
def resolve_rc(value: RegionCode | PhoneNumber | PhoneNumberObj | int) -> RegionCode | None:
    """Find a region from a region code, a calling code or a phone number.

    Args:
        value: Letters are read as a region code; digits as a calling code,
            then as a phone number; a parsed number by its region.

    Returns:
        The lowercase region code, or `None` when nothing matches.
    """
    if isinstance(value, int):
        return safe_call(partial(rc_from_cc, value))

    if isinstance(value, PhoneNumberObj):
        return rc_from_phone(value)

    text = clean_spaces(value).replace("-", "").lower()

    if text.isalpha():
        return text if is_rc(text) else None

    try:
        number = int(text.removeprefix("+"))
    except (ValueError, TypeError):
        return None

    return safe_call(partial(rc_from_cc, number)) or safe_call(partial(rc_from_phone, number))


__all__ = (
    "parse_phone",
    "cc_from_rc",
    "cc_from_phone",
    "rc_from_cc",
    "rc_from_phone",
    "resolve_rc",
)
