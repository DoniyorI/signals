"""Analytics runs (spec 9.10): rebuild the derived tables in dependency order.

A full run rebuilds everything as of a date; an incremental run rebuilds the issuers and
owners touched by new filings, then still refreshes every insider rating, because
percentiles are relative. The steps, grouped into transactions so readers never see one
table rebuilt without the tables tied to it:

1. `positions`                                            (one transaction)
2. `decisions` -> 3. `decision_returns` -> 4. badges -> 5. insider `profile_stats` and
   `profile_windows`, all linked by decision ids              (one transaction)
6. full runs only: workstream B's `fund_position_changes`, then the fund curves
   (`fund_nav_daily`), windows and stats                   (one transaction)
7. `feed_items` badges, sector and market cap -> 8. the `analytics_version` stamp, which
   also retires cached insider curves                      (one transaction)

Every transaction starts by taking one Postgres advisory lock, so overlapping runs (the
nightly run, a backfill step, incremental requests from the live feed) apply their
delete-and-insert steps one at a time instead of duplicating rows.
"""

import time
from collections.abc import Callable, Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from signals.analytics.badges import compute_badges
from signals.analytics.curves import ANALYTICS_VERSION_KEY
from signals.analytics.decisions import build_decisions
from signals.analytics.positions import build_positions
from signals.analytics.returns import compute_decision_returns
from signals.analytics.series import load_issuer_series
from signals.analytics.stats import compute_fund_stats, compute_profile_stats
from signals.db.models import Decision, DecisionOwner, FeedItem, Issuer
from signals.db.session import session_scope
from signals.domain.appstate import set_state
from signals.domain.calendars import now_et
from signals.domain.types import Badge

ANALYTICS_LOCK_KEY = 0x5349_474E_414C_5301  # pg_advisory_xact_lock key shared by every run
# A company without a bar in this many days before as_of has no current market cap.
MARKET_CAP_LOOKBACK_DAYS = 14

Progress = Callable[[str], None]


@dataclass(frozen=True)
class RunResult:
    """decisions and returns: rows rebuilt; badges: decisions whose badges changed;
    insider_profiles and fund_profiles: `profile_stats` rows written."""

    decisions: int
    returns: int
    badges: int
    insider_profiles: int
    fund_profiles: int
    seconds: float


def _fund_changes(session: Session) -> int:
    """Workstream B's quarter-over-quarter 13F changes (`fund_position_changes`)."""
    from signals.ingest.fund_changes import (  # pyright: ignore[reportMissingImports]
        compute_fund_changes,
    )

    return compute_fund_changes(session)


@contextmanager
def _locked(session_factory: Callable[[], Session]) -> Iterator[Session]:
    """One committed transaction, serialized with every other analytics run."""
    with session_scope(session_factory) as session:
        session.execute(select(func.pg_advisory_xact_lock(ANALYTICS_LOCK_KEY)))
        yield session


def _stamp(session: Session, as_of: date) -> None:
    set_state(
        session, ANALYTICS_VERSION_KEY, {"as_of": as_of.isoformat(), "run_at": now_et().isoformat()}
    )


# ----------------------------------------------------------------------------- feed items
_FEED_BADGES_SQL = """
WITH earned AS (
    SELECT acc AS accession_no,
           array_agg(badge ORDER BY array_position(CAST(:badge_order AS text[]), badge))
               AS badges
    FROM (
        SELECT DISTINCT acc, badge
        FROM decisions d
        CROSS JOIN LATERAL unnest(d.accessions) AS acc
        CROSS JOIN LATERAL unnest(d.badges) AS badge
        {decisions}
    ) pairs
    GROUP BY acc
),
wanted AS (
    SELECT f.accession_no, coalesce(e.badges, CAST('{{}}' AS text[])) AS badges
    FROM feed_items f
    LEFT JOIN earned e ON e.accession_no = f.accession_no
    {feed}
)
UPDATE feed_items f
SET badges = w.badges, updated_at = now()
FROM wanted w
WHERE f.accession_no = w.accession_no AND f.badges IS DISTINCT FROM w.badges
"""

_FEED_ISSUER_SQL = """
UPDATE feed_items
SET sector = CAST(:sector AS text), market_cap_usd = CAST(:cap AS double precision),
    updated_at = now()
WHERE issuer_cik = :cik
  AND (sector IS DISTINCT FROM CAST(:sector AS text)
       OR market_cap_usd IS DISTINCT FROM CAST(:cap AS double precision))
"""


def _latest_close(session: Session, issuer_cik: int, as_of: date) -> float | None:
    series = load_issuer_series(
        session, issuer_cik, as_of - timedelta(days=MARKET_CAP_LOOKBACK_DAYS), as_of
    )
    last = series.last_date()
    return None if last is None else series.close_adj(last)


def refresh_feed_items(
    session: Session, *, issuer_ciks: Collection[int] | None = None, as_of: date
) -> None:
    """For the feed items of the issuers (or all): badges = the union of the badges of the
    decisions whose accessions include the item's; sector = the issuer's sector;
    market_cap_usd = shares outstanding x the latest adjusted close on or before `as_of`
    (none without a bar in the last MARKET_CAP_LOOKBACK_DAYS days)."""
    params: dict[str, Any] = {"badge_order": [badge.value for badge in Badge]}
    decisions = feed = ""
    issuers = select(FeedItem.issuer_cik).where(FeedItem.issuer_cik.is_not(None)).distinct()
    if issuer_ciks is not None:
        params["issuers"] = sorted({int(c) for c in issuer_ciks})
        decisions = "WHERE d.issuer_cik = ANY(CAST(:issuers AS bigint[]))"
        feed = "WHERE f.issuer_cik = ANY(CAST(:issuers AS bigint[]))"
        issuers = issuers.where(FeedItem.issuer_cik.in_(params["issuers"]))
    session.execute(text(_FEED_BADGES_SQL.format(decisions=decisions, feed=feed)), params)

    ciks = [int(c) for c in session.scalars(issuers) if c is not None]
    if not ciks:
        return
    facts = {
        cik: (sector, shares)
        for cik, sector, shares in session.execute(
            select(Issuer.cik, Issuer.sector, Issuer.shares_outstanding).where(Issuer.cik.in_(ciks))
        )
    }
    updates: list[dict[str, Any]] = []
    for cik in ciks:
        sector, shares = facts.get(cik, (None, None))
        close = _latest_close(session, cik, as_of) if shares else None
        cap = shares * close if shares and close else None
        updates.append({"cik": cik, "sector": sector, "cap": cap})
    session.execute(text(_FEED_ISSUER_SQL), updates)


# ----------------------------------------------------------------------------- runs
def run_full(
    session_factory: Callable[[], Session],
    *,
    as_of: date,
    include_funds: bool = True,
    progress: Progress | None = None,
) -> RunResult:
    """Rebuild every derived table as of `as_of` (steps and transactions: module docstring).
    `progress` is called with each step's name as it starts."""
    started = time.monotonic()
    report = progress or (lambda step: None)
    with _locked(session_factory) as session:
        report("positions")
        build_positions(session)
    with _locked(session_factory) as session:
        report("decisions")
        decisions = build_decisions(session)
        report("returns")
        returns = compute_decision_returns(session, as_of=as_of)
        report("badges")
        badges = compute_badges(session)
        report("insider_stats")
        insider_profiles = compute_profile_stats(session, as_of=as_of)
    fund_profiles = 0
    if include_funds:
        with _locked(session_factory) as session:
            report("funds")
            _fund_changes(session)
            fund_profiles = compute_fund_stats(session, as_of=as_of)
    with _locked(session_factory) as session:
        report("feed")
        refresh_feed_items(session, as_of=as_of)
        report("version")
        _stamp(session, as_of)
    return RunResult(
        decisions, returns, badges, insider_profiles, fund_profiles, time.monotonic() - started
    )


def _owners_of(session: Session, issuer_ciks: Collection[int]) -> set[int]:
    """Owners with a decision in the issuers."""
    if not issuer_ciks:
        return set()
    return set(
        session.scalars(
            select(DecisionOwner.owner_cik)
            .join(Decision, Decision.id == DecisionOwner.decision_id)
            .where(Decision.issuer_cik.in_(list(issuer_ciks)))
            .distinct()
        )
    )


def run_incremental(
    session_factory: Callable[[], Session],
    *,
    issuer_ciks: Collection[int],
    owner_ciks: Collection[int],
    as_of: date,
    progress: Progress | None = None,
) -> RunResult:
    """The full run's steps limited to the issuers (decisions, returns, badges, feed items)
    and owners (positions); profile stats cover the given owners plus every owner of those
    issuers' decisions before and after the rebuild, and all insider ratings are refreshed.
    Fund curves are left to the full run. Empty scopes do nothing."""
    started = time.monotonic()
    report = progress or (lambda step: None)
    issuers = sorted({int(c) for c in issuer_ciks})
    owners = sorted({int(c) for c in owner_ciks})
    if not issuers and not owners:
        return RunResult(0, 0, 0, 0, 0, time.monotonic() - started)
    with _locked(session_factory) as session:
        report("positions")
        build_positions(session, owner_ciks=owners)
    with _locked(session_factory) as session:
        touched = _owners_of(session, issuers)
        report("decisions")
        decisions = build_decisions(session, issuer_ciks=issuers)
        ids = list(session.scalars(select(Decision.id).where(Decision.issuer_cik.in_(issuers))))
        report("returns")
        returns = compute_decision_returns(session, decision_ids=ids, as_of=as_of)
        report("badges")
        badges = compute_badges(session, issuer_ciks=issuers)
        report("insider_stats")
        touched |= _owners_of(session, issuers)
        insider_profiles = compute_profile_stats(
            session, owner_ciks=sorted(touched | set(owners)), as_of=as_of
        )
    with _locked(session_factory) as session:
        report("feed")
        refresh_feed_items(session, issuer_ciks=issuers, as_of=as_of)
        report("version")
        _stamp(session, as_of)
    return RunResult(decisions, returns, badges, insider_profiles, 0, time.monotonic() - started)
