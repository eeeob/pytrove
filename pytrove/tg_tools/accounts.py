"""Facts about Telegram accounts: their age, and login codes sent by email."""

from __future__ import annotations as _annotations

import re
from itertools import pairwise

from .._internal._optional import _optional_import
from ..email_tools import detect_email_provider, fetch_emails_from
from ..errors import ValidationError
from ._internal.points import _interpolate_time, _points


def tg_account_created_at(user_id: int) -> float:
    """Estimate when a Telegram account was created, from its id.

    Ids grow over time, so the date is interpolated between bundled known
    points, and extrapolated past the last one but never into the future.
    An id at or below the first point gets that point's date. The points are
    read on first use.

    Args:
        user_id: The account's id.

    Returns:
        The estimated creation time, as a Unix timestamp.
    """
    points = _points()

    if user_id <= points[0][0]:
        return points[0][1]

    for (id1, t1), (id2, t2) in pairwise(points):
        if id1 <= user_id <= id2:
            return _interpolate_time(user_id, id1, t1, id2, t2)

    return _interpolate_time(user_id, *points[-2], *points[-1])


@_optional_import(("aioimaplib", "imap"), ("beautifulsoup4", "bs4"))
async def fetch_tg_email_code(
    email: str, password: str, full_name: str, code_length: int
) -> str | None:
    """Find a Telegram login code in the inbox: the first code in the newest email that names `full_name`.

    Args:
        email: The address; its domain picks the IMAP server.
        password: The password or app password.
        full_name: A name that must appear in the email.
        code_length: How many digits the code has.

    Returns:
        The code, or `None` when no email matches.

    Raises:
        ValidationError: If `email` is not an address, or no known IMAP provider serves its domain.
    """
    provider = detect_email_provider(email)

    if provider is None:
        msg = f"no known IMAP provider serves {email!r}"
        raise ValidationError(msg)

    code_pattern = re.compile(rf"\b\d{{{code_length}}}\b")

    async for message in fetch_emails_from(email, password, provider):
        if (match := code_pattern.search(message)) and full_name in message:
            return match.group()

    return None


__all__ = (
    "tg_account_created_at",
    "fetch_tg_email_code",
)
