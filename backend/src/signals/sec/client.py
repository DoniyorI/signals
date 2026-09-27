"""The one HTTP client for SEC EDGAR: User-Agent, rate limit, retries, 403 pause, archive."""

import os
import random
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from signals.config import Settings
from signals.domain.accession import filing_txt_url, normalize_accession
from signals.domain.calendars import now_et
from signals.logging import get_logger
from signals.sec.archive import RawArchive
from signals.sec.ratelimit import Priority, TokenBucket

log = get_logger(__name__)

MAX_RETRIES = 5
BLOCK_PAUSE = timedelta(minutes=10)


class SecError(Exception):
    """Base class for SEC access errors."""


class SecNotFoundError(SecError):
    def __init__(self, url: str) -> None:
        super().__init__(f"404 Not Found: {url}")
        self.url = url


class SecHttpError(SecError):
    def __init__(self, url: str, status: int | None) -> None:
        super().__init__(f"HTTP {status} after retries: {url}")
        self.url = url
        self.status = status


class SecBlockedError(SecError):
    def __init__(self, until: datetime) -> None:
        super().__init__(f"SEC access paused until {until.isoformat()}")
        self.until = until


def _retryable(status: int) -> bool:
    return status == 429 or status >= 500


class SecClient:
    def __init__(
        self,
        settings: Settings,
        *,
        http: httpx.Client | None = None,
        limiter: TokenBucket | None = None,
        archive: RawArchive | None = None,
        clock: Callable[[], datetime] = now_et,
        sleep: Callable[[float], None] = time.sleep,
        rand: Callable[[], float] = random.random,
        on_block: Callable[[datetime], None] | None = None,
    ) -> None:
        self._settings = settings
        self._http = http or httpx.Client(
            timeout=httpx.Timeout(30, connect=5), follow_redirects=True
        )
        self._limiter = limiter or TokenBucket(
            rate=settings.sec_rate_limit, capacity=max(2, int(settings.sec_rate_limit))
        )
        self._archive = archive
        self._clock = clock
        self._sleep = sleep
        self._rand = rand
        self._on_block = on_block
        self.blocked_until: datetime | None = None

    @property
    def _headers(self) -> dict[str, str]:
        return {"User-Agent": self._settings.sec_user_agent, "Accept-Encoding": "gzip, deflate"}

    def _check_blocked(self) -> None:
        if self.blocked_until is not None and self._clock() < self.blocked_until:
            raise SecBlockedError(self.blocked_until)

    def _block(self) -> SecBlockedError:
        self.blocked_until = self._clock() + BLOCK_PAUSE
        log.error("sec_blocked", until=self.blocked_until.isoformat())
        if self._on_block is not None:
            self._on_block(self.blocked_until)
        return SecBlockedError(self.blocked_until)

    def _backoff(self, attempt: int) -> None:
        self._sleep(min(30, 2 ** (attempt - 1)) + self._rand() * 0.5)

    def _request(self, url: str, priority: Priority, send: Callable[[], httpx.Response]):
        """Run `send` with limiter, retries and block handling; returns the final response."""
        last_status: int | None = None
        for attempt in range(MAX_RETRIES + 1):
            self._check_blocked()
            self._limiter.acquire(priority)
            try:
                resp = send()
            except httpx.TransportError as exc:
                log.warning("sec_transport_error", url=url, attempt=attempt, error=str(exc))
                last_status = None
            else:
                if resp.status_code == 404:
                    raise SecNotFoundError(url)
                if resp.status_code == 403:
                    raise self._block()
                if not _retryable(resp.status_code):
                    resp.raise_for_status()
                    return resp
                last_status = resp.status_code
                log.warning("sec_retryable_status", url=url, status=last_status, attempt=attempt)
            if attempt < MAX_RETRIES:
                self._backoff(attempt + 1)
        raise SecHttpError(url, last_status)

    def get(
        self,
        url: str,
        *,
        priority: Priority = Priority.BULK,
        archive_as: tuple[str, str, str] | None = None,
    ) -> bytes:
        resp = self._request(url, priority, lambda: self._http.get(url, headers=self._headers))
        body = resp.content
        if archive_as is not None and self._archive is not None:
            kind, key, ext = archive_as
            self._archive.put(kind, key, body, ext)
        return body

    def get_filing_txt(
        self, cik: int, accession: str, *, priority: Priority = Priority.BULK
    ) -> bytes:
        acc = normalize_accession(accession)
        url = filing_txt_url(cik, acc)
        return self.get(url, priority=priority, archive_as=("filing", acc, "txt"))

    def download(self, url: str, dest: Path, *, priority: Priority = Priority.BULK) -> Path:
        """Stream a (possibly multi-GB) body to disk, then atomically move it into place."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(dest.suffix + ".part")

        def send() -> httpx.Response:
            with self._http.stream("GET", url, headers=self._headers) as resp:
                if resp.status_code == 200:
                    with open(part, "wb") as f:
                        for chunk in resp.iter_bytes(1 << 20):
                            f.write(chunk)
                return resp

        try:
            self._request(url, priority, send)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        os.replace(part, dest)
        return dest


def build_sec_client(
    settings: Settings,
    *,
    archive: RawArchive,
    on_block: Callable[[datetime], None] | None = None,
) -> SecClient:
    limiter = TokenBucket(
        rate=settings.sec_rate_limit, capacity=max(2, int(settings.sec_rate_limit))
    )
    return SecClient(settings, limiter=limiter, archive=archive, on_block=on_block)
