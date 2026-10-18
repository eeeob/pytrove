from __future__ import annotations as _annotations

from pytrove.text_tools import en_or_dis, op_or_cl, y_or_n


def test_y_or_n() -> None:
    assert y_or_n(True) == "✅"
    assert y_or_n(False) == "❌"
    assert y_or_n(1) == "✅"
    assert y_or_n(0) == "❌"


def test_en_or_dis_and_op_or_cl() -> None:
    assert en_or_dis(True) == "مفعل ✅"
    assert en_or_dis(False) == "معطل ❌"
    assert op_or_cl(True) == "مفتوح ✅"
    assert op_or_cl(False) == "مغلق ❌"
