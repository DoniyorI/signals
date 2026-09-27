"""Thread-safe token bucket shared by every SEC request in the process.

SEC fair access allows at most 10 requests/second; we cap lower. Bulk work must leave
`reserve_for_live` tokens untouched so the live poller never waits behind a backfill.
"""

import threading
import time
from collections.abc import Callable
from enum import Enum


class Priority(Enum):
    LIVE = "live"
    BULK = "bulk"


class TokenBucket:
    def __init__(
        self,
        rate: float,
        capacity: int,
        *,
        reserve_for_live: int = 1,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if capacity < 1 + reserve_for_live:
            raise ValueError("capacity must exceed the live reserve")
        self.rate = float(rate)
        self.capacity = float(capacity)
        self.reserve_for_live = reserve_for_live
        self._clock = clock
        self._sleep = sleep
        self._tokens = float(capacity)
        self._last = clock()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
        self._last = now

    def acquire(self, priority: Priority = Priority.BULK) -> None:
        need = 1.0 if priority is Priority.LIVE else 1.0 + self.reserve_for_live
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= need:
                    self._tokens -= 1.0
                    return
                wait = (need - self._tokens) / self.rate
            self._sleep(wait)
