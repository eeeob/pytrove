"""Checks for phone numbers, region codes and email addresses."""

from __future__ import annotations as _annotations

import logging
from typing import TYPE_CHECKING, Any, TypeGuard

try:
    import phonenumbers  # type: ignore[import-not-found]  # Optional: the `phone` extra.
except ImportError:
    pass

try:
    from aioimaplib import aioimaplib  # type: ignore[import-not-found]  # Optional: the `imap` extra.
except ImportError:
    pass

from .._internal import _normalize_phone_text, _optional_import
from ..constants import EMAIL_PATTERN

if TYPE_CHECKING:
    from ..typings import StrInt

log = logging.getLogger(__name__)


@_optional_import("phone")
def is_phone_number(
    phone_number: StrInt | phonenumbers.PhoneNumber,
    remove_spaces: bool = True,
    resolve: bool = True,
) -> bool:
    """Tell whether `phone_number` is a possible and valid international number.

    Returns a plain `bool`, not a type guard: a valid parsed `PhoneNumber` is
    `True` as well, so `True` does not mean the value is a `StrInt`.

    Args:
        phone_number: A number as an int, a string or a parsed `PhoneNumber`.
        remove_spaces: Whether to strip whitespace and dashes from a string first.
        resolve: Whether to turn a `00` prefix, or no prefix, into `+`.

    Returns:
        Whether phonenumbers reads it as both possible and valid.
    """
    if isinstance(phone_number, phonenumbers.PhoneNumber):
        parsed_number = phone_number
    elif isinstance(phone_number, (int, str)):
        phone_number = _normalize_phone_text(str(phone_number), remove_spaces, resolve)

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


@_optional_import("phone")
def is_rc(rc: Any) -> TypeGuard[str]:
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


def is_email(email: Any) -> TypeGuard[str]:
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


@_optional_import("imap")
async def is_accessible_received_email(email: str, password: str) -> bool:
    """Tell whether an inbox accepts this login, by signing in over IMAP.

    Args:
        email: The address; its domain picks the provider.
        password: The password or app password.

    Returns:
        Whether the server answered `OK` to the login; `False` for a rejected
        login, an unknown provider or any failure.
    """
    from ..email_tools import detect_email_provider  # noqa: PLC0415 - `email_tools` sits above `validate_tools` in the import layering

    provider = detect_email_provider(email)

    if provider is None:
        return False

    c = aioimaplib.IMAP4_SSL(host=provider.host, port=provider.port)

    try:
        await c.wait_hello_from_server()
    except Exception:
        # No session to log out of: close whatever connection was made.
        transport = getattr(c.protocol, "transport", None)

        if transport is not None:
            transport.close()

        return False

    try:
        # aioimaplib does not raise on a rejected login: the server's `NO` comes back as the result.
        response = await c.login(email, password)
    except Exception:
        return False
    else:
        return response.result == "OK"
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
)
