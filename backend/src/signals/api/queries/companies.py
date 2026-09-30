"""Queries behind the `/companies/{ref}` endpoints."""

from collections.abc import Sequence
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from signals.api.pagination import SortKey, paginate, parse_float, parse_int
from signals.api.queries.common import issuer_ref, latest_close, rating_of, sec_url, today
from signals.api.schemas import (
    Bar,
    CompanyHeader,
    Form144Out,
    InsiderRosterRow,
    InstitutionRow,
    InstitutionsOut,
    Marker,
    NetBuying,
    OwnerRef,
    PriceSeriesOut,
    StakeOut,
    StakePerson,
)
from signals.db.models import (
    Decision,
    DecisionOwner,
    Filing,
    Form144Notice,
    FundManager,
    FundPositionChange,
    Issuer,
    Owner,
    OwnerRole,
    OwnershipStake,
    PriceDaily,
    ProfileStats,
    Security,
)
from signals.domain.tickers import (
    canonical_symbol,
    current_symbol,
    issuer_for_symbol,
    ticker_intervals,
)

# Calendar-day windows for net insider buying, distinct from the 21/63/126/252 *trading*-day
# horizons used for per-decision returns (Global Constraints): there is no seeded case that
# needs the two to agree, so plain calendar days keep "ending today" simple and robust to
# today not being a trading session. Ruling recorded in the E4 ledger entry.
NET_BUYING_DAYS: dict[str, int] = {"3m": 91, "6m": 182, "12m": 365}

INSTITUTION_KEYS = [
    SortKey("v", FundPositionChange.value_usd, desc=True, nullable=True, parse=parse_float),
    SortKey("f", FundPositionChange.filer_cik, desc=True, parse=parse_int),
]


# --------------------------------------------------------------------------- resolution
def resolve_company(session: Session, ref: str) -> int:
    """`ref` is a CIK (all digits) or a ticker: the current holder, else the latest one."""
    if ref.isdigit():
        cik = int(ref)
    else:
        symbol = canonical_symbol(ref)
        cik = issuer_for_symbol(session, symbol) if symbol else None
    if cik is None or session.get(Issuer, cik) is None:
        raise HTTPException(404, "company not found")
    return cik


def _former_tickers(session: Session, cik: int) -> list[str]:
    intervals = ticker_intervals(session, cik)
    current = current_symbol(session, cik)
    return [i.symbol for i in reversed(intervals) if i.symbol != current]


def _money(value: float | None) -> str:
    if not value:
        return "$0"
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:,.0f}"


def _owner_names(session: Session, decision_id: int) -> str:
    names = session.execute(
        select(Owner.name)
        .join(DecisionOwner, DecisionOwner.owner_cik == Owner.cik)
        .where(DecisionOwner.decision_id == decision_id)
        .order_by(Owner.cik)
    ).scalars()
    return ", ".join(names)


# --------------------------------------------------------------------------- header
def _net_buying(session: Session, cik: int, as_of: date) -> list[NetBuying]:
    out = []
    for window, days in NET_BUYING_DAYS.items():
        start = as_of - timedelta(days=days)
        rows = list(
            session.execute(
                select(Decision).where(
                    Decision.issuer_cik == cik,
                    Decision.first_trade_date >= start,
                    Decision.first_trade_date <= as_of,
                )
            ).scalars()
        )
        buys = [r for r in rows if r.direction == "buy"]
        sells = [r for r in rows if r.direction == "sell"]
        buys_usd = sum(r.value_usd or 0.0 for r in buys)
        sells_usd = sum(r.value_usd or 0.0 for r in sells)
        out.append(
            NetBuying(
                window=window,  # type: ignore[arg-type]
                buys_usd=buys_usd,
                sells_usd=sells_usd,
                net_usd=buys_usd - sells_usd,
                n_buyers=len({r.owner_group for r in buys}),
                n_sellers=len({r.owner_group for r in sells}),
            )
        )
    return out


def get_company_header(session: Session, ref: str) -> CompanyHeader:
    cik = resolve_company(session, ref)
    issuer = session.get(Issuer, cik)
    assert issuer is not None  # resolve_company already checked existence
    ticker = current_symbol(session, cik)
    close = latest_close(session, ticker) if ticker else None
    market_cap = (
        issuer.shares_outstanding * close[0]
        if (issuer.shares_outstanding is not None and close is not None)
        else None
    )
    return CompanyHeader(
        cik=cik,
        name=issuer.name,
        ticker=ticker,
        former_tickers=_former_tickers(session, cik),
        exchange=issuer.exchange,
        sector=issuer.sector,
        sic=issuer.sic,
        sic_description=issuer.sic_description,
        market_cap_usd=market_cap,
        latest_close=close[0] if close else None,
        latest_close_date=close[1] if close else None,
        net_buying=_net_buying(session, cik, today()),
    )


# --------------------------------------------------------------------------- prices
def _bars(session: Session, cik: int, start: date, end: date) -> list[Bar]:
    bars: list[Bar] = []
    for interval in ticker_intervals(session, cik):
        lo = max(start, interval.valid_from)
        hi = min(end, interval.valid_to) if interval.valid_to else end
        if lo > hi:
            continue
        rows = session.execute(
            select(PriceDaily)
            .where(
                PriceDaily.symbol == interval.symbol, PriceDaily.date >= lo, PriceDaily.date <= hi
            )
            .order_by(PriceDaily.date)
        ).scalars()
        bars.extend(
            Bar(
                date=row.date,
                open=row.open if row.open is not None else row.close,
                high=row.high if row.high is not None else row.close,
                low=row.low if row.low is not None else row.close,
                close=row.close,
                volume=row.volume,
                adj_close=row.adj_close,
            )
            for row in rows
        )
    bars.sort(key=lambda b: b.date)
    return bars


def _trade_markers(session: Session, cik: int, start: date, end: date) -> list[Marker]:
    decisions = list(
        session.execute(
            select(Decision).where(
                Decision.issuer_cik == cik,
                Decision.first_trade_date >= start,
                Decision.first_trade_date <= end,
            )
        ).scalars()
    )
    return [
        Marker(
            date=d.first_trade_date,
            kind=d.direction,  # type: ignore[arg-type]
            label=f"{'Buy' if d.direction == 'buy' else 'Sell'} {_money(d.value_usd)} "
            f"· {_owner_names(session, d.id)}",
            value_usd=d.value_usd,
            ref=d.first_accession,
        )
        for d in decisions
    ]


def _form144_markers(session: Session, cik: int, start: date, end: date) -> list[Marker]:
    rows = session.execute(
        select(Form144Notice, Filing.filed_date)
        .join(Filing, Filing.accession_no == Form144Notice.accession_no)
        .where(
            Form144Notice.issuer_cik == cik, Filing.filed_date >= start, Filing.filed_date <= end
        )
    ).all()
    return [
        Marker(
            date=filed_date,
            kind="form144",
            label=f"Form 144: {notice.seller_name or 'Unknown'} plans to sell",
            value_usd=notice.market_value_usd,
            ref=notice.accession_no,
        )
        for notice, filed_date in rows
    ]


def _stake_markers(session: Session, cik: int, start: date, end: date) -> list[Marker]:
    rows = session.execute(
        select(OwnershipStake, Filing.filed_date)
        .join(Filing, Filing.accession_no == OwnershipStake.accession_no)
        .where(OwnershipStake.issuer_cik == cik)
    ).all()
    out = []
    for stake, filed_date in rows:
        day = stake.event_date or filed_date
        if start <= day <= end:
            pct = f"{stake.percent_of_class * 100:.1f}%" if stake.percent_of_class else "an"
            out.append(
                Marker(
                    date=day,
                    kind="stake",
                    label=f"{stake.form_type}: {pct} stake",
                    value_usd=None,
                    ref=stake.accession_no,
                )
            )
    return out


def _cluster_markers(session: Session, cik: int, start: date, end: date) -> list[Marker]:
    decisions = list(
        session.execute(
            select(Decision)
            .where(
                Decision.issuer_cik == cik,
                Decision.badges.overlap(["cluster_buy"]),
                Decision.first_trade_date >= start,
                Decision.first_trade_date <= end,
            )
            .order_by(Decision.first_trade_date)
        ).scalars()
    )
    groups: list[list[Decision]] = []
    for d in decisions:
        if groups and (d.first_trade_date - groups[-1][-1].first_trade_date).days <= 14:
            groups[-1].append(d)
        else:
            groups.append([d])
    return [
        Marker(
            date=group[0].first_trade_date,
            kind="cluster",
            label=f"Cluster buy: {len({g.owner_group for g in group})} owners",
            value_usd=sum(g.value_usd or 0.0 for g in group),
            ref="",
        )
        for group in groups
    ]


def get_prices(
    session: Session, cik: int, *, start: date | None, end: date | None, markers: bool
) -> PriceSeriesOut:
    end = end or today()
    start = start or (end - timedelta(days=365 * 3))
    bars = _bars(session, cik, start, end)
    marker_list: list[Marker] = []
    if markers:
        marker_list = [
            *_trade_markers(session, cik, start, end),
            *_form144_markers(session, cik, start, end),
            *_stake_markers(session, cik, start, end),
            *_cluster_markers(session, cik, start, end),
        ]
    return PriceSeriesOut(symbol=current_symbol(session, cik), bars=bars, markers=marker_list)


# --------------------------------------------------------------------------- insiders roster
def _owner_issuer_stats(
    session: Session, cik: int, owner_cik: int, as_of: date
) -> tuple[date | None, float, int]:
    decisions = list(
        session.execute(
            select(Decision)
            .join(DecisionOwner, DecisionOwner.decision_id == Decision.id)
            .where(DecisionOwner.owner_cik == owner_cik, Decision.issuer_cik == cik)
        ).scalars()
    )
    n_decisions = len(decisions)
    last_trade_date = max((d.first_trade_date for d in decisions), default=None)
    start = as_of - timedelta(days=365)
    net = sum(
        (d.value_usd or 0.0) * (1 if d.direction == "buy" else -1)
        for d in decisions
        if start <= d.first_trade_date <= as_of
    )
    return last_trade_date, net, n_decisions


def list_company_insiders(
    session: Session, cik: int, *, include_10b5_1: bool
) -> list[InsiderRosterRow]:
    roles = list(session.execute(select(OwnerRole).where(OwnerRole.issuer_cik == cik)).scalars())
    owners = {
        o.cik: o
        for o in session.execute(
            select(Owner).where(Owner.cik.in_([r.owner_cik for r in roles]))
        ).scalars()
    }
    as_of = today()
    out = []
    for role in roles:
        owner = owners.get(role.owner_cik)
        if owner is None:
            continue
        stats = session.get(ProfileStats, ("insider", role.owner_cik, "filed", include_10b5_1))
        last_trade_date, net_12m, n_decisions = _owner_issuer_stats(
            session, cik, role.owner_cik, as_of
        )
        out.append(
            InsiderRosterRow(
                owner=OwnerRef(cik=owner.cik, name=owner.name),
                roles=list(role.roles or []),
                last_trade_date=last_trade_date,
                net_12m_usd=net_12m,
                n_decisions=n_decisions,
                rating=rating_of(stats),
            )
        )
    return out


# --------------------------------------------------------------------------- institutions
def get_institutions(
    session: Session, cik: int, *, period: date | None, cursor: str | None, limit: int
) -> InstitutionsOut:
    cusips = list(
        session.execute(select(Security.cusip).where(Security.issuer_cik == cik)).scalars()
    )
    periods_available = (
        sorted(
            set(
                session.execute(
                    select(FundPositionChange.period)
                    .where(FundPositionChange.cusip.in_(cusips))
                    .distinct()
                ).scalars()
            ),
            reverse=True,
        )
        if cusips
        else []
    )
    if not periods_available:
        return InstitutionsOut(
            period=None,
            periods_available=[],
            rows=[],
            total_value_usd=0.0,
            holders_count=0,
            new_count=0,
            exit_count=0,
            next_cursor=None,
        )
    target = period or periods_available[0]

    all_changes = list(
        session.execute(
            select(FundPositionChange).where(
                FundPositionChange.cusip.in_(cusips), FundPositionChange.period == target
            )
        ).scalars()
    )
    non_exit = [c for c in all_changes if c.change != "EXIT"]
    exit_count = len(all_changes) - len(non_exit)
    new_count = sum(1 for c in non_exit if c.change == "NEW")
    total_value = sum(c.value_usd or 0.0 for c in non_exit)

    stmt = select(FundPositionChange).where(
        FundPositionChange.cusip.in_(cusips),
        FundPositionChange.period == target,
        FundPositionChange.change != "EXIT",
    )
    rows, next_cursor = paginate(session, stmt, INSTITUTION_KEYS, cursor, limit)
    changes = [row[0] for row in rows]
    managers = {
        m.cik: m
        for m in session.execute(
            select(FundManager).where(FundManager.cik.in_({c.filer_cik for c in changes}))
        ).scalars()
    }
    out_rows = [
        InstitutionRow(
            fund=OwnerRef(
                cik=c.filer_cik,
                name=managers[c.filer_cik].name
                if c.filer_cik in managers
                else f"CIK {c.filer_cik}",
            ),
            shares=c.shares or 0.0,
            value_usd=c.value_usd or 0.0,
            weight_in_fund=c.weight,
            change=c.change,  # type: ignore[arg-type]
            shares_change_pct=c.shares_change_pct,
            is_tracked=managers[c.filer_cik].is_tracked if c.filer_cik in managers else False,
        )
        for c in changes
    ]
    return InstitutionsOut(
        period=target,
        periods_available=periods_available,
        rows=out_rows,
        total_value_usd=total_value,
        holders_count=len(non_exit),
        new_count=new_count,
        exit_count=exit_count,
        next_cursor=next_cursor,
    )


# --------------------------------------------------------------------------- stakes
def list_stakes(session: Session, cik: int, *, current_only: bool) -> list[StakeOut]:
    stmt = (
        select(OwnershipStake, Filing.filed_date)
        .join(Filing, Filing.accession_no == OwnershipStake.accession_no)
        .where(OwnershipStake.issuer_cik == cik)
    )
    if current_only:
        stmt = stmt.where(OwnershipStake.is_current.is_(True))
    stmt = stmt.order_by(Filing.filed_date.desc())
    rows = session.execute(stmt).all()
    out = []
    for stake, filed_date in rows:
        persons: Sequence[dict] = stake.reporting_persons or []
        link_cik = persons[0].get("cik") if persons else None
        out.append(
            StakeOut(
                accession_no=stake.accession_no,
                sec_url=sec_url(link_cik or cik, stake.accession_no),
                form_type=stake.form_type,
                filed_date=filed_date,
                event_date=stake.event_date,
                reporting_persons=[
                    StakePerson(
                        name=p["name"],
                        cik=p.get("cik"),
                        percent_of_class=p.get("percent_of_class"),
                        shares=p.get("aggregate_owned"),
                    )
                    for p in persons
                ],
                percent_of_class=stake.percent_of_class,
                is_activist=stake.is_activist,
                is_current=stake.is_current,
                purpose_excerpt=stake.purpose_excerpt,
            )
        )
    return out


# --------------------------------------------------------------------------- form 144
def list_company_form144(session: Session, cik: int, *, status: str | None) -> list[Form144Out]:
    rows = session.execute(
        select(Form144Notice, Filing.filed_date)
        .join(Filing, Filing.accession_no == Form144Notice.accession_no)
        .where(Form144Notice.issuer_cik == cik)
        .order_by(Filing.filed_date.desc())
    ).all()
    day = today()
    issuer = issuer_ref(session, cik)
    out = []
    for notice, filed_date in rows:
        if notice.matched_sale_accession is not None:
            notice_status = "matched"
        elif (
            notice.approx_sale_date is not None
            and notice.approx_sale_date + timedelta(days=90) < day
        ):
            notice_status = "expired"
        else:
            notice_status = "pending"
        if status is not None and notice_status != status:
            continue
        out.append(
            Form144Out(
                accession_no=notice.accession_no,
                sec_url=sec_url(notice.filer_cik or cik, notice.accession_no),
                filed_date=filed_date,
                issuer=issuer,
                seller_name=notice.seller_name,
                relationship=notice.relationship,
                shares_to_sell=notice.shares_to_sell,
                market_value_usd=notice.market_value_usd,
                approx_sale_date=notice.approx_sale_date,
                broker=notice.broker,
                plan_10b5_1_adopted=notice.plan_10b5_1_adopted,
                matched_sale_accession=notice.matched_sale_accession,
                status=notice_status,  # type: ignore[arg-type]
            )
        )
    return out
