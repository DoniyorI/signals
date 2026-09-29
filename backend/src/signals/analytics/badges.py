"""Decision badges (spec 9.8), recomputed from scratch for the decisions in scope.

- cluster_buy: 3 or more distinct owner groups make discretionary buys in one issuer with
  first trade dates within 14 calendar days. For each discretionary buy d the window is
  [d, d + 14 days]; when it holds 3 or more groups, every discretionary buy in it gets the
  badge. A joint filing's group counts once.
- late_filing: acceptance (its US Eastern date; the filing date when unknown) on or after the
  3rd SEC business day after the trade. The trade is the first trade date, or the deemed
  execution date when every first-day row of the decision carries one.
- first_buy_2y: a discretionary buy with no discretionary buy by the same owner group in the
  same issuer in the 730 days before it.
- dip_buy: a buy after the adjusted close fell 20% or more over the 60 sessions before the
  first trade date (the last close before the trade against the close 60 sessions earlier).
- big_stake: a buy that is high conviction (spec 9.7: stake change of 20% or more, $1M or
  more, or a new position).
- form144_matched: a sale whose owners include a Form 144 filer for the same issuer, with its
  first trade date within 90 days from the notice's filing date. Each notice links to its
  earliest matching sale (`form144_notices.matched_sale_accession`), or to none.
- top_exec: an owner holds a CEO, CFO or President role at the issuer (`owner_roles`).
"""

import bisect
from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Select, and_, any_, case, func, select, update
from sqlalchemy.orm import InstrumentedAttribute, Session

from signals.analytics.allocation import insider_high_conviction
from signals.analytics.series import IssuerSeries, load_issuer_series
from signals.db.models import Decision, Filing, Form144Notice, InsiderTransaction, OwnerRole
from signals.domain.calendars import (
    ET,
    add_trading_days,
    prev_trading_day,
    sec_business_days_between,
)
from signals.domain.owner_group import owner_group_ciks
from signals.domain.types import Badge, PlanFlag, Role

CLUSTER_WINDOW_DAYS = 14
CLUSTER_MIN_GROUPS = 3
LATE_SEC_BUSINESS_DAYS = 3
FIRST_BUY_LOOKBACK_DAYS = 730
DIP_LOOKBACK_SESSIONS = 60
DIP_DROP = 0.20
FORM144_WINDOW_DAYS = 90
TOP_EXEC_ROLES = (Role.CEO.value, Role.CFO.value, Role.PRESIDENT.value)
# Prices load from a little before the earliest dip reference day, in case it has no bar.
DIP_PRICE_BUFFER_DAYS = 10
# "20% or more" includes exactly 20% despite floating-point rounding.
_RELATIVE_TOLERANCE = 1e-9

_DECISION_COLUMNS = (
    Decision.id,
    Decision.owner_group,
    Decision.issuer_cik,
    Decision.direction,
    Decision.is_planned,
    Decision.first_trade_date,
    Decision.accepted_at,
    Decision.filed_date,
    Decision.stake_change_pct,
    Decision.value_usd,
    Decision.is_new_position,
    Decision.first_accession,
    Decision.badges,
)


def _scoped[*Ts](
    query: Select[*Ts], column: InstrumentedAttribute[Any], issuer_ciks: Collection[int] | None
) -> Select[*Ts]:
    return query if issuer_ciks is None else query.where(column.in_(list(issuer_ciks)))


def _discretionary_buys(decisions: Iterable[Any]) -> list[Any]:
    return [d for d in decisions if d.direction == "buy" and not d.is_planned]


# ----------------------------------------------------------------------------- cluster_buy
def _clusters(decisions: Sequence[Any]) -> set[int]:
    by_issuer: dict[int, list[Any]] = defaultdict(list)
    for d in _discretionary_buys(decisions):
        by_issuer[d.issuer_cik].append(d)
    members: set[int] = set()
    window = timedelta(days=CLUSTER_WINDOW_DAYS)
    for buys in by_issuer.values():
        buys.sort(key=lambda d: (d.first_trade_date, d.id))
        days = [d.first_trade_date for d in buys]
        for day in sorted(set(days)):
            inside = buys[bisect.bisect_left(days, day) : bisect.bisect_right(days, day + window)]
            if len({d.owner_group for d in inside}) >= CLUSTER_MIN_GROUPS:
                members.update(d.id for d in inside)
    return members


# ----------------------------------------------------------------------------- late_filing
def _public_day(decision: Any) -> date | None:
    if decision.accepted_at is not None:
        return decision.accepted_at.astimezone(ET).date()
    return decision.filed_date


def _deemed_starts(session: Session, issuer_ciks: Collection[int] | None) -> dict[int, date]:
    """Decision id -> the earliest execution date of its first-day rows, counting each row's
    deemed execution date, for the decisions with a deemed date on a first-day row."""
    tx = InsiderTransaction
    deemed = (
        select(tx.issuer_cik, tx.owner_group, tx.transaction_date)
        .where(
            tx.deemed_execution_date.is_not(None),
            tx.table_kind == "nonderiv",
            tx.superseded_by.is_(None),
        )
        .distinct()
    )
    keys = _scoped(deemed, tx.issuer_cik, issuer_ciks).subquery()
    query = (
        select(Decision.id, func.min(func.coalesce(tx.deemed_execution_date, tx.transaction_date)))
        .join(
            keys,
            and_(
                keys.c.issuer_cik == Decision.issuer_cik,
                keys.c.owner_group == Decision.owner_group,
                keys.c.transaction_date == Decision.first_trade_date,
            ),
        )
        .join(
            tx,
            and_(
                tx.issuer_cik == Decision.issuer_cik,
                tx.owner_group == Decision.owner_group,
                tx.transaction_date == Decision.first_trade_date,
                tx.accession_no == any_(Decision.accessions),
                tx.code == case((Decision.direction == "buy", "P"), else_="S"),
                tx.table_kind == "nonderiv",
                tx.superseded_by.is_(None),
                (tx.plan_10b5_1 != PlanFlag.NONE.value) == Decision.is_planned,
            ),
        )
        .group_by(Decision.id)
    )
    return {decision_id: start for decision_id, start in session.execute(query)}


def _late_filings(
    session: Session, decisions: Sequence[Any], issuer_ciks: Collection[int] | None
) -> set[int]:
    deemed = _deemed_starts(session, issuer_ciks)
    late: set[int] = set()
    for d in decisions:
        public = _public_day(d)
        if public is None:
            continue
        executed = max(d.first_trade_date, deemed.get(d.id, d.first_trade_date))
        if sec_business_days_between(executed, public) >= LATE_SEC_BUSINESS_DAYS:
            late.add(d.id)
    return late


# ----------------------------------------------------------------------------- first_buy_2y
def _first_buys(decisions: Sequence[Any]) -> set[int]:
    by_owner: dict[tuple[int, str], list[Any]] = defaultdict(list)
    for d in _discretionary_buys(decisions):
        by_owner[(d.issuer_cik, d.owner_group)].append(d)
    lookback = timedelta(days=FIRST_BUY_LOOKBACK_DAYS)
    first: set[int] = set()
    for buys in by_owner.values():
        buys.sort(key=lambda d: (d.first_trade_date, d.id))
        previous: date | None = None
        for d in buys:
            if previous is None or previous < d.first_trade_date - lookback:
                first.add(d.id)
            previous = d.first_trade_date
    return first


# ----------------------------------------------------------------------------- dip_buy
def _dip_span(first_trade_date: date) -> tuple[date, date]:
    """(the session 60 sessions before the last pre-trade session, that pre-trade session)."""
    pre_trade = prev_trading_day(first_trade_date)
    return add_trading_days(pre_trade, -DIP_LOOKBACK_SESSIONS), pre_trade


def _close_on_or_before(series: IssuerSeries, day: date) -> float | None:
    bar = series.last_on_or_before(day)
    return None if bar is None else series.close_adj(bar)


def _dip_buys(session: Session, decisions: Sequence[Any]) -> set[int]:
    by_issuer: dict[int, list[Any]] = defaultdict(list)
    for d in decisions:
        if d.direction == "buy":
            by_issuer[d.issuer_cik].append(d)
    dips: set[int] = set()
    for issuer_cik, buys in by_issuer.items():
        spans = {d.id: _dip_span(d.first_trade_date) for d in buys}
        start = min(before for before, _ in spans.values()) - timedelta(days=DIP_PRICE_BUFFER_DAYS)
        end = max(pre_trade for _, pre_trade in spans.values())
        series = load_issuer_series(session, issuer_cik, start, end)
        for decision_id, (before, pre_trade) in spans.items():
            then, now = _close_on_or_before(series, before), _close_on_or_before(series, pre_trade)
            if then is None or now is None or not then > 0:
                continue
            if now <= then * (1.0 - DIP_DROP) * (1.0 + _RELATIVE_TOLERANCE):
                dips.add(decision_id)
    return dips


# ----------------------------------------------------------------------------- form144_matched
def _form144_matches(
    session: Session, decisions: Sequence[Any], issuer_ciks: Collection[int] | None
) -> set[int]:
    """Sale decisions pre-announced by a Form 144; also relinks each notice in scope to its
    earliest matching sale (or to none)."""
    sales: dict[tuple[int, int], list[Any]] = defaultdict(list)  # (issuer, owner) -> sales
    for d in decisions:
        if d.direction == "sell":
            for owner in owner_group_ciks(d.owner_group):
                sales[(d.issuer_cik, owner)].append(d)
    for group in sales.values():
        group.sort(key=lambda d: (d.first_trade_date, d.first_accession, d.id))

    notices = session.execute(
        _scoped(
            select(
                Form144Notice.accession_no,
                Form144Notice.filer_cik,
                Form144Notice.issuer_cik,
                Form144Notice.matched_sale_accession,
                Filing.filed_date,
            ).join(Filing, Filing.accession_no == Form144Notice.accession_no),
            Form144Notice.issuer_cik,
            issuer_ciks,
        )
    ).all()
    matched: set[int] = set()
    links: list[dict[str, Any]] = []
    window = timedelta(days=FORM144_WINDOW_DAYS)
    for notice in notices:
        candidates = sales.get((notice.issuer_cik, notice.filer_cik), [])
        inside = [
            d
            for d in candidates
            if notice.filed_date <= d.first_trade_date <= notice.filed_date + window
        ]
        matched.update(d.id for d in inside)
        link = inside[0].first_accession if inside else None
        if link != notice.matched_sale_accession:
            links.append({"accession_no": notice.accession_no, "matched_sale_accession": link})
    if links:
        session.execute(update(Form144Notice), links)
    return matched


# ----------------------------------------------------------------------------- top_exec
def _top_execs(
    session: Session, decisions: Sequence[Any], issuer_ciks: Collection[int] | None
) -> set[int]:
    query = select(OwnerRole.owner_cik, OwnerRole.issuer_cik).where(
        OwnerRole.roles.overlap(list(TOP_EXEC_ROLES))
    )
    execs = {
        (owner, issuer)
        for owner, issuer in session.execute(_scoped(query, OwnerRole.issuer_cik, issuer_ciks))
    }
    return {
        d.id
        for d in decisions
        if any((owner, d.issuer_cik) in execs for owner in owner_group_ciks(d.owner_group))
    }


# ----------------------------------------------------------------------------- entry point
def compute_badges(session: Session, *, issuer_ciks: Collection[int] | None = None) -> int:
    """Recompute `decisions.badges` for the issuers (or all) and relink their Form 144
    notices. Returns the number of decisions whose badges changed."""
    decisions = session.execute(
        _scoped(select(*_DECISION_COLUMNS), Decision.issuer_cik, issuer_ciks).order_by(Decision.id)
    ).all()
    earned: dict[int, set[Badge]] = {d.id: set() for d in decisions}

    def award(badge: Badge, ids: Iterable[int]) -> None:
        for decision_id in ids:
            earned[decision_id].add(badge)

    award(Badge.CLUSTER_BUY, _clusters(decisions))
    award(Badge.LATE_FILING, _late_filings(session, decisions, issuer_ciks))
    award(Badge.FIRST_BUY_2Y, _first_buys(decisions))
    award(Badge.DIP_BUY, _dip_buys(session, decisions))
    award(
        Badge.BIG_STAKE,
        (
            d.id
            for d in decisions
            if d.direction == "buy"
            and insider_high_conviction(d.stake_change_pct, d.value_usd, d.is_new_position)
        ),
    )
    award(Badge.FORM144_MATCHED, _form144_matches(session, decisions, issuer_ciks))
    award(Badge.TOP_EXEC, _top_execs(session, decisions, issuer_ciks))

    changes: list[dict[str, Any]] = []
    for d in decisions:
        badges = [badge.value for badge in Badge if badge in earned[d.id]]
        if badges != list(d.badges):
            changes.append({"id": d.id, "badges": badges})
    if changes:
        session.execute(update(Decision), changes)
    return len(changes)
