from __future__ import annotations as _annotations

from typing import overload

try:
    from phonenumbers import (
        parse, format_number,  
        region_code_for_country_code, 
        region_code_for_number, 
        country_code_for_valid_region, 
        PhoneNumberFormat, 
        PhoneNumber as PhoneNumberObj, 
        UNKNOWN_REGION, 
    )
except ImportError:
    pass

from .typings import PhoneNumber, RegionCode, _True
from .text_tools import clean_spaces, to_str
from .validate_tools import is_rc, validation, is_phone_number
from .callable_tools import safe_call

from ._optional import _optional_import


@overload
def parse_phone(
    phone_number: PhoneNumber | int | PhoneNumberObj, 
    clean: bool = True, 
    ) -> PhoneNumber: ...
@overload
def parse_phone(
    phone_number: PhoneNumber | int | PhoneNumberObj, 
    clean: bool = True, 
    *, 
    return_numobj: _True
    ) -> PhoneNumberObj: ...
@_optional_import(("phonenumbers", "phone"))
def parse_phone(
    phone_number, 
    clean = True, 
    return_numobj = False
    ):

    if not isinstance(phone_number, PhoneNumberObj):
        phone_number = to_str(phone_number)
        validation(isinstance(phone_number, str), f"Invalid PhoneNumber - {phone_number}")

        if clean:
            phone_number = clean_spaces(phone_number).replace("-", "")
        
        if phone_number.startswith("00"):
            phone_number = phone_number[2:]

        if not phone_number.startswith("+"):
            phone_number = "+" + phone_number
    
        phone_number = parse(phone_number)
    
    validation(is_phone_number(phone_number, remove_spaces=False, resolve=False), f"Invalid PhoneNumber - {phone_number}")
    
    return phone_number if return_numobj else format_number(phone_number, PhoneNumberFormat.E164)
    
@_optional_import(("phonenumbers", "phone"))
def cc_from_rc(rc: RegionCode) -> int:
    return country_code_for_valid_region(rc.lower())

@_optional_import(("phonenumbers", "phone"))
def cc_from_phone(phone_number: PhoneNumber | PhoneNumberObj) -> int:
    if not isinstance(phone_number, PhoneNumberObj):
        phone_number = parse_phone(phone_number, return_numobj=True)
        
    return phone_number.country_code

@_optional_import(("phonenumbers", "phone"))
def rc_from_cc(cc: int) -> RegionCode:
    rc = region_code_for_country_code(cc)
    validation(rc != UNKNOWN_REGION, "invalid country code %s" % cc)
    
    return rc.lower()

@_optional_import(("phonenumbers", "phone"))
def rc_from_phone(phone_number: PhoneNumber | PhoneNumberObj) -> RegionCode:
    if not isinstance(phone_number, PhoneNumberObj):
        phone_number = parse_phone(phone_number, return_numobj=True)
        
    rc = region_code_for_number(phone_number)
    validation(rc is not None, "invalid PhoneNumber %s" % phone_number)
    
    return rc.lower()
        
@_optional_import(("phonenumbers", "phone"))
def resolve_rc(value: RegionCode | PhoneNumber | PhoneNumberObj | int) -> RegionCode | None:
    if isinstance(value, int):
        return rc_from_cc(value)
    elif isinstance(value, PhoneNumberObj):
        return rc_from_phone(value)

    value = clean_spaces(value).replace("-", "").lower()

    if value.isalpha():
        return value if is_rc(value) else None
    
    if value.startswith("+"):
        value = value[1:]
    
    try:
        value = int(value)
    except (ValueError, TypeError):
        return None
    
    return safe_call(rc_from_cc, value) or safe_call(rc_from_phone, value)


__all__ = (
    "parse_phone", 
    "cc_from_rc", 
    "cc_from_phone", 
    "rc_from_cc", 
    "rc_from_phone", 
    "resolve_rc", 
)