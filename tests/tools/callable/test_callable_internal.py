from __future__ import annotations as _annotations

from typing import TypeVar

from pytrove.callable_tools import _internal


def test_internal_protocols_and_type_variables() -> None:
    for proto in (
        _internal._WaitOnErrorDecorator, _internal._AwaitOnErrorDecorator,
        _internal._WaitAfterDecorator, _internal._AwaitAfterDecorator, _internal._LazyCallAll,
    ):
        assert getattr(proto, "_is_protocol", False)

    assert isinstance(_internal._ET_co, TypeVar) and _internal._ET_co.__covariant__
    assert isinstance(_internal._AT_co, TypeVar) and _internal._AT_co.__covariant__
    assert _internal._Coro is not None
    assert _internal._ExcLogger is not None
