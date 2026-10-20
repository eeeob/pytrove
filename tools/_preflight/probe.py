"""Reaching a source and deciding what the answer means.

The only module here that touches the network. It never reads a tool's cache:
the checker judges the world, the janitor judges the disk, and keeping those
apart is what lets the check run before a first download and after a full
wipe alike.

The classification is the point of this module. Three things can go wrong and
only one of them is the source's fault:

    404 / 410          the resource is gone. a developer must remove it from
                       the tool, because every source has bespoke handling.
    200 + wrong shape  it was reshaped. the worst case, because a build would
                       consume it and produce silently wrong data.
    timeout / 5xx /    the network. accusing a source of dying because a
    429 / DNS          request timed out would hand someone a report asking
                       for surgery on working code.
"""

from __future__ import annotations

import hashlib
import socket
import ssl
import time
import urllib.error
import urllib.request
from typing import ClassVar

from .enums import ContractKind, State
from .models import Source, Verdict

# ============================== the prober ==============================

class Prober:
    """One HTTP (or git-refs) request per source, with retries and a verdict.

    A conditional request is made when the caller hands over a validator: the
    server answers 304 with no body, which costs nothing and is the most
    reliable "unchanged" signal there is. Deciding *which* validators are
    worth sending is `Lock.validators`, not this module -- a 304 earned
    against a weak one would be a claim about meaning rather than about
    bytes, and there would be no body left to re-read the shape of.
    """

    USER_AGENT: ClassVar[str] = "pytrove-preflight"
    TIMEOUT: ClassVar[int] = 30

    #: Three attempts, 1s then 2s apart. Enough to ride out a blip, short
    #: enough that eighteen sources still finish in well under a minute.
    ATTEMPTS: ClassVar[int] = 3
    BACKOFF: ClassVar[float] = 1.0

    #: Status codes that mean the resource itself is gone.
    GONE_CODES: ClassVar[frozenset[int]] = frozenset({404, 410})
    #: Codes that are somebody's capacity, not a dead source. 429 and 403 are
    #: expected here: the DMI step makes thousands of raw.githubusercontent
    #: requests and gets throttled for it.
    TRANSIENT_CODES: ClassVar[frozenset[int]] = frozenset(
        {403, 408, 425, 429, 500, 502, 503, 504, 509, 520, 522, 524})

    #: How much of a body to keep. Every source here is far below this; the
    #: cap only stops a redirect to something enormous from filling memory.
    MAX_BYTES: ClassVar[int] = 64 * 1024 * 1024

    #: Appended to a git remote to list its refs over HTTP, so a repository
    #: can be checked for liveness and its HEAD read without cloning it.
    GIT_REFS: ClassVar[str] = "/info/refs?service=git-upload-pack"

    def __init__(self, *, timeout: int | None = None) -> None:
        self.timeout = timeout or self.TIMEOUT

    # --- one request ------------------------------------------------------

    def request(
        self,
        url: str,
        *,
        etag: str = "",
        last_modified: str = "",
    ) -> tuple[int, bytes, dict[str, str]]:
        """Status, body and the headers worth keeping. Raises on failure."""

        headers = {"User-Agent": self.USER_AGENT, "Accept-Encoding": "identity"}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            body = response.read(self.MAX_BYTES)
            return response.status, body, {
                "etag": response.headers.get("ETag", "") or "",
                "last_modified": response.headers.get("Last-Modified", "") or "",
            }

    # --- classification ---------------------------------------------------

    @classmethod
    def classify(cls, exc: BaseException) -> tuple[State, int | None, str]:
        """(state, status, message) for a failed request.

        Re-raises an interrupt rather than classifying it. Catching
        `BaseException` around a request is right -- a probe must not be able
        to end a run of eighteen sources over one bad socket -- but swallowing
        Ctrl-C made it `flaky`, retried it twice with a sleep between, and
        then moved on to the next source, so the run could not be stopped at
        all without fifty-four keypresses.
        """

        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise exc

        if isinstance(exc, urllib.error.HTTPError):
            if exc.code == 304:                       # not an error at all
                return State.OK, 304, ""
            if exc.code in cls.GONE_CODES:
                return State.GONE, exc.code, f"HTTP {exc.code}"
            if exc.code in cls.TRANSIENT_CODES:
                return State.FLAKY, exc.code, f"HTTP {exc.code}"
            return State.CONTRACT_BROKEN, exc.code, f"HTTP {exc.code}"

        if isinstance(exc, urllib.error.URLError):
            reason = exc.reason
            if isinstance(reason, (socket.timeout, TimeoutError)):
                return State.FLAKY, None, "timeout"
            if isinstance(reason, ssl.SSLError):
                return State.FLAKY, None, f"TLS: {reason}"
            if isinstance(reason, socket.gaierror):
                return State.FLAKY, None, f"DNS: {reason.strerror or reason}"
            return State.FLAKY, None, str(reason)

        if isinstance(exc, (TimeoutError, socket.timeout)):
            return State.FLAKY, None, "timeout"

        return State.FLAKY, None, f"{type(exc).__name__}: {exc}"

    # --- the whole probe --------------------------------------------------

    def probe(
        self,
        source: Source,
        *,
        etag: str = "",
        last_modified: str = "",
    ) -> Verdict:
        """Reach one source. The verdict carries no comparison yet -- the
        state here is only OK (reached, or 304) or a failure; deciding
        `changed` needs the lock, and that is the checker's job."""

        url = source.target
        if source.contract and source.contract.kind is ContractKind.GIT_REFS:
            url = url.removesuffix("/") + self.GIT_REFS

        state, status, error = State.OK, None, ""
        body: bytes | None = None
        found: dict[str, str] = {}
        started = time.monotonic()
        attempt = 0

        for attempt in range(1, self.ATTEMPTS + 1):
            try:
                status, body, found = self.request(
                    url, etag=etag, last_modified=last_modified)
                state, error = State.OK, ""
                break
            except BaseException as exc:                  # noqa: BLE001
                state, status, error = self.classify(exc)
                if state is State.OK:                     # a 304 raised as HTTPError
                    body, found = None, {}
                    break
                if not state.is_transient or attempt == self.ATTEMPTS:
                    break
                time.sleep(self.BACKOFF * attempt)

        elapsed = int((time.monotonic() - started) * 1000)

        return Verdict(
            source_id=source.id,
            state=state,
            http_status=status,
            error=error,
            attempts=attempt,
            elapsed_ms=elapsed,
            body=body,
            sha256=hashlib.sha256(body).hexdigest() if body is not None else "",
            bytes_len=len(body) if body is not None else 0,
            etag=found.get("etag", ""),
            last_modified=found.get("last_modified", ""),
        )
