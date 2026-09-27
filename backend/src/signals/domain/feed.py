"""Feed items: one row per filing, shaped for the live feed."""

from dataclasses import asdict, dataclass
from datetime import date, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from signals.db.models import FeedItem


@dataclass(frozen=True)
class FeedItemIn:
    accession_no: str
    form_type: str
    accepted_at: datetime | None = None
    filed_date: date | None = None
    issuer_cik: int | None = None
    issuer_name: str | None = None
    ticker: str | None = None
    owner_group: str | None = None
    owner_ciks: tuple[int, ...] = ()
    owner_names: str | None = None
    top_role: str | None = None
    direction: str | None = None
    codes: tuple[str, ...] = ()
    value_usd: float | None = None
    shares: float | None = None
    price: float | None = None
    plan_10b5_1: str | None = None
    badges: tuple[str, ...] = ()
    market_cap_usd: float | None = None
    sector: str | None = None
    summary: str = ""
    lag_days: int | None = None
    first_trade_date: date | None = None


def upsert_feed_item(session: Session, item: FeedItemIn) -> None:
    values = asdict(item)
    for key in ("owner_ciks", "codes", "badges"):
        values[key] = list(values[key])
    stmt = insert(FeedItem).values(**values)
    update = {k: stmt.excluded[k] for k in values if k != "accession_no"}
    session.execute(stmt.on_conflict_do_update(index_elements=["accession_no"], set_=update))


def _shares(n: float) -> str:
    return f"{n:,.0f}" if float(n).is_integer() else f"{n:,.2f}"


def summarize_trade(
    direction: str, shares: float | None, price: float | None, value: float | None
) -> str:
    """'Bought 12,000 sh @ $41.25 ($495,000)'; unknown pieces are left out."""
    verb = {"buy": "Bought", "sell": "Sold"}.get(direction, "Reported")
    parts = [verb]
    if shares is not None:
        parts.append(f"{_shares(shares)} sh")
    if price is not None:
        parts.append(f"@ ${price:,.2f}")
    if value is not None:
        parts.append(f"(${value:,.0f})")
    return " ".join(parts)
