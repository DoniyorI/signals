"""The API test world: a fixed, fictional dataset built with the factories.

See docs/superpowers/plans/2026-09-27-sec-dashboard/06-api.md ("Test seed world"). The `api`
fixture freezes the API clock at FROZEN_NOW, so "today" is Monday 2024-08-26. Expectations
on SeedIds are literals written from the definitions below, never computed by API code.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import ClassVar

import pandas as pd
from sqlalchemy.orm import Session

from signals.analytics.types import Curve, WindowResult
from signals.db.models import (
    Form144Notice,
    FundManager,
    FundNavDaily,
    FundPositionChange,
    InsiderHolding,
    OwnerRole,
    OwnershipStake,
    Position,
    ProfileWindow,
    Ticker,
)
from signals.domain.calendars import ET
from signals.domain.feed import FeedItemIn, upsert_feed_item
from signals.domain.types import Basis, Window
from tests.factories import (
    make_decision,
    make_decision_return,
    make_filing,
    make_fund_filing,
    make_fund_manager,
    make_fund_position,
    make_issuer,
    make_owner,
    make_prices,
    make_profile_stats,
    make_security,
    make_transaction,
)

FROZEN_NOW = datetime(2024, 8, 26, 10, 0, tzinfo=ET)

# Issuers, owners, funds, CUSIPs, 13F periods.
ACME, GLOBEX, OLDCO, NEWCO = 1000001, 1000002, 1000003, 1000004
DOE, ROE, HOLDINGS, SMITH, NEWBIE = 2000001, 2000002, 2000003, 2000004, 2000005
FUND, SMALL_FUND = 3000001, 3999999
CUSIP_ACME, CUSIP_GLBX, CUSIP_OLD = "000000AA1", "000000BB2", "000000CC3"
Q1, Q2 = date(2024, 3, 31), date(2024, 6, 30)

# Accessions.
A_DOE_OLD = "0002000001-23-000002"  # Form 4, superseded by its amendment
A_DOE_OLD_AMEND = "0002000001-23-000003"  # Form 4/A
A_DOE_BUY = "0002000001-24-000001"  # feed 1
A_DOE_SELL = "0002000001-24-000002"  # feed 5, 10b5-1 flagged
A_DOE_144 = "0002000001-24-000003"  # Form 144, matched to A_DOE_SELL
A_ROE_GBX_BUY = "0002000002-23-000001"
A_ROE_SELL = "0002000002-24-000001"
A_ROE_BUY = "0002000002-24-000002"  # feed 2
A_ROE_144 = "0002000002-24-000003"  # feed 4, Form 144 pending
A_GROUP_BUY = "0002000003-24-000001"  # feed 3, joint filing
A_GROUP_13D = "0002000003-24-000002"
A_NEW_BUY = "0002000005-24-000001"
A_FUND_Q1 = "0003000001-24-000001"  # feed 6
A_FUND_Q2 = "0003000001-24-000002"
A_SMALL_Q2 = "0003999999-24-000001"


def _at(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=ET)


FEED: tuple[FeedItemIn, ...] = (
    FeedItemIn(
        accession_no=A_DOE_BUY,
        form_type="4",
        accepted_at=_at(2024, 6, 3, 16, 30),
        filed_date=date(2024, 6, 3),
        issuer_cik=ACME,
        issuer_name="Acme Corp",
        ticker="ACME",
        owner_group=str(DOE),
        owner_ciks=(DOE,),
        owner_names="Doe Jane",
        top_role="CEO",
        direction="buy",
        codes=("P",),
        value_usd=10_000.0,
        shares=1_000.0,
        price=10.0,
        plan_10b5_1="none",
        badges=("cluster_buy", "top_exec"),
        market_cap_usd=1e10,
        sector="Technology",
        summary="Bought 1,000 sh @ $10.00 ($10,000)",
        lag_days=2,
        first_trade_date=date(2024, 5, 30),
    ),
    FeedItemIn(
        accession_no=A_ROE_BUY,
        form_type="4",
        accepted_at=_at(2024, 6, 5, 9, 15),
        filed_date=date(2024, 6, 5),
        issuer_cik=ACME,
        issuer_name="Acme Corp",
        ticker="ACME",
        owner_group=str(ROE),
        owner_ciks=(ROE,),
        owner_names="Roe Richard",
        top_role="Director",
        direction="buy",
        codes=("P",),
        value_usd=1_500_000.0,
        shares=150_000.0,
        price=10.0,
        plan_10b5_1="none",
        badges=("cluster_buy", "big_stake"),
        market_cap_usd=1e10,
        sector="Technology",
        summary="Bought 150,000 sh @ $10.00 ($1,500,000)",
        lag_days=2,
        first_trade_date=date(2024, 6, 3),
    ),
    FeedItemIn(
        accession_no=A_GROUP_BUY,
        form_type="4",
        accepted_at=_at(2024, 6, 5, 12, 0),
        filed_date=date(2024, 6, 5),
        issuer_cik=ACME,
        issuer_name="Acme Corp",
        ticker="ACME",
        owner_group=f"{HOLDINGS}|{SMITH}",
        owner_ciks=(HOLDINGS, SMITH),
        owner_names="Acme Holdings LP; Smith John",
        top_role="10% owner",
        direction="buy",
        codes=("P",),
        value_usd=2_500_000.0,
        shares=250_000.0,
        price=10.0,
        plan_10b5_1="none",
        badges=("cluster_buy", "big_stake", "late_filing"),
        market_cap_usd=1e10,
        sector="Technology",
        summary="Bought 250,000 sh @ $10.00 ($2,500,000)",
        lag_days=5,
        first_trade_date=date(2024, 5, 29),
    ),
    FeedItemIn(
        accession_no=A_ROE_144,
        form_type="144",
        accepted_at=_at(2024, 6, 5, 15, 10),
        filed_date=date(2024, 6, 5),
        issuer_cik=GLOBEX,
        issuer_name="Globex Inc",
        ticker="GLBX",
        owner_group=str(ROE),
        owner_ciks=(ROE,),
        owner_names="Roe Richard",
        top_role="Director",
        direction="sell",
        codes=("144",),
        value_usd=60_000.0,
        shares=2_000.0,
        sector="Communication Services",
        summary="Plans to sell 2,000 sh (~$60,000) around Jun 05, 2024",
    ),
    FeedItemIn(
        accession_no=A_DOE_SELL,
        form_type="4",
        accepted_at=_at(2024, 6, 6, 16, 5),
        filed_date=date(2024, 6, 6),
        issuer_cik=ACME,
        issuer_name="Acme Corp",
        ticker="ACME",
        owner_group=str(DOE),
        owner_ciks=(DOE,),
        owner_names="Doe Jane",
        top_role="CEO",
        direction="sell",
        codes=("S",),
        value_usd=50_000.0,
        shares=5_000.0,
        price=10.0,
        plan_10b5_1="flag",
        badges=("late_filing", "form144_matched", "top_exec"),
        market_cap_usd=1e10,
        sector="Technology",
        summary="Sold 5,000 sh @ $10.00 ($50,000)",
        lag_days=7,
        first_trade_date=date(2024, 5, 28),
    ),
    FeedItemIn(
        accession_no=A_FUND_Q1,
        form_type="13F-HR",
        accepted_at=_at(2024, 6, 7, 10, 0),
        filed_date=date(2024, 6, 7),
        owner_group=str(FUND),
        owner_ciks=(FUND,),
        owner_names="Example Capital Management",
        direction="other",
        codes=("13F-HR",),
        summary="13F-HR for 2024-03-31: 3 positions ($1,600)",
    ),
)


@dataclass(frozen=True)
class DecisionSeed:
    key: str
    owners: tuple[int, ...]
    issuer: int
    direction: str
    first_trade_date: date
    shares: float
    value_usd: float
    vwap: float
    accession: str
    accepted_at: datetime
    plan: str = "none"
    badges: tuple[str, ...] = ()
    lag_days: int = 2
    lag_cost: float = 0.01
    complete: tuple[str, ...] = ()  # horizons complete by FROZEN_NOW
    excess_6m: float = 0.05  # filed basis; see _seed_returns for the other horizons and bases


DECISIONS: tuple[DecisionSeed, ...] = (
    DecisionSeed(
        "d0", (DOE,), ACME, "buy", date(2023, 1, 10), 5_000.0, 50_000.0, 10.0,
        A_DOE_OLD_AMEND, _at(2023, 1, 20, 16), badges=("first_buy_2y", "top_exec"),
        lag_cost=0.004, complete=("1m", "3m", "6m", "12m"), excess_6m=0.10,
    ),
    DecisionSeed(
        "d1", (DOE,), ACME, "buy", date(2024, 5, 30), 1_000.0, 10_000.0, 10.0,
        A_DOE_BUY, _at(2024, 6, 3, 16, 30), badges=("cluster_buy", "top_exec"),
        complete=("1m",), excess_6m=0.02,
    ),
    DecisionSeed(
        "d2", (ROE,), ACME, "buy", date(2024, 6, 3), 150_000.0, 1_500_000.0, 10.0,
        A_ROE_BUY, _at(2024, 6, 5, 9, 15), badges=("cluster_buy", "big_stake"),
        complete=("1m",), excess_6m=0.03,
    ),
    DecisionSeed(
        "d3", (HOLDINGS, SMITH), ACME, "buy", date(2024, 5, 29), 250_000.0, 2_500_000.0,
        10.0, A_GROUP_BUY, _at(2024, 6, 5, 12), badges=("cluster_buy", "big_stake", "late_filing"),
        lag_days=5, complete=("1m",), excess_6m=0.04,
    ),
    DecisionSeed(
        "d4", (DOE,), ACME, "sell", date(2024, 5, 28), 5_000.0, 50_000.0, 10.0,
        A_DOE_SELL, _at(2024, 6, 6, 16, 5), plan="flag",
        badges=("late_filing", "form144_matched", "top_exec"), lag_days=7,
        complete=("1m",), excess_6m=-0.01,
    ),
    DecisionSeed(
        "d5", (ROE,), GLOBEX, "buy", date(2023, 11, 15), 10_000.0, 300_000.0, 30.0,
        A_ROE_GBX_BUY, _at(2023, 11, 17, 16), complete=("1m", "3m", "6m"), excess_6m=0.03,
    ),
    DecisionSeed(
        "d6", (NEWBIE,), GLOBEX, "buy", date(2024, 8, 1), 1_000.0, 20_000.0, 20.0,
        A_NEW_BUY, _at(2024, 8, 5, 16), complete=(), excess_6m=0.01,
    ),
    DecisionSeed(
        "d7", (ROE,), ACME, "sell", date(2024, 3, 15), 20_000.0, 200_000.0, 10.0,
        A_ROE_SELL, _at(2024, 3, 19, 16), complete=("1m", "3m"), excess_6m=0.02,
    ),
)  # fmt: skip

HORIZON_FACTOR = {"1m": 0.25, "3m": 0.5, "6m": 1.0, "12m": 1.5}


@dataclass(frozen=True)
class SeedIds:
    """Ids assigned while seeding, plus literal expectations for the feed tests."""

    decisions: dict[str, int]

    # GET /api/feed filters.
    buy_accessions = frozenset({A_DOE_BUY, A_ROE_BUY, A_GROUP_BUY})
    f13_accessions = frozenset({A_FUND_Q1})
    non_planned_accessions = frozenset({A_DOE_BUY, A_ROE_BUY, A_GROUP_BUY, A_ROE_144, A_FUND_Q1})
    big_accessions = frozenset({A_ROE_BUY, A_GROUP_BUY})
    roe_accessions = frozenset({A_ROE_BUY, A_ROE_144})
    cluster_accessions = frozenset({A_DOE_BUY, A_ROE_BUY, A_GROUP_BUY})
    # Newest first: accepted_at DESC.
    feed_order = (A_FUND_Q1, A_DOE_SELL, A_ROE_144, A_GROUP_BUY, A_ROE_BUY, A_DOE_BUY)
    # GET /api/feed/summary?date=2024-06-05.
    counts_on_0605: ClassVar[dict[str, int]] = {"4": 2, "144": 1}
    top_buys_0605: ClassVar[list[str]] = [A_GROUP_BUY, A_ROE_BUY]


def seed_world(session: Session) -> SeedIds:
    _seed_reference(session)
    _seed_people_and_filings(session)
    _seed_feed(session)
    ids = _seed_decisions(session)
    _seed_profiles(session, ids)
    _seed_funds(session)
    session.flush()
    return SeedIds(decisions=ids)


# --------------------------------------------------------------------------- reference
def _seed_reference(session: Session) -> None:
    make_issuer(session, cik=ACME, name="Acme Corp", sic=3571, sector="Technology", ticker="ACME")
    make_issuer(
        session, cik=GLOBEX, name="Globex Inc", sic=4841, sector="Communication Services",
        ticker=None, shares_outstanding=5e8,
    )  # fmt: skip
    make_issuer(session, cik=OLDCO, name="Old Co", sic=None, sector=None, ticker=None)
    make_issuer(
        session, cik=NEWCO, name="New Co", sic=2834, sector="Health Care", ticker="XYZ",
        ticker_from=date(2020, 5, 1),
    )  # fmt: skip
    for cik, symbol, start, end in (
        (GLOBEX, "GBX", date(2010, 1, 1), date(2022, 6, 8)),
        (GLOBEX, "GLBX", date(2022, 6, 9), None),
        (OLDCO, "XYZ", date(2010, 1, 1), date(2018, 12, 31)),
        (OLDCO, "XYZA", date(2019, 1, 1), None),
    ):
        session.add(
            Ticker(issuer_cik=cik, symbol=symbol, valid_from=start, valid_to=end, source="test")
        )
    session.flush()
    # 19 NYSE sessions, 2024-05-20 through 2024-06-14 (Memorial Day skipped).
    acme = [9.0, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 10.0, 10.1, 10.2, 10.3, 10.2, 10.1]
    make_prices(session, "ACME", date(2024, 5, 20), [*acme, 10.1, 10.0, 10.0])
    make_prices(session, "GLBX", date(2024, 5, 20), [29.0] * 18 + [30.0])
    make_prices(session, "SPY", date(2024, 5, 20), [490.0] * 18 + [500.0])
    make_security(session, cusip=CUSIP_ACME, issuer_cik=ACME, ticker="ACME", name="ACME CORP")
    make_security(session, cusip=CUSIP_GLBX, issuer_cik=GLOBEX, ticker="GLBX", name="GLOBEX INC")
    make_security(session, cusip=CUSIP_OLD, issuer_cik=OLDCO, ticker="XYZA", name="OLD CO")


# --------------------------------------------------------------------------- people
def _seed_people_and_filings(session: Session) -> None:
    make_owner(session, cik=DOE, name="Doe Jane")
    make_owner(session, cik=ROE, name="Roe Richard")
    make_owner(session, cik=HOLDINGS, name="Acme Holdings LP", owner_type="entity")
    make_owner(session, cik=SMITH, name="Smith John")
    make_owner(session, cik=NEWBIE, name="New Person")
    roles = (
        (DOE, ACME, "Chief Executive Officer", ["CEO"], date(2019, 3, 1), date(2024, 6, 6)),
        (ROE, ACME, None, ["Director"], date(2018, 5, 1), date(2024, 6, 5)),
        (ROE, GLOBEX, None, ["Director"], date(2020, 1, 15), date(2024, 6, 5)),
        (HOLDINGS, ACME, None, ["10% owner"], date(2024, 6, 5), date(2024, 6, 10)),
        (SMITH, ACME, None, ["10% owner"], date(2024, 6, 5), date(2024, 6, 10)),
        (NEWBIE, GLOBEX, "Chief Financial Officer", ["CFO"], date(2024, 8, 5), date(2024, 8, 5)),
    )
    for owner, issuer, title, role_list, first, last in roles:
        session.add(
            OwnerRole(
                owner_cik=owner,
                issuer_cik=issuer,
                is_director="Director" in role_list,
                is_officer=title is not None,
                officer_title=title,
                roles=role_list,
                is_ten_pct_owner="10% owner" in role_list,
                first_filed=first,
                last_filed=last,
            )
        )
    session.flush()

    filings = (
        (A_DOE_OLD, "4", _at(2023, 1, 12, 17), ACME, DOE, (DOE,)),
        (A_DOE_OLD_AMEND, "4/A", _at(2023, 1, 20, 16), ACME, DOE, (DOE,)),
        (A_DOE_BUY, "4", _at(2024, 6, 3, 16, 30), ACME, DOE, (DOE,)),
        (A_DOE_SELL, "4", _at(2024, 6, 6, 16, 5), ACME, DOE, (DOE,)),
        (A_DOE_144, "144", _at(2024, 5, 24, 11), ACME, DOE, ()),
        (A_ROE_GBX_BUY, "4", _at(2023, 11, 17, 16), GLOBEX, ROE, (ROE,)),
        (A_ROE_SELL, "4", _at(2024, 3, 19, 16), ACME, ROE, (ROE,)),
        (A_ROE_BUY, "4", _at(2024, 6, 5, 9, 15), ACME, ROE, (ROE,)),
        (A_ROE_144, "144", _at(2024, 6, 5, 15, 10), GLOBEX, ROE, ()),
        (A_GROUP_BUY, "4", _at(2024, 6, 5, 12), ACME, HOLDINGS, (HOLDINGS, SMITH)),
        (A_GROUP_13D, "SCHEDULE 13D", _at(2024, 6, 10, 16), ACME, HOLDINGS, ()),
        (A_NEW_BUY, "4", _at(2024, 8, 5, 16), GLOBEX, NEWBIE, (NEWBIE,)),
    )
    for accession, form, accepted, issuer, primary, owners in filings:
        make_filing(
            session,
            accession_no=accession,
            form_type=form,
            issuer_cik=issuer,
            primary_cik=primary,
            filed_date=accepted.date(),
            accepted_at=accepted,
            owners=owners,
        )

    txs = (  # accession, issuer, owners, code, date, shares, price, owned after, plan, superseded
        (A_DOE_OLD, ACME, (DOE,), "P", date(2023, 1, 10), 5_000, 10.1, 15_000, "none",
         A_DOE_OLD_AMEND),
        (A_DOE_OLD_AMEND, ACME, (DOE,), "P", date(2023, 1, 10), 5_000, 10.0, 15_000, "none", None),
        (A_DOE_SELL, ACME, (DOE,), "S", date(2024, 5, 28), 5_000, 10.0, 10_000, "flag", None),
        (A_DOE_BUY, ACME, (DOE,), "P", date(2024, 5, 30), 1_000, 10.0, 11_000, "none", None),
        (A_ROE_GBX_BUY, GLOBEX, (ROE,), "P", date(2023, 11, 15), 10_000, 30.0, 10_000, "none",
         None),
        (A_ROE_SELL, ACME, (ROE,), "S", date(2024, 3, 15), 20_000, 10.0, 130_000, "none", None),
        (A_ROE_BUY, ACME, (ROE,), "P", date(2024, 6, 3), 150_000, 10.0, 280_000, "none", None),
        (A_GROUP_BUY, ACME, (HOLDINGS, SMITH), "P", date(2024, 5, 29), 250_000, 10.0, 12_000_000,
         "none", None),
        (A_NEW_BUY, GLOBEX, (NEWBIE,), "P", date(2024, 8, 1), 1_000, 20.0, 1_000, "none", None),
    )  # fmt: skip
    for accession, issuer, owners, code, day, shares, price, after, plan, superseded in txs:
        make_transaction(
            session,
            accession_no=accession,
            issuer_cik=issuer,
            owner_ciks=owners,
            code=code,
            transaction_date=day,
            shares=float(shares),
            price=price,
            shares_owned_after=float(after),
            plan_10b5_1=plan,
            superseded_by=superseded,
        )

    session.add(
        Position(
            owner_cik=DOE,
            issuer_cik=ACME,
            security_title="Common Stock",
            direct_indirect="D",
            shares=11_000.0,
            as_of_date=date(2024, 6, 3),
            last_accession=A_DOE_BUY,
        )
    )
    session.add(
        InsiderHolding(
            accession_no=A_DOE_BUY,
            table_kind="deriv",
            row_no=1,
            issuer_cik=ACME,
            owner_group=str(DOE),
            security_title="Stock Option (Right to Buy)",
            shares_owned=20_000.0,
            direct_indirect="D",
            exercise_price=8.0,
            expiration_date=date(2030, 1, 1),
            underlying_title="Common Stock",
            underlying_shares=20_000.0,
        )
    )
    session.add_all(
        [
            Form144Notice(
                accession_no=A_DOE_144,
                filer_cik=DOE,
                issuer_cik=ACME,
                seller_name="Doe Jane",
                relationship="Officer",
                security_class="Common",
                broker="Example Securities LLC",
                shares_to_sell=5_000.0,
                market_value_usd=50_000.0,
                approx_sale_date=date(2024, 5, 28),
                matched_sale_accession=A_DOE_SELL,
            ),
            Form144Notice(
                accession_no=A_ROE_144,
                filer_cik=ROE,
                issuer_cik=GLOBEX,
                seller_name="Roe Richard",
                relationship="Director",
                security_class="Common",
                broker="Example Securities LLC",
                shares_to_sell=2_000.0,
                market_value_usd=60_000.0,
                approx_sale_date=date(2024, 6, 5),
            ),
            OwnershipStake(
                accession_no=A_GROUP_13D,
                form_type="SCHEDULE 13D",
                issuer_cik=ACME,
                cusip=CUSIP_ACME,
                event_date=date(2024, 5, 29),
                amendment_no=None,
                is_activist=True,
                percent_of_class=0.12,
                shares=12_000_000.0,
                reporting_persons=[
                    {
                        "name": "Acme Holdings LP",
                        "cik": HOLDINGS,
                        "percent_of_class": 0.12,
                        "aggregate_owned": 12_000_000.0,
                    },
                    {
                        "name": "Smith John",
                        "cik": SMITH,
                        "percent_of_class": 0.12,
                        "aggregate_owned": 12_000_000.0,
                    },
                ],
                group_key=f"{HOLDINGS}|{SMITH}",
                purpose_excerpt="Seeking board representation.",
                is_current=True,
            ),
        ]
    )
    session.flush()


def _seed_feed(session: Session) -> None:
    for item in FEED:
        upsert_feed_item(session, item)
    session.flush()


# --------------------------------------------------------------------------- analytics
def _seed_decisions(session: Session) -> dict[str, int]:
    ids: dict[str, int] = {}
    for spec in DECISIONS:
        decision = make_decision(
            session,
            owner_ciks=spec.owners,
            issuer_cik=spec.issuer,
            direction=spec.direction,
            first_trade_date=spec.first_trade_date,
            value_usd=spec.value_usd,
            shares=spec.shares,
            vwap=spec.vwap,
            accepted_at=spec.accepted_at,
            plan_10b5_1=spec.plan,
            badges=spec.badges,
        )
        decision.first_accession = spec.accession
        decision.accessions = [spec.accession]
        decision.lag_days = spec.lag_days
        decision.lag_cost = spec.lag_cost
        session.flush()
        _seed_returns(session, decision.id, spec)
        ids[spec.key] = decision.id
    return ids


def _seed_returns(session: Session, decision_id: int, spec: DecisionSeed) -> None:
    """Filed-basis excess vs SPY scales with the horizon; executed adds 0.02 everywhere."""
    for basis, bump in (("filed", 0.0), ("executed", 0.02)):
        for horizon, factor in HORIZON_FACTOR.items():
            excess = spec.excess_6m * factor + bump
            make_decision_return(
                session,
                decision_id,
                basis=basis,
                horizon=horizon,
                raw_return=excess + 0.05,
                excess_spy=excess,
                excess_qqq=excess - 0.01,
                excess_sector=excess - 0.02,
                is_complete=horizon in spec.complete,
            )


def _seed_profiles(session: Session, ids: dict[str, int]) -> None:
    common = {"primary_issuer_cik": ACME, "sector": "Technology", "avg_lag_days": 2.0}
    doe = {
        **common,
        "n_complete": 1,
        "avg_roi_6m_raw": 0.15,
        "median_6m": 0.10,
        "hit_rate": 1.0,
        "best_decision_id": ids["d0"],
        "worst_decision_id": ids["d0"],
        "avg_lag_cost": 0.004,
        "shrunk_mean": 0.04,
        "confidence": "low",
        "risk_label": "medium",
    }
    roe = {
        **common,
        "n_decisions": 3,
        "n_buys": 2,
        "n_sells": 1,
        "n_complete": 1,
        "avg_roi_6m_raw": 0.08,
        "median_6m": 0.03,
        "hit_rate": 1.0,
        "best_decision_id": ids["d5"],
        "worst_decision_id": ids["d5"],
        "avg_lag_cost": 0.01,
        "shrunk_mean": 0.01,
        "confidence": "low",
        "risk_label": "high",
        "last_trade_date": date(2024, 6, 3),
    }
    rows = (  # cik, basis, include_10b5_1, metrics
        (DOE, "filed", False, {**doe, "n_decisions": 2, "n_buys": 2, "n_sells": 0,
                               "avg_roi_6m": 0.10, "rating": 80,
                               "last_trade_date": date(2024, 5, 30)}),
        (DOE, "executed", False, {**doe, "n_decisions": 2, "n_buys": 2, "n_sells": 0,
                                  "avg_roi_6m": 0.12, "rating": 75,
                                  "last_trade_date": date(2024, 5, 30)}),
        (DOE, "filed", True, {**doe, "n_decisions": 3, "n_buys": 2, "n_sells": 1,
                              "avg_roi_6m": 0.10, "rating": 78,
                              "last_trade_date": date(2024, 5, 30)}),
        (DOE, "executed", True, {**doe, "n_decisions": 3, "n_buys": 2, "n_sells": 1,
                                 "avg_roi_6m": 0.12, "rating": 72,
                                 "last_trade_date": date(2024, 5, 30)}),
        (ROE, "filed", False, {**roe, "avg_roi_6m": 0.03, "rating": 40}),
        (ROE, "executed", False, {**roe, "avg_roi_6m": 0.05, "rating": 45}),
        (ROE, "filed", True, {**roe, "avg_roi_6m": 0.03, "rating": 41}),
        (ROE, "executed", True, {**roe, "avg_roi_6m": 0.05, "rating": 46}),
    )  # fmt: skip
    for cik, basis, toggle, metrics in rows:
        make_profile_stats(
            session, kind="insider", cik=cik, basis=basis, include_10b5_1=toggle, **metrics
        )
    for basis, rating in (("filed", 65), ("executed", 60)):
        make_profile_stats(
            session,
            kind="fund",
            cik=FUND,
            basis=basis,
            include_10b5_1=False,
            n_complete=4,
            avg_roi_6m=0.03,
            hit_rate=0.75,
            rating=rating,
            confidence="medium",
            risk_label="medium",
            sector="Technology",
        )
    windows = (  # kind, cik, window, ret, ret_spy
        ("insider", DOE, "ytd", 0.05, 0.08), ("insider", DOE, "1y", 0.20, 0.15),
        ("insider", DOE, "3y", 0.35, 0.30), ("insider", DOE, "5y", None, None),
        ("insider", ROE, "ytd", -0.02, 0.08), ("insider", ROE, "1y", 0.10, 0.15),
        ("insider", ROE, "3y", None, None), ("insider", ROE, "5y", None, None),
        ("fund", FUND, "ytd", 0.03, 0.08), ("fund", FUND, "1y", 0.12, 0.15),
        ("fund", FUND, "3y", 0.30, 0.25), ("fund", FUND, "5y", 0.50, 0.60),
    )  # fmt: skip
    for kind, cik, window, ret, ret_spy in windows:
        session.add(
            ProfileWindow(
                kind=kind,
                cik=cik,
                basis="filed",
                include_10b5_1=False,
                window=window,
                ret=ret,
                ret_spy=ret_spy,
                ret_qqq=ret_spy,
                ret_sector=ret_spy,
                vol=0.25 if ret is not None else None,
            )
        )
    session.flush()


# --------------------------------------------------------------------------- funds
def _seed_funds(session: Session) -> None:
    make_fund_manager(session, cik=FUND, name="Example Capital Management", is_tracked=True)
    make_fund_manager(session, cik=SMALL_FUND, name="Small Fry Advisors", is_tracked=False)
    make_fund_filing(
        session, accession_no=A_FUND_Q1, filer_cik=FUND, period=Q1,
        filed_date=date(2024, 6, 7), accepted_at=_at(2024, 6, 7, 10),
    )  # fmt: skip
    make_fund_filing(
        session, accession_no=A_FUND_Q2, filer_cik=FUND, period=Q2,
        filed_date=date(2024, 8, 14), accepted_at=_at(2024, 8, 14, 16),
    )  # fmt: skip
    make_fund_filing(
        session, accession_no=A_SMALL_Q2, filer_cik=SMALL_FUND, period=Q2,
        filed_date=date(2024, 8, 12), accepted_at=_at(2024, 8, 12, 16),
    )  # fmt: skip
    positions = (  # accession, filer, period, cusip, shares, value
        (A_FUND_Q1, FUND, Q1, CUSIP_ACME, 100.0, 1_000.0),
        (A_FUND_Q1, FUND, Q1, CUSIP_GLBX, 50.0, 500.0),
        (A_FUND_Q1, FUND, Q1, CUSIP_OLD, 10.0, 100.0),
        (A_FUND_Q2, FUND, Q2, CUSIP_ACME, 150.0, 2_000.0),
        (A_FUND_Q2, FUND, Q2, CUSIP_GLBX, 50.0, 100.0),
        (A_SMALL_Q2, SMALL_FUND, Q2, CUSIP_ACME, 40.0, 500.0),
    )
    for accession, filer, period, cusip, shares, value in positions:
        make_fund_position(
            session,
            accession_no=accession,
            filer_cik=filer,
            period=period,
            cusip=cusip,
            shares=shares,
            value_usd=value,
        )
    changes = (  # filer, period, cusip, prev, shares, change, pct, value, weight, prev_weight
        (FUND, Q1, CUSIP_ACME, None, 100.0, "NEW", None, 1_000.0, 0.625, None),
        (FUND, Q1, CUSIP_GLBX, None, 50.0, "NEW", None, 500.0, 0.3125, None),
        (FUND, Q1, CUSIP_OLD, None, 10.0, "NEW", None, 100.0, 0.0625, None),
        (FUND, Q2, CUSIP_ACME, 100.0, 150.0, "ADD", 0.5, 2_000.0, 2000 / 2100, 0.625),
        (FUND, Q2, CUSIP_GLBX, 50.0, 50.0, "SAME", 0.0, 100.0, 100 / 2100, 0.3125),
        (FUND, Q2, CUSIP_OLD, 10.0, 0.0, "EXIT", -1.0, 0.0, 0.0, 0.0625),
        (SMALL_FUND, Q2, CUSIP_ACME, None, 40.0, "NEW", None, 500.0, 1.0, None),
    )  # fmt: skip
    for filer, period, cusip, prev, shares, change, pct, value, weight, prev_weight in changes:
        session.add(
            FundPositionChange(
                filer_cik=filer,
                period=period,
                cusip=cusip,
                put_call="",
                prev_shares=prev,
                shares=shares,
                change=change,
                shares_change_pct=pct,
                value_usd=value,
                weight=weight,
                prev_weight=prev_weight,
            )
        )
    for cik, value, count in ((FUND, 2_100.0, 2), (SMALL_FUND, 500.0, 1)):
        manager = session.get(FundManager, cik)
        assert manager is not None
        manager.latest_period = Q2
        manager.latest_value_usd = value
        manager.latest_positions = count
    session.add_all(
        [
            FundNavDaily(cik=FUND, basis="filed", date=date(2024, 6, 28), nav=1.10, coverage=0.90),
            FundNavDaily(cik=FUND, basis="filed", date=date(2024, 7, 1), nav=1.12, coverage=0.95),
        ]
    )
    session.flush()


# --------------------------------------------------------------------------- curves
INSIDER_CURVE_START = date(2024, 8, 20)
FUND_CURVE_START = date(2024, 8, 21)  # one day later, so compare has to rebase


class FakeCurves:
    """Stands in for signals.analytics.curves: 3 points and 4 windows returned out of the
    canonical order. Fund 3999999 is untracked, so fund_curve raises LookupError for it."""

    def insider_curve(self, session, cik, *, basis, include_10b5_1, as_of) -> Curve:
        return _fake_curve(basis, as_of, INSIDER_CURVE_START, coverage=None)

    def fund_curve(self, session, cik, *, basis, as_of) -> Curve:
        if cik == SMALL_FUND:
            raise LookupError("fund not tracked")
        return _fake_curve(basis, as_of, FUND_CURVE_START, coverage=0.9)


def _fake_curve(basis: str, as_of: date, start: date, *, coverage: float | None) -> Curve:
    index = [start + timedelta(days=i) for i in range(3)]
    points = pd.DataFrame(
        {
            "nav": [1.0, 1.05, 1.10],
            "spy": [1.0, 1.01, 1.02],
            "qqq": [1.0, 1.01, 1.02],
            "sector": [1.0, 1.01, 1.02],
        },
        index=index,
    )

    def window(name: Window, ret: float | None) -> WindowResult:
        return WindowResult(
            window=name,
            start=start if ret is not None else None,
            end=as_of if ret is not None else None,
            ret=ret,
            ret_spy=0.05 if ret is not None else None,
            ret_qqq=0.06 if ret is not None else None,
            ret_sector=0.04 if ret is not None else None,
            annualized=None,
            vol=0.2 if ret is not None else None,
            max_drawdown=-0.1 if ret is not None else None,
            beta=1.1 if ret is not None else None,
            time_invested_pct=0.8 if ret is not None else None,
        )

    windows = [
        window(Window.Y5, None),
        window(Window.YTD, 0.1),
        window(Window.Y3, None),
        window(Window.Y1, 0.2),
    ]
    return Curve(
        basis=Basis(basis), points=points, windows=windows, coverage_pct=coverage, as_of=as_of
    )
