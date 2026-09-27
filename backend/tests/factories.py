"""Row builders for tests. Keyword-only arguments with sensible defaults; each flushes."""

from collections.abc import Sequence
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from signals.db.models import (
    Decision,
    DecisionOwner,
    DecisionReturn,
    Filing,
    FilingOwner,
    FundFiling,
    FundManager,
    FundPosition,
    InsiderHolding,
    InsiderTransaction,
    Issuer,
    Owner,
    PriceDaily,
    ProfileStats,
    Security,
    Ticker,
)
from signals.domain.calendars import ET, trading_days
from signals.domain.owner_group import owner_group_key


def make_issuer(
    session: Session,
    *,
    cik: int = 1000001,
    name: str = "Acme Corp",
    sic: int | None = 3571,
    sector: str | None = "Technology",
    ticker: str | None = "ACME",
    ticker_from: date = date(2010, 1, 1),
    shares_outstanding: float | None = 1e9,
) -> Issuer:
    issuer = Issuer(
        cik=cik, name=name, sic=sic, sector=sector, shares_outstanding=shares_outstanding
    )
    session.add(issuer)
    session.flush()
    if ticker:
        session.add(Ticker(issuer_cik=cik, symbol=ticker, valid_from=ticker_from, source="test"))
        session.flush()
    return issuer


def make_owner(
    session: Session, *, cik: int = 2000001, name: str = "Doe Jane", owner_type: str = "person"
) -> Owner:
    owner = Owner(cik=cik, name=name, owner_type=owner_type)
    session.add(owner)
    session.flush()
    return owner


def make_filing(
    session: Session,
    *,
    accession_no: str = "0002000001-24-000001",
    form_type: str = "4",
    issuer_cik: int | None = 1000001,
    primary_cik: int = 2000001,
    filed_date: date = date(2024, 1, 16),
    accepted_at: datetime | None = datetime(2024, 1, 16, 16, 30, tzinfo=ET),
    owners: Sequence[int] = (2000001,),
    source: str = "feed",
    parse_status: str = "parsed",
) -> Filing:
    filing = Filing(
        accession_no=accession_no,
        form_type=form_type,
        issuer_cik=issuer_cik,
        primary_cik=primary_cik,
        filed_date=filed_date,
        accepted_at=accepted_at,
        accepted_at_source="sgml" if accepted_at else "missing",
        is_amendment=form_type.endswith("/A"),
        source=source,
        parse_status=parse_status,
    )
    session.add(filing)
    session.flush()
    for cik in owners:
        if session.get(Owner, cik) is None:
            session.add(Owner(cik=cik, name=f"Owner {cik}", owner_type="person"))
            session.flush()
        session.add(FilingOwner(accession_no=accession_no, owner_cik=cik))
    session.flush()
    return filing


def make_transaction(
    session: Session,
    *,
    accession_no: str,
    issuer_cik: int = 1000001,
    owner_ciks: Sequence[int] = (2000001,),
    code: str = "P",
    transaction_date: date = date(2024, 1, 12),
    shares: float | None = 1000.0,
    price: float | None = 10.0,
    shares_owned_after: float | None = 11000.0,
    plan_10b5_1: str = "none",
    table_kind: str = "nonderiv",
    row_no: int = 1,
    superseded_by: str | None = None,
) -> InsiderTransaction:
    tx = InsiderTransaction(
        accession_no=accession_no,
        table_kind=table_kind,
        row_no=row_no,
        issuer_cik=issuer_cik,
        owner_group=owner_group_key(owner_ciks),
        transaction_date=transaction_date,
        code=code,
        shares=shares,
        price=price,
        value_usd=shares * price if shares is not None and price is not None else None,
        acquired_disposed={"P": "A", "S": "D"}.get(code),
        shares_owned_after=shares_owned_after,
        direct_indirect="D",
        plan_10b5_1=plan_10b5_1,
        superseded_by=superseded_by,
    )
    session.add(tx)
    session.flush()
    return tx


def make_holding(
    session: Session,
    *,
    accession_no: str,
    issuer_cik: int = 1000001,
    owner_ciks: Sequence[int] = (2000001,),
    shares_owned: float | None = 5000.0,
    row_no: int = 1,
) -> InsiderHolding:
    holding = InsiderHolding(
        accession_no=accession_no,
        table_kind="nonderiv",
        row_no=row_no,
        issuer_cik=issuer_cik,
        owner_group=owner_group_key(owner_ciks),
        security_title="Common Stock",
        shares_owned=shares_owned,
        direct_indirect="D",
    )
    session.add(holding)
    session.flush()
    return holding


def make_prices(
    session: Session,
    symbol: str,
    start: date,
    closes: Sequence[float],
    *,
    opens: Sequence[float] | None = None,
    adj_factors: Sequence[float] | None = None,
    source: str = "test",
) -> None:
    """One row per NYSE trading day starting at `start` (or the next trading day)."""
    days = trading_days(start, start + timedelta(days=len(closes) * 2 + 10))[: len(closes)]
    for i, day in enumerate(days):
        close = float(closes[i])
        factor = float(adj_factors[i]) if adj_factors is not None else 1.0
        opened = float(opens[i]) if opens is not None else close
        session.add(
            PriceDaily(
                symbol=symbol,
                date=day,
                open=opened,
                high=max(opened, close),
                low=min(opened, close),
                close=close,
                volume=1_000_000.0,
                adj_close=close * factor,
                source=source,
            )
        )
    session.flush()


def make_fund_manager(
    session: Session,
    *,
    cik: int = 3000001,
    name: str = "Example Capital Management",
    is_tracked: bool = True,
) -> FundManager:
    manager = FundManager(cik=cik, name=name, is_tracked=is_tracked)
    session.add(manager)
    session.flush()
    return manager


def make_fund_filing(
    session: Session,
    *,
    accession_no: str = "0003000001-24-000001",
    filer_cik: int = 3000001,
    period: date = date(2024, 3, 31),
    filed_date: date = date(2024, 5, 15),
    accepted_at: datetime | None = None,
    submission_type: str = "13F-HR",
    amendment_type: str | None = None,
) -> FundFiling:
    session.add(
        Filing(
            accession_no=accession_no,
            form_type=submission_type,
            primary_cik=filer_cik,
            filed_date=filed_date,
            accepted_at=accepted_at,
            accepted_at_source="sgml" if accepted_at else "missing",
            period_of_report=period,
            is_amendment=submission_type.endswith("/A"),
            source="test",
            parse_status="parsed",
        )
    )
    session.flush()
    fund_filing = FundFiling(
        accession_no=accession_no,
        filer_cik=filer_cik,
        period_of_report=period,
        filed_date=filed_date,
        accepted_at=accepted_at,
        submission_type=submission_type,
        amendment_type=amendment_type,
    )
    session.add(fund_filing)
    session.flush()
    return fund_filing


def make_fund_position(
    session: Session,
    *,
    accession_no: str,
    filer_cik: int = 3000001,
    period: date = date(2024, 3, 31),
    cusip: str = "000000AA1",
    shares: float = 100.0,
    value_usd: float = 1000.0,
    put_call: str = "",
    is_effective: bool = True,
) -> FundPosition:
    position = FundPosition(
        period=period,
        accession_no=accession_no,
        cusip=cusip,
        put_call=put_call,
        filer_cik=filer_cik,
        shares=shares,
        sh_prn="SH",
        value_usd=value_usd,
        is_effective=is_effective,
    )
    session.add(position)
    session.flush()
    return position


def make_security(
    session: Session,
    *,
    cusip: str = "000000AA1",
    issuer_cik: int | None = 1000001,
    ticker: str | None = "ACME",
    name: str = "ACME CORP",
) -> Security:
    security = Security(
        cusip=cusip,
        issuer_cik=issuer_cik,
        ticker=ticker,
        name=name,
        map_source="openfigi",
        map_status="mapped",
    )
    session.add(security)
    session.flush()
    return security


def make_decision(
    session: Session,
    *,
    owner_ciks: Sequence[int] = (2000001,),
    issuer_cik: int = 1000001,
    direction: str = "buy",
    first_trade_date: date = date(2024, 1, 12),
    value_usd: float | None = 10000.0,
    shares: float | None = 1000.0,
    vwap: float | None = 10.0,
    accepted_at: datetime | None = datetime(2024, 1, 16, 16, 30, tzinfo=ET),
    plan_10b5_1: str = "none",
    badges: Sequence[str] = (),
) -> Decision:
    accession = f"test-{owner_group_key(owner_ciks)}-{issuer_cik}-{first_trade_date:%Y%m%d}"
    decision = Decision(
        owner_group=owner_group_key(owner_ciks),
        issuer_cik=issuer_cik,
        direction=direction,
        is_planned=plan_10b5_1 != "none",
        plan_10b5_1=plan_10b5_1,
        first_trade_date=first_trade_date,
        last_trade_date=first_trade_date,
        shares=shares,
        value_usd=value_usd,
        vwap=vwap,
        first_accession=accession,
        accessions=[accession],
        accepted_at=accepted_at,
        filed_date=accepted_at.date() if accepted_at else None,
        badges=list(badges),
    )
    session.add(decision)
    session.flush()
    for cik in owner_ciks:
        session.add(DecisionOwner(decision_id=decision.id, owner_cik=cik))
    session.flush()
    return decision


def make_decision_return(
    session: Session,
    decision_id: int,
    *,
    basis: str = "filed",
    horizon: str = "6m",
    raw_return: float | None = 0.1,
    excess_spy: float | None = 0.05,
    excess_qqq: float | None = None,
    excess_sector: float | None = None,
    is_complete: bool = True,
) -> DecisionReturn:
    row = DecisionReturn(
        decision_id=decision_id,
        basis=basis,
        horizon=horizon,
        raw_return=raw_return,
        excess_spy=excess_spy,
        excess_qqq=excess_qqq,
        excess_sector=excess_sector,
        is_complete=is_complete,
        exit_reason="horizon",
    )
    session.add(row)
    session.flush()
    return row


def make_profile_stats(
    session: Session,
    *,
    kind: str = "insider",
    cik: int = 2000001,
    basis: str = "filed",
    include_10b5_1: bool = False,
    **metrics: object,
) -> ProfileStats:
    stats = ProfileStats(kind=kind, cik=cik, basis=basis, include_10b5_1=include_10b5_1, **metrics)
    session.add(stats)
    session.flush()
    return stats


def get_one(session: Session, model: type, **filters: object):
    """Small convenience used by tests: fetch exactly one row by column equality."""
    stmt = select(model).filter_by(**filters)
    return session.execute(stmt).scalar_one()
