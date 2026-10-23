"""Checks for phone numbers, region codes and email addresses."""

from __future__ import annotations as _annotations

import logging
import re
import sys
from typing import TYPE_CHECKING, Any, Final

if sys.version_info >= (3, 13):
    from typing import TypeIs
else:
    from typing import TypeGuard as TypeIs

try:
    import phonenumbers  # type: ignore[import-not-found]  # Optional: the `phone` extra.
except ImportError:
    pass

try:
    from aioimaplib import aioimaplib  # type: ignore[import-not-found]  # Optional: the `imap` extra.
except ImportError:
    pass

from .._internal import _optional_import

if TYPE_CHECKING:
    from ..typings import StrInt

EMAIL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)
"""A plain email address: local part, `@`, a domain with a dot and a 2+ letter suffix."""

log = logging.getLogger(__name__)


@_optional_import(("phonenumbers", "phone"))
def is_phone_number(
    phone_number: StrInt | phonenumbers.PhoneNumber,
    remove_spaces: bool = True,
    resolve: bool = True,
) -> TypeIs[StrInt]:
    """Tell whether `phone_number` is a possible and valid international number.

    Args:
        phone_number: A number as an int, a string or a parsed `PhoneNumber`.
        remove_spaces: Whether to strip whitespace from a string first.
        resolve: Whether to turn a `00` prefix, or no prefix, into `+`.

    Returns:
        Whether phonenumbers reads it as both possible and valid.
    """
    if isinstance(phone_number, phonenumbers.PhoneNumber):
        parsed_number = phone_number
    elif isinstance(phone_number, (int, str)):
        phone_number = str(phone_number)

        if remove_spaces:
            from ..text_tools import clean_spaces  # noqa: PLC0415 - `text_tools` sits above `validate_tools` in the import layering

            phone_number = clean_spaces(phone_number)

        if resolve:
            if phone_number.startswith("00"):
                phone_number = phone_number[2:]

            if not phone_number.startswith("+"):
                phone_number = "+" + phone_number

        try:
            parsed_number = phonenumbers.parse(phone_number)
        except Exception:
            return False
    else:
        return False

    try:
        return phonenumbers.is_possible_number(parsed_number) and phonenumbers.is_valid_number(
            parsed_number
        )
    except Exception:
        return False


@_optional_import(("phonenumbers", "phone"))
def is_rc(rc: Any) -> TypeIs[str]:
    """Tell whether `rc` is a two-letter region code with a calling code, in any letter case.

    Args:
        rc: The value to test.

    Returns:
        Whether phonenumbers knows a calling code for it; the unknown region `ZZ` is refused.
    """
    return (
        isinstance(rc, str)
        and rc.isalpha()
        and len(rc) == 2
        and rc.lower() != "zz"
        and phonenumbers.country_code_for_region(rc.upper()) != 0
    )


def is_email(email: Any) -> TypeIs[str]:
    """Tell whether `email` is a plain email address.

    Args:
        email: The value to test.

    Returns:
        Whether it is a string fully matching `EMAIL_PATTERN`.

    Example:
        >>> is_email("user@example.com")
        True
        >>> is_email("user@localhost")
        False
    """
    return isinstance(email, str) and bool(EMAIL_PATTERN.fullmatch(email))


@_optional_import(("aioimaplib", "imap"))
async def is_accessible_received_email(email: str, password: str) -> bool:
    """Tell whether an inbox accepts this login, by signing in over IMAP.

    Args:
        email: The address; its domain picks the provider.
        password: The password or app password.

    Returns:
        Whether the login succeeded; `False` for an unknown provider or any failure.
    """
    from ..email_tools import detect_email_provider  # noqa: PLC0415 - `email_tools` sits above `validate_tools` in the import layering

    provider = detect_email_provider(email)

    if provider is None:
        return False

    c = aioimaplib.IMAP4_SSL(host=provider.host, port=provider.port)

    try:
        await c.wait_hello_from_server()
        await c.login(email, password)
    except Exception:
        return False
    else:
        return True
    finally:
        try:
            await c.logout()
        except Exception as e:
            log.error("Failed to log out from the IMAP server", exc_info=e)


__all__ = (
    "is_phone_number",
    "is_rc",
    "is_email",
    "is_accessible_received_email",
    "EMAIL_PATTERN",
)
