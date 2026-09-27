from datetime import timedelta

import httpx
import pytest

from signals.sec.archive import RawArchive
from signals.sec.client import SecBlockedError, SecClient, SecHttpError, SecNotFoundError
from signals.sec.ratelimit import Priority, TokenBucket
from tests.support import MockRouter


def test_bucket_bursts_then_waits(fake_clock):
    b = TokenBucket(
        rate=8, capacity=8, clock=fake_clock.monotonic, sleep=fake_clock.sleep, reserve_for_live=0
    )
    for _ in range(8):
        b.acquire()
    assert fake_clock.slept == []
    b.acquire()
    assert fake_clock.slept == [pytest.approx(0.125)]


def test_bulk_leaves_reserve_for_live(fake_clock):
    b = TokenBucket(
        rate=8, capacity=2, clock=fake_clock.monotonic, sleep=fake_clock.sleep, reserve_for_live=1
    )
    b.acquire(Priority.BULK)  # 2 -> 1 token
    b.acquire(Priority.LIVE)  # live may take the last token
    assert fake_clock.slept == []
    b.acquire(Priority.BULK)  # bulk had to wait
    assert fake_clock.slept


def test_sends_user_agent_and_archives(settings, tmp_path):
    r = MockRouter({"https://www.sec.gov/x": b"hello"})
    c = SecClient(settings, http=r.client, archive=RawArchive(tmp_path), sleep=lambda s: None)
    assert c.get("https://www.sec.gov/x", archive_as=("filing", "k", "txt")) == b"hello"
    assert r.requests[0].headers["User-Agent"] == settings.sec_user_agent
    assert RawArchive(tmp_path).get("filing", "k") == b"hello"


def test_retries_429_with_backoff(settings):
    seq = iter([429, 429, 200])
    slept: list[float] = []
    r = MockRouter({"https://www.sec.gov/y": lambda req: httpx.Response(next(seq), content=b"ok")})
    c = SecClient(settings, http=r.client, sleep=slept.append, rand=lambda: 0.0)
    assert c.get("https://www.sec.gov/y") == b"ok"
    assert slept == [1.0, 2.0]


def test_gives_up_after_five_retries(settings):
    r = MockRouter({"https://www.sec.gov/z": 503})
    c = SecClient(settings, http=r.client, sleep=lambda s: None, rand=lambda: 0.0)
    with pytest.raises(SecHttpError):
        c.get("https://www.sec.gov/z")
    assert len(r.requests) == 6


def test_404_and_403_pause(settings, fake_clock):
    r = MockRouter({"https://www.sec.gov/nf": 404, "https://www.sec.gov/blocked": 403})
    blocked: list = []
    c = SecClient(
        settings,
        http=r.client,
        clock=fake_clock.now_et,
        sleep=fake_clock.sleep,
        on_block=blocked.append,
    )
    with pytest.raises(SecNotFoundError):
        c.get("https://www.sec.gov/nf")
    with pytest.raises(SecBlockedError):
        c.get("https://www.sec.gov/blocked")
    assert c.blocked_until == fake_clock.now_et() + timedelta(minutes=10) and blocked
    with pytest.raises(SecBlockedError):
        c.get("https://www.sec.gov/nf")
    assert len(r.requests) == 2  # nothing sent while blocked


def test_download_streams_to_file(settings, tmp_path):
    r = MockRouter({"https://www.sec.gov/big.zip": b"x" * 100_000})
    c = SecClient(settings, http=r.client, sleep=lambda s: None)
    out = c.download("https://www.sec.gov/big.zip", tmp_path / "big.zip")
    assert out.read_bytes() == b"x" * 100_000
    assert not (tmp_path / "big.zip.part").exists()


def test_archive_roundtrip_is_gzip(tmp_path):
    import gzip

    a = RawArchive(tmp_path)
    path = a.put("filing", "0000320193-24-000001", b"abc")
    assert path.name == "0000320193-24-000001.txt.gz"
    assert gzip.decompress(path.read_bytes()) == b"abc"
    assert a.exists("filing", "0000320193-24-000001") and a.read_path(path) == b"abc"
