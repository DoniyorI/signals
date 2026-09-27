"""Test helpers importable from any test module (conftest re-exports them)."""

from collections.abc import Callable, Mapping

import httpx

Route = bytes | int | tuple[int, bytes] | Callable[[httpx.Request], httpx.Response]


class MockRouter:
    """An httpx MockTransport with a URL -> response table and a request log.

    Routes match the full URL first, then the URL without its query string.
    Unmatched URLs return 404.
    """

    def __init__(self, routes: Mapping[str, Route]):
        self.routes: dict[str, Route] = dict(routes)
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)
        self.client = httpx.Client(transport=self.transport)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        target = self.routes.get(url)
        if target is None:
            target = self.routes.get(url.split("?", 1)[0])
        if target is None:
            return httpx.Response(404, content=b"not found")
        if callable(target):
            return target(request)
        if isinstance(target, int):
            return httpx.Response(target, content=b"")
        if isinstance(target, tuple):
            status, body = target
            return httpx.Response(status, content=body)
        return httpx.Response(200, content=target)


class FakeClock:
    """Deterministic time for rate limiter and retry tests; sleep() advances both clocks."""

    def __init__(self) -> None:
        from datetime import datetime

        from signals.domain.calendars import ET

        self.now = datetime(2024, 6, 3, 10, 0, tzinfo=ET)
        self.mono = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.mono

    def now_et(self):
        return self.now

    def sleep(self, seconds: float) -> None:
        from datetime import timedelta

        self.slept.append(seconds)
        self.mono += seconds
        self.now += timedelta(seconds=seconds)
