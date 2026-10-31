"""Facts about Telegram accounts: their age and email login codes."""

from __future__ import annotations as _annotations

import re
from bisect import bisect_left

from .._internal import _optional_import
from ..email_tools import detect_email_provider, fetch_emails_from
from ..errors import ValidationError
from ..validate_tools import validation
from ._internal import _block_time, _blocks, _interpolate_time, _points


def tg_account_created_at(user_id: int) -> float:
    """Estimate when a Telegram account was created, from its id.

    Until 2024-02 ids grew over time, so below the first randomized block the
    date is interpolated between the two bundled known points around the id;
    an id at or below the first point gets that point's date. Since then ids
    are handed out at random inside blocks (7.0e9 to 7.2e9, and so on), so an
    id in a block gets the middle of that block's window, from its opening to
    the next block's opening, or to now for the block still open. The estimate
    is never later than now, unless the clock is behind the bundled data; it is
    then never earlier than the opening of the id's block. The data is read on
    first use and fitted so the date never goes down as the id grows.

    Args:
        user_id: The account's id.

    Returns:
        The estimated creation time, as a Unix timestamp.
    """
    if user_id >= _blocks()[0][0]:
        return _block_time(user_id)

    points = _points()

    if user_id <= points[0][0]:
        return points[0][1]

    # The first point at or above the id; `(user_id,)` sorts before any `(user_id, stamp)`.
    # The last point is the first block's lowest id, so there always is one.
    above = bisect_left(points, (user_id,))
    return _interpolate_time(user_id, *points[above - 1], *points[above])


@_optional_import("imap", "bs4")
async def fetch_tg_email_code(
    email: str,
    password: str,
    full_name: str,
    code_length: int,
    *,
    sender: str = "noreply@telegram.org",
    limit: int = 10,
) -> str | None:
    """Find a Telegram login code in the inbox: the first code in the newest email that names `full_name`.

    Args:
        email: The address; its domain picks the IMAP server.
        password: The password or app password.
        full_name: A name that must appear in the email, with the same case.
        code_length: How many digits the code has; at least 1.
        sender: The address the codes come from.
        limit: How many of the newest emails from `sender` to read.

    Returns:
        The code, or `None` when no email matches.

    Raises:
        ValidationError: If `code_length` is below 1, `email` is not an address,
            or no known IMAP provider serves its domain.
    """
    validation(code_length > 0, f"code_length must be at least 1, not {code_length}")
    provider = detect_email_provider(email)

    if provider is None:
        msg = f"no known IMAP provider serves {email!r}"
        raise ValidationError(msg)

    code_pattern = re.compile(rf"\b\d{{{code_length}}}\b")

    async for message in fetch_emails_from(email, password, provider, sender, limit):
        if (match := code_pattern.search(message)) and full_name in message:
            return match.group()

    return None


__all__ = (
    "tg_account_created_at",
    "fetch_tg_email_code",
)
