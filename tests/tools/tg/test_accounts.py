from __future__ import annotations as _annotations

import time
from collections.abc import AsyncIterator

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


def test_account_age_between_two_points_lies_on_their_line() -> None:
    (id1, t1), (id2, t2) = points._points()[:2]

    assert tg_account_created_at(id2) == t2
    uid = id1 + (id2 - id1) // 2
    assert tg_account_created_at(uid) == pytest.approx(t1 + (t2 - t1) * (uid - id1) / (id2 - id1))


def test_account_age_past_the_last_point_extrapolates_but_never_into_the_future() -> None:
    (id1, t1), (id2, t2) = points._points()[-2:]
    beyond = id2 + (id2 - id1)

    before = time.time()
    estimate = tg_account_created_at(beyond)

    # The line through the last two points, capped at the moment of the call.
    assert estimate == pytest.approx(t2 + (t2 - t1), abs=1) or before <= estimate <= time.time()
    assert estimate > t2
    assert tg_account_created_at(10**15) <= time.time()


def _fake_inbox(monkeypatch: pytest.MonkeyPatch, *messages: str) -> None:
    """Serve `messages` as the inbox, newest first, for any Gmail address."""

    async def fake_fetch(*args: object, **kwargs: object) -> AsyncIterator[str]:
        for message in messages:
            yield message

    monkeypatch.setattr("pytrove.tg_tools.accounts.fetch_emails_from", fake_fetch)
    monkeypatch.setattr("pytrove.tg_tools.accounts.detect_email_provider", lambda email: ImapEmailProvider.GMAIL)


async def test_fetch_tg_email_code_skips_an_email_for_someone_else(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_inbox(monkeypatch, "Hello Omar, your code is 111111", "Hello Ali Hassan, your code is 222222")

    assert await fetch_tg_email_code("a@gmail.com", "pw", "Ali Hassan", 6) == "222222"


async def test_fetch_tg_email_code_only_matches_a_code_of_the_given_length(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_inbox(monkeypatch, "Ali Hassan: 1234567 or 1234", "Ali Hassan: 54321")

    assert await fetch_tg_email_code("a@gmail.com", "pw", "Ali Hassan", 5) == "54321"


async def test_fetch_tg_email_code_returns_none_when_no_email_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_inbox(monkeypatch, "Hello Omar, your code is 111111", "Ali Hassan, no code here")

    assert await fetch_tg_email_code("a@gmail.com", "pw", "Ali Hassan", 6) is None


async def test_fetch_tg_email_code_refuses_an_unknown_email_domain() -> None:
    with pytest.raises(ValidationError, match="unknown.example"):
        await fetch_tg_email_code("a@unknown.example", "pw", "Ali Hassan", 6)
