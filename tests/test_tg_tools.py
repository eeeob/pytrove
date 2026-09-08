from pytrove import parse_tg_target


def test_parse_tg_target_passes_an_int_through():
    assert parse_tg_target(123456) == 123456


def test_parse_tg_target_reads_a_phone_number_as_an_int():
    assert parse_tg_target("+967 (777) 123-456") == 967777123456
    assert parse_tg_target("967777123456") == 967777123456


def test_parse_tg_target_strips_at_and_plus_from_a_username():
    assert parse_tg_target("@some_user") == "some_user"
    assert parse_tg_target("some_user") == "some_user"


def test_parse_tg_target_lowercases_a_username():
    assert parse_tg_target("@Some_User") == "some_user"


def test_parse_tg_target_reads_a_channel_message_link_into_a_chat_id():
    # get_channel_id(1234567890) == -1001234567890
    assert parse_tg_target("https://t.me/c/1234567890") == -1001234567890


def test_parse_tg_target_keeps_a_non_numeric_link_capture_as_a_string():
    assert parse_tg_target("https://t.me/some_channel") == "some_channel"
