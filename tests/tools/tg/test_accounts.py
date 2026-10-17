from __future__ import annotations as _annotations

import time

import pytest

from pytrove.enums import ImapEmailProvider
from pytrove.errors import ValidationError
from pytrove.tg_tools import fetch_tg_email_code, tg_account_created_at
from pytrove.tg_tools._internal import points


def test_account_age_is_interpolated_and_capped() -> None:
    first_id, first_time = points._points()[0]
    assert tg_account_created_at(first_id) == first_time
    assert tg_account_created_at(0) == first_time
    assert tg_account_created_at(10**12) <= time.time()
    mid = (points._points()[1][0] + points._points()[2][0]) // 2
    assert points._points()[1][1] <= tg_account_created_at(mid) <= points._points()[2][1]


async def test_fetch_tg_email_code_matches_a_six_digit_code(monkeypatch):
    async def fake_fetch(*args, **kwargs):
        yield "Hello Ali Hassan, your code is 123456"

    monkeypatch.setattr("pytrove.tg_tools.accounts.fetch_emails_from", fake_fetch)
    monkeypatch.setattr(
        "pytrove.tg_tools.accounts.detect_email_provider",
        lambda email: ImapEmailProvider.GMAIL,
    )

    assert await fetch_tg_email_code("a@gmail.com", "pw", "Ali Hassan", 6) == "123456"


async def test_fetch_tg_email_code_refuses_an_unknown_email_domain() -> None:
    with pytest.raises(ValidationError, match="unknown.example"):
        await fetch_tg_email_code("a@unknown.example", "pw", "Ali Hassan", 6)
