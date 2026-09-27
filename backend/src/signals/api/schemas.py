"""The API contract. Percentages are fractions (0.123 = 12.3%); money is USD.

The frontend's TypeScript types are generated from the OpenAPI document built from these
models, so changing a field here is a contract change: regenerate and update both sides.
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Basis = Literal["filed", "executed"]
WindowName = Literal["ytd", "1y", "3y", "5y"]
Change = Literal["NEW", "ADD", "TRIM", "EXIT", "SAME"]
ConfidenceName = Literal["low", "medium", "high"]
PlanFlagName = Literal["flag", "footnote", "none"]


# ---------------------------------------------------------------------------- shared
class OwnerRef(BaseModel):
    cik: int
    name: str


class IssuerRef(BaseModel):
    cik: int
    name: str
    ticker: str | None = None


class Rating(BaseModel):
    score: int | None
    confidence: ConfidenceName | None
    n: int


class WindowStat(BaseModel):
    window: WindowName
    ret: float | None
    ret_spy: float | None
    ret_qqq: float | None
    ret_sector: float | None
    annualized: float | None
    vol: float | None
    max_drawdown: float | None
    beta: float | None
    time_invested_pct: float | None


class AllocationSlice(BaseModel):
    key: str
    label: str
    value_usd: float
    weight: float


class CurvePoint(BaseModel):
    date: date
    nav: float
    spy: float
    qqq: float
    sector: float


class PerformanceOut(BaseModel):
    basis: Basis
    points: list[CurvePoint]
    windows: list[WindowStat]
    coverage_pct: float | None
    as_of: date


# ---------------------------------------------------------------------------- feed
class FeedItemOut(BaseModel):
    accession_no: str
    sec_url: str
    form_type: str
    accepted_at: datetime | None
    filed_date: date
    issuer: IssuerRef | None
    owners: list[OwnerRef]
    top_role: str | None
    direction: Literal["buy", "sell", "other"] | None
    codes: list[str]
    value_usd: float | None
    shares: float | None
    price: float | None
    plan_10b5_1: PlanFlagName | None
    badges: list[str]
    market_cap_usd: float | None
    sector: str | None
    summary: str
    lag_days: int | None


class FeedPage(BaseModel):
    items: list[FeedItemOut]
    next_cursor: str | None


class ClusterEvent(BaseModel):
    issuer: IssuerRef
    start_date: date
    end_date: date
    owner_count: int
    total_value_usd: float


class FeedSummary(BaseModel):
    date: date
    counts_by_form: dict[str, int]
    top_buys: list[FeedItemOut]
    top_sells: list[FeedItemOut]
    clusters: list[ClusterEvent]
    late_filings: list[FeedItemOut]


# ---------------------------------------------------------------------------- insiders
class RoleAtIssuer(BaseModel):
    issuer: IssuerRef
    roles: list[str]
    officer_title: str | None
    first_filed: date | None
    last_filed: date | None


class HorizonReturn(BaseModel):
    horizon: Literal["1m", "3m", "6m", "12m"]
    raw: float | None
    excess_spy: float | None
    excess_qqq: float | None
    excess_sector: float | None
    complete: bool


class DecisionOut(BaseModel):
    id: int
    issuer: IssuerRef
    owners: list[OwnerRef]
    direction: Literal["buy", "sell"]
    first_trade_date: date
    last_trade_date: date
    shares: float | None
    value_usd: float | None
    vwap: float | None
    stake_change_pct: float | None
    accepted_at: datetime | None
    plan_10b5_1: PlanFlagName
    badges: list[str]
    lag_days: int | None
    lag_cost: float | None
    returns: list[HorizonReturn]
    first_accession: str
    sec_url: str


class DecisionPage(BaseModel):
    items: list[DecisionOut]
    next_cursor: str | None


class InsiderHeader(BaseModel):
    cik: int
    name: str
    owner_type: Literal["person", "entity"]
    roles: list[RoleAtIssuer]
    basis: Basis
    include_10b5_1: bool
    rating: Rating
    avg_roi_6m: float | None
    avg_roi_6m_raw: float | None
    median_6m: float | None
    hit_rate: float | None
    n_decisions: int
    n_buys: int
    n_sells: int
    avg_lag_days: float | None
    avg_lag_cost: float | None
    best: DecisionOut | None
    worst: DecisionOut | None
    risk_label: Literal["low", "medium", "high"] | None
    fund_cik: int | None
    updated_at: datetime | None


class TransactionOut(BaseModel):
    accession_no: str
    sec_url: str
    form_type: str
    accepted_at: datetime | None
    issuer: IssuerRef
    transaction_date: date | None
    code: str | None
    code_label: str | None
    acquired_disposed: str | None
    shares: float | None
    price: float | None
    value_usd: float | None
    shares_owned_after: float | None
    direct_indirect: str | None
    security_title: str | None
    table_kind: Literal["nonderiv", "deriv"]
    plan_10b5_1: PlanFlagName
    superseded: bool
    footnotes: list[str]


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    next_cursor: str | None


class HoldingOut(BaseModel):
    issuer: IssuerRef
    security_title: str | None
    shares: float | None
    value_usd: float | None
    weight: float | None
    sector: str | None
    direct_indirect: str | None
    as_of_date: date | None


class HoldingsOut(BaseModel):
    positions: list[HoldingOut]
    derivatives: list[HoldingOut]
    by_sector: list[AllocationSlice]
    by_issuer: list[AllocationSlice]
    effective_n: float | None
    top5_weight: float | None
    total_value_usd: float | None


class Form144Out(BaseModel):
    accession_no: str
    sec_url: str
    filed_date: date
    issuer: IssuerRef
    seller_name: str | None
    relationship: str | None
    shares_to_sell: float | None
    market_value_usd: float | None
    approx_sale_date: date | None
    broker: str | None
    plan_10b5_1_adopted: date | None
    matched_sale_accession: str | None
    status: Literal["pending", "matched", "expired"]


# ---------------------------------------------------------------------------- companies
class NetBuying(BaseModel):
    window: Literal["3m", "6m", "12m"]
    buys_usd: float
    sells_usd: float
    net_usd: float
    n_buyers: int
    n_sellers: int


class CompanyHeader(BaseModel):
    cik: int
    name: str
    ticker: str | None
    former_tickers: list[str]
    exchange: str | None
    sector: str | None
    sic: int | None
    sic_description: str | None
    market_cap_usd: float | None
    latest_close: float | None
    latest_close_date: date | None
    net_buying: list[NetBuying]


class Bar(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    adj_close: float


class Marker(BaseModel):
    date: date
    kind: Literal["buy", "sell", "form144", "stake", "cluster"]
    label: str
    value_usd: float | None
    ref: str


class PriceSeriesOut(BaseModel):
    symbol: str | None
    bars: list[Bar]
    markers: list[Marker]


class InsiderRosterRow(BaseModel):
    owner: OwnerRef
    roles: list[str]
    last_trade_date: date | None
    net_12m_usd: float
    n_decisions: int
    rating: Rating


class InstitutionRow(BaseModel):
    fund: OwnerRef
    shares: float
    value_usd: float
    weight_in_fund: float | None
    change: Change
    shares_change_pct: float | None
    is_tracked: bool


class InstitutionsOut(BaseModel):
    period: date | None
    periods_available: list[date]
    rows: list[InstitutionRow]
    total_value_usd: float
    holders_count: int
    new_count: int
    exit_count: int
    next_cursor: str | None


class StakePerson(BaseModel):
    name: str
    cik: int | None
    percent_of_class: float | None
    shares: float | None


class StakeOut(BaseModel):
    accession_no: str
    sec_url: str
    form_type: str
    filed_date: date
    event_date: date | None
    reporting_persons: list[StakePerson]
    percent_of_class: float | None
    is_activist: bool
    is_current: bool
    purpose_excerpt: str | None


# ---------------------------------------------------------------------------- funds
class FundValuePoint(BaseModel):
    period: date
    value_usd: float
    positions: int


class FundHeader(BaseModel):
    cik: int
    name: str
    is_tracked: bool
    latest_period: date | None
    latest_value_usd: float | None
    latest_positions: int | None
    value_history: list[FundValuePoint]
    rating: Rating
    windows: list[WindowStat]
    coverage_pct: float | None
    insider_cik: int | None


class SecurityRef(BaseModel):
    cusip: str
    name: str | None
    ticker: str | None
    issuer_cik: int | None


class FundHoldingRow(BaseModel):
    security: SecurityRef
    put_call: str | None
    shares: float
    value_usd: float
    weight: float | None
    prev_weight: float | None
    change: Change
    shares_change_pct: float | None
    sector: str | None
    high_conviction: bool


class FundHoldingsOut(BaseModel):
    period: date | None
    periods_available: list[date]
    rows: list[FundHoldingRow]
    exits: list[FundHoldingRow]
    by_sector: list[AllocationSlice]
    effective_n: float | None
    top5_weight: float | None
    next_cursor: str | None


# ----------------------------------------------------------------- screener, compare, search
class InsiderScreenRow(BaseModel):
    owner: OwnerRef
    primary_issuer: IssuerRef | None
    roles: list[str]
    sector: str | None
    rating: Rating
    avg_roi_6m: float | None
    hit_rate: float | None
    n_decisions: int
    last_trade_date: date | None
    windows: dict[str, float | None]
    risk_label: str | None


class InsiderScreenPage(BaseModel):
    items: list[InsiderScreenRow]
    next_cursor: str | None


class FundScreenRow(BaseModel):
    fund: OwnerRef
    latest_value_usd: float | None
    positions: int | None
    top_sector: str | None
    rating: Rating
    windows: dict[str, float | None]
    risk_label: str | None
    coverage_pct: float | None


class FundScreenPage(BaseModel):
    items: list[FundScreenRow]
    next_cursor: str | None


class CompareProfile(BaseModel):
    id: str
    kind: Literal["insider", "fund"]
    name: str
    rating: Rating
    avg_roi_6m: float | None
    hit_rate: float | None
    windows: list[WindowStat]
    curve: list[CurvePoint]
    by_sector: list[AllocationSlice]


class CompareOut(BaseModel):
    basis: Basis
    profiles: list[CompareProfile]


class SearchHit(BaseModel):
    kind: Literal["insider", "company", "fund"]
    cik: int
    name: str
    ticker: str | None
    subtitle: str | None
    score: float


class SearchOut(BaseModel):
    insiders: list[SearchHit]
    companies: list[SearchHit]
    funds: list[SearchHit]


# ---------------------------------------------------------------------------- watchlists
class WatchlistItemOut(BaseModel):
    kind: Literal["insider", "company", "fund"]
    cik: int
    name: str
    added_at: datetime


class WatchlistOut(BaseModel):
    id: int
    name: str
    items: list[WatchlistItemOut]


class WatchlistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class WatchlistItemCreate(BaseModel):
    kind: Literal["insider", "company", "fund"]
    cik: int


# ---------------------------------------------------------------------------- health, jobs
class JobStatusOut(BaseModel):
    kind: str
    last_started_at: datetime | None
    last_finished_at: datetime | None
    last_status: str | None
    last_error: str | None


class ParseErrorOut(BaseModel):
    accession_no: str
    form_type: str
    filed_date: date
    error: str
    sec_url: str


class BackfillStep(BaseModel):
    step: str
    status: str
    done_units: int
    total_units: int | None
    updated_at: datetime | None


class Coverage(BaseModel):
    issuers_with_sector_pct: float | None
    cusip_value_mapped_pct: float | None
    decisions_with_prices_pct: float | None
    decisions_last_price_exit_pct: float | None


class HealthOut(BaseModel):
    status: Literal["ok", "warn", "error"]
    jobs: list[JobStatusOut]
    feed_delay_p50_s: float | None
    feed_delay_p95_s: float | None
    last_filing_seen_at: datetime | None
    parse_errors: list[ParseErrorOut]
    backfill: list[BackfillStep]
    coverage: Coverage
    sec_blocked_until: datetime | None


class JobRequestIn(BaseModel):
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)


class JobRequestOut(BaseModel):
    id: int
    kind: str
    status: str
    requested_at: datetime
    finished_at: datetime | None
    error: str | None
