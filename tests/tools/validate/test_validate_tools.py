from pytrove.validate_tools import is_tg_bot_token
from pytrove import (
    is_container, is_mapping, is_sub_container, is_sub_mapping,
    is_email, is_exception,
)


def test_is_tg_bot_token_still_accepts_a_well_formed_token():
    assert is_tg_bot_token("123456:ABC")


def test_is_container_accepts_plain_collections():
    assert is_container([1, 2, 3])
    assert is_container((1, 2, 3))
    assert is_container({1, 2, 3})
    assert is_container({"a": 1})
    assert is_container(range(3))
    assert is_container(x for x in range(2))  # generator expression -> Generator ABC


def test_is_container_accepts_bare_iterator():
    # Container names Iterator rather than listing filter/enumerate/zip one by
    # one -- those are all Iterators anyway, and neither `filter` nor `zip` is
    # subscriptable at runtime, so `filter[I]` raised TypeError the moment the
    # alias was evaluated. Consequence of the wider member: any single-pass
    # iterator now counts as a container, list_iterator included.
    assert is_container(iter([1, 2]))
    assert is_container(filter(None, [1, 2]))
    assert is_container(enumerate([1, 2]))
    assert is_container(zip([1, 2], "ab"))
    assert is_container(map(str, [1, 2]))


def test_is_container_rejects_not_container_types():
    # str/bytes/bytearray/memoryview are explicitly excluded even though
    # they are technically iterable, per typings.NotContainer.
    assert not is_container("abc")
    assert not is_container(b"abc")
    assert not is_container(bytearray(b"abc"))
    assert not is_container(1)
    assert not is_container(None)


def test_is_mapping():
    assert is_mapping({"a": 1})
    assert not is_mapping([1, 2])


def test_is_sub_container_and_is_sub_mapping():
    assert is_sub_container(list)
    assert is_sub_container(dict)
    assert not is_sub_container(str)
    assert is_sub_mapping(dict)
    assert not is_sub_mapping(list)


def test_is_email():
    assert is_email("user@example.com")
    assert not is_email("not-an-email")
    assert not is_email(123)


def test_is_exception():
    assert is_exception(ValueError("x"))
    assert not is_exception("x")
