from __future__ import annotations as _annotations

import asyncio
import sys
import threading
from collections.abc import Callable, Coroutine
from typing import Any

import pytest

from pytrove.async_tools import AioThreadWorker
from pytrove.async_tools._internal import _LoopHost, loop_host

from pytrove.object_tools.proxies import HAS_WRAPT

needs_proxy = pytest.mark.skipif(not HAS_WRAPT, reason="needs the proxy extra")

_LoopRunner = Callable[
    [Coroutine[Any, Any, Any], Callable[[], asyncio.AbstractEventLoop] | None], None
]


def _patch_run_loop(monkeypatch: pytest.MonkeyPatch, run_loop: _LoopRunner) -> None:
    """Replace the loop driver the worker thread calls."""
    monkeypatch.setattr(loop_host, "_run_loop", run_loop)


def test_loop_host_starts_in_a_known_state() -> None:
    host = _LoopHost(run_now=False)

    assert not host.is_started()
    assert not host.is_running()
    assert not host.is_stopping()
    assert not host.is_finished()


def test_loop_host_logs_under_the_worker_logger() -> None:
    assert loop_host.log.name == "pytrove.async_tools.worker"


def test_loop_proxy_refuses_before_the_loop_is_published() -> None:
    host = _LoopHost(run_now=False)

    with pytest.raises(RuntimeError, match="not been published"):
        _ = host._loop_proxy


def test_bootstrap_refuses_any_thread_but_the_workers() -> None:
    worker = AioThreadWorker()
    worker.wait_for_running(5)

    with pytest.raises(RuntimeError, match="worker thread"):
        worker._bootstrap()

    asyncio.run(worker.join(timeout=5))


def test_get_loop_refuses_a_worker_that_is_not_running() -> None:
    worker = AioThreadWorker(run_now=False)

    with pytest.raises(RuntimeError, match="Worker not running"):
        worker.get_loop()


def test_get_loop_refuses_a_published_loop_that_is_not_running() -> None:
    worker = AioThreadWorker()
    worker.wait_for_running(5)
    real_loop = worker._loop
    idle_loop = asyncio.new_event_loop()
    worker._loop = idle_loop

    try:
        with pytest.raises(RuntimeError, match="event loop is not running"):
            worker.get_loop()
    finally:
        worker._loop = real_loop
        idle_loop.close()

    asyncio.run(worker.join(timeout=5))


def test_get_loop_refuses_a_closed_loop() -> None:
    class _ClosedButRunning:
        """A loop stand-in that reports running and closed at once."""

        def is_running(self) -> bool:
            """Report running."""
            return True

        def is_closed(self) -> bool:
            """Report closed."""
            return True

    worker = AioThreadWorker()
    worker.wait_for_running(5)
    real_loop = worker._loop
    fake_loop: Any = _ClosedButRunning()
    worker._loop = fake_loop

    try:
        with pytest.raises(RuntimeError, match="already closed"):
            worker.get_loop()
    finally:
        worker._loop = real_loop

    asyncio.run(worker.join(timeout=5))


@needs_proxy
def test_get_loop_hands_out_the_loop_without_stop_or_close() -> None:
    worker = AioThreadWorker()
    worker.wait_for_running(5)
    loop = worker.get_loop()

    assert loop.is_running()
    assert worker.get_loop() is loop  # The proxy is built once.

    with pytest.raises(AttributeError):
        loop.close()

    asyncio.run(worker.join(timeout=5))


@pytest.mark.skipif(HAS_WRAPT, reason="checks the error raised without the proxy extra")
def test_get_loop_without_the_proxy_extra_names_it() -> None:
    worker = AioThreadWorker()
    worker.wait_for_running(5)

    with pytest.raises(ImportError, match=r"pytrove\[proxy\]"):
        worker.get_loop()

    asyncio.run(worker.join(timeout=5))


@needs_proxy
async def test_exception_handler_is_installed_on_the_loop() -> None:
    def handler(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        """Ignore the error."""

    async def installed_handler() -> object:
        """Return the handler of the loop this runs on."""
        return asyncio.get_running_loop().get_exception_handler()

    async with AioThreadWorker(exception_handler=handler) as worker:
        assert await worker.submit(installed_handler) is handler


def test_run_waits_until_running_when_asked() -> None:
    worker = AioThreadWorker(run_now=False)
    worker.run(wait=5)

    assert worker.is_started()
    assert worker.is_running()
    worker.wait_for_running()  # Returns at once while running.
    asyncio.run(worker.join(timeout=5))


def test_loop_factory_builds_the_loop_where_python_allows_it() -> None:
    built: list[asyncio.AbstractEventLoop] = []

    def factory() -> asyncio.AbstractEventLoop:
        """Build and remember a loop."""
        loop = asyncio.new_event_loop()
        built.append(loop)
        return loop

    if sys.version_info < (3, 12):
        with pytest.warns(UserWarning, match="loop_factory is ignored"):
            worker = AioThreadWorker(loop_factory=factory, run_now=False)
    else:
        worker = AioThreadWorker(loop_factory=factory, run_now=False)

    worker.run(wait=5)
    asyncio.run(worker.join(timeout=5))
    assert len(built) == (0 if sys.version_info < (3, 12) else 1)


def test_thread_death_during_startup_is_reported_and_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    boom = OSError("no loop")

    def run_loop(
        coro: Coroutine[Any, Any, Any], _factory: Callable[[], asyncio.AbstractEventLoop] | None
    ) -> None:
        """Fail before the loop ever runs."""
        coro.close()
        raise boom

    _patch_run_loop(monkeypatch, run_loop)
    worker = AioThreadWorker()

    with pytest.raises(RuntimeError, match="ended before it ever started") as caught:
        worker.wait_for_running(5)

    assert caught.value.__cause__ is boom
    assert worker.is_finished()
    assert "AioThreadWorker thread died" in caplog.text


def test_wait_for_running_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()

    def run_loop(
        coro: Coroutine[Any, Any, Any], _factory: Callable[[], asyncio.AbstractEventLoop] | None
    ) -> None:
        """Hold the thread in startup until released."""
        coro.close()
        release.wait(5)

    _patch_run_loop(monkeypatch, run_loop)
    worker = AioThreadWorker()

    try:
        with pytest.raises(TimeoutError, match="did not start running within 0.05"):
            worker.wait_for_running(0.05)
    finally:
        release.set()

    worker._thread.join(5)
    assert worker.is_finished()


def test_wait_for_running_refuses_the_workers_own_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[BaseException] = []
    worker: AioThreadWorker | None = None

    def run_loop(
        coro: Coroutine[Any, Any, Any], _factory: Callable[[], asyncio.AbstractEventLoop] | None
    ) -> None:
        """Wait for the worker from its own thread, before it is running."""
        coro.close()

        try:
            if worker is not None:
                worker.wait_for_running(1)
        except RuntimeError as e:
            seen.append(e)

    _patch_run_loop(monkeypatch, run_loop)
    worker = AioThreadWorker(run_now=False)
    worker.run()
    worker._thread.join(5)

    assert len(seen) == 1
    assert "from inside the worker's own thread" in str(seen[0])
