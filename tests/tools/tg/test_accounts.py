from __future__ import annotations as _annotations

import importlib.util
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest

from pytrove import device_tools, tg_tools
from pytrove.enums import ImapEmailProvider
from pytrove.errors import ValidationError
from pytrove.tg_tools import accounts, fetch_tg_email_code, tg_account_created_at
from pytrove.tg_tools import format as tg_format
from pytrove.tg_tools._internal import points

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

HAS_EMAIL = all(importlib.util.find_spec(name) is not None for name in ("aioimaplib", "bs4"))

needs_email = pytest.mark.skipif(not HAS_EMAIL, reason="needs the imap and bs4 extras")


def test_account_age_is_interpolated_and_capped() -> None:
    first_id, first_time = points._points()[0]
    assert tg_account_created_at(first_id) == first_time
    assert tg_account_created_at(0) == first_time
    assert tg_account_created_at(10**12) <= time.time()
    mid = (points._points()[1][0] + points._points()[2][0]) // 2
    assert points._points()[1][1] <= tg_account_created_at(mid) <= points._points()[2][1]


@needs_email
async def test_fetch_tg_email_code_matches_a_six_digit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_inbox(monkeypatch, "Hello Ali Hassan, your code is 123456")

    assert await fetch_tg_email_code("a@gmail.com", "pw", "Ali Hassan", 6) == "123456"


def test_account_age_between_two_points_lies_on_their_line() -> None:
    (id1, t1), (id2, t2) = points._points()[:2]

    assert tg_account_created_at(id2) == t2
    uid = id1 + (id2 - id1) // 2
    assert tg_account_created_at(uid) == pytest.approx(t1 + (t2 - t1) * (uid - id1) / (id2 - id1))


def test_account_age_inside_a_closed_block_is_the_middle_of_its_window() -> None:
    (low, opened), (_, closed) = points._blocks()[:2]

    assert tg_account_created_at(low) == (opened + closed) / 2
    assert tg_account_created_at(7_100_000_000) == (opened + closed) / 2
    assert "2024-02-19" <= _date(tg_account_created_at(7_100_000_000)) <= "2024-05-26"


def test_account_age_inside_the_open_block_runs_to_now_and_never_past_it() -> None:
    low, opened = points._blocks()[-1]

    before = time.time()
    estimate = tg_account_created_at(low)

    assert (opened + before) / 2 <= estimate <= (opened + time.time()) / 2
    assert tg_account_created_at(9_500_000_000) <= time.time()
    assert tg_account_created_at(10**15) <= time.time()


def test_account_age_just_below_the_first_block_meets_its_opening() -> None:
    low, opened = points._blocks()[0]

    assert tg_account_created_at(low - 1) <= opened
    assert tg_account_created_at(low - 1) == pytest.approx(opened, abs=86_400)


def _fake_inbox(monkeypatch: pytest.MonkeyPatch, *messages: str) -> list[tuple[object, ...]]:
    """Serve `messages` as the inbox, newest first, for any Gmail address; return the calls made."""
    calls: list[tuple[object, ...]] = []

    async def fake_fetch(*args: object, **kwargs: object) -> AsyncIterator[str]:
        calls.append((*args, *kwargs.items()))
        for message in messages:
            yield message

    monkeypatch.setattr("pytrove.tg_tools.accounts.fetch_emails_from", fake_fetch)
    monkeypatch.setattr(
        "pytrove.tg_tools.accounts.detect_email_provider", lambda email: ImapEmailProvider.GMAIL
    )
    return calls


@needs_email
async def test_fetch_tg_email_code_skips_an_email_for_someone_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_inbox(
        monkeypatch, "Hello Omar, your code is 111111", "Hello Ali Hassan, your code is 222222"
    )

    assert await fetch_tg_email_code("a@gmail.com", "pw", "Ali Hassan", 6) == "222222"


@needs_email
async def test_fetch_tg_email_code_only_matches_a_code_of_the_given_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_inbox(monkeypatch, "Ali Hassan: 1234567 or 1234", "Ali Hassan: 54321")

    assert await fetch_tg_email_code("a@gmail.com", "pw", "Ali Hassan", 5) == "54321"


@needs_email
async def test_fetch_tg_email_code_returns_none_when_no_email_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_inbox(monkeypatch, "Hello Omar, your code is 111111", "Ali Hassan, no code here")

    assert await fetch_tg_email_code("a@gmail.com", "pw", "Ali Hassan", 6) is None


@needs_email
async def test_fetch_tg_email_code_refuses_an_unknown_email_domain() -> None:
    with pytest.raises(ValidationError, match="unknown.example"):
        await fetch_tg_email_code("a@unknown.example", "pw", "Ali Hassan", 6)


@pytest.mark.skipif(HAS_EMAIL, reason="checks the error raised without the imap and bs4 extras")
async def test_fetch_tg_email_code_without_its_extras_raises_a_clear_import_error() -> None:
    with pytest.raises(ImportError, match=r"pip install -U 'pytrove\[imap, bs4\]'"):
        await fetch_tg_email_code("a@gmail.com", "pw", "Ali Hassan", 6)


@needs_email
async def test_fetch_tg_email_code_refuses_a_value_that_is_not_an_address() -> None:
    with pytest.raises(ValidationError, match="not valid email"):
        await fetch_tg_email_code("not-an-address", "pw", "Ali Hassan", 6)


def test_the_device_draw_lives_only_in_device_tools() -> None:
    assert "random_device" in device_tools.__all__
    assert not hasattr(tg_tools, "rand_tg_device")
    assert not hasattr(accounts, "rand_tg_device")
    assert "random_device" not in accounts.__all__


def _date(stamp: float) -> str:
    """Format a timestamp as its UTC date."""
    return datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d")


def test_account_age_never_goes_down_as_the_id_grows() -> None:
    lows = [low for low, _ in points._blocks()]
    ids = sorted({uid for uid, _ in points._points()} | set(lows))
    edges = {low + step for low in lows for step in (-1, 1)}
    probes = sorted({*ids, *edges, *((a + b) // 2 for a, b in zip(ids, ids[1:], strict=False))})
    estimates = [tg_account_created_at(uid) for uid in probes]

    assert estimates == sorted(estimates)


def test_account_age_inside_a_stretch_where_the_bundled_ids_go_down() -> None:
    # The file lists 111220210 (2015-04-21) before 103258382 (2015-05-27); the id
    # between them used to land on 2015-04-05, before both neighbours.
    assert "2015-05-01" <= _date(tg_account_created_at(107_239_296)) <= "2015-07-01"


def test_account_age_of_a_mid_2022_id() -> None:
    assert "2022-02-01" <= _date(tg_account_created_at(5_200_000_000)) <= "2022-04-30"


@needs_email
async def test_fetch_tg_email_code_forwards_the_account_and_search_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _fake_inbox(monkeypatch, "Ali Hassan: 123456")

    assert await fetch_tg_email_code("a@gmail.com", "pw", "Ali Hassan", 6) == "123456"
    assert (
        await fetch_tg_email_code("a@gmail.com", "pw", "Ali Hassan", 6, sender="x@y.org", limit=3)
        == "123456"
    )
    assert calls == [
        ("a@gmail.com", "pw", ImapEmailProvider.GMAIL, "noreply@telegram.org", 10),
        ("a@gmail.com", "pw", ImapEmailProvider.GMAIL, "x@y.org", 3),
    ]


@needs_email
@pytest.mark.parametrize("code_length", [0, -1])
async def test_fetch_tg_email_code_refuses_a_code_length_below_one(
    monkeypatch: pytest.MonkeyPatch, code_length: int
) -> None:
    calls = _fake_inbox(monkeypatch, "Ali Hassan: 123456")

    with pytest.raises(ValidationError, match="code_length"):
        await fetch_tg_email_code("a@gmail.com", "pw", "Ali Hassan", code_length)

    assert calls == []


@needs_email
async def test_fetch_tg_email_code_finds_a_code_written_before_the_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_inbox(monkeypatch, "123456 is the code for Ali Hassan")

    assert await fetch_tg_email_code("a@gmail.com", "pw", "Ali Hassan", 6) == "123456"


@needs_email
async def test_fetch_tg_email_code_matches_the_name_with_its_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_inbox(monkeypatch, "Hello Ali Hassan, your code is 123456")

    assert await fetch_tg_email_code("a@gmail.com", "pw", "ali hassan", 6) is None


def test_tg_tools_exports_the_format_and_accounts_tools() -> None:
    assert tg_tools.__all__ == (*tg_format.__all__, *accounts.__all__)
