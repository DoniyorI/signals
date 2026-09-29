"""Helpers shared by the API query modules: the clock, issuer refs, prices, ratings, links."""

from collections.abc import Collection, Sequence
from datetime import date, datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from signals.analytics.types import WindowResult
from signals.api.schemas import CurvePoint, IssuerRef, Rating, WindowStat
from signals.db.models import Issuer, PriceDaily, ProfileStats, Ticker
from signals.domain.accession import filing_index_url
from signals.domain.calendars import now_et
from signals.domain.types import Window

WINDOW_ORDER = ("ytd", "1y", "3y", "5y")
HORIZON_ORDER = ("1m", "3m", "6m", "12m")


def now() -> datetime:
    """The API clock (US Eastern). Tests freeze it by patching `now_et` in this module."""
    return now_et()


def today() -> date:
    return now().date()


def sec_url(cik: int, accession: str) -> str:
    """The filing's index page on sec.gov. A malformed accession falls back to the
    company's filing list rather than failing the whole response."""
    try:
        return filing_index_url(cik, accession)
    except ValueError:
        return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"


def current_symbols(session: Session, ciks: Collection[int]) -> dict[int, str]:
    """Current ticker per issuer: the same rule as `domain.tickers.current_symbol`, batched
    (open interval first, then the latest start)."""
    if not ciks:
        return {}
    rows = session.execute(
        select(Ticker.issuer_cik, Ticker.symbol)
        .where(Ticker.issuer_cik.in_(list(ciks)))
        .order_by(Ticker.issuer_cik, Ticker.valid_to.desc().nulls_first(), Ticker.valid_from.desc())
        .ext(distinct_on(Ticker.issuer_cik))
    ).all()
    return {row.issuer_cik: row.symbol for row in rows}


def issuer_refs(session: Session, ciks: Collection[int]) -> dict[int, IssuerRef]:
    wanted = {int(c) for c in ciks}
    if not wanted:
        return {}
    names = {
        row.cik: row.name
        for row in session.execute(select(Issuer.cik, Issuer.name).where(Issuer.cik.in_(wanted)))
    }
    symbols = current_symbols(session, wanted)
    return {
        cik: IssuerRef(cik=cik, name=names.get(cik) or f"CIK {cik}", ticker=symbols.get(cik))
        for cik in wanted
    }


def issuer_ref(session: Session, cik: int) -> IssuerRef:
    return issuer_refs(session, [cik])[cik]


def latest_close(session: Session, symbol: str) -> tuple[float, date] | None:
    row = session.execute(
        select(PriceDaily.close, PriceDaily.date)
        .where(PriceDaily.symbol == symbol)
        .order_by(PriceDaily.date.desc())
        .limit(1)
    ).first()
    return (row.close, row.date) if row is not None else None


def rating_of(stats: ProfileStats | None) -> Rating:
    """The reliability rating; a missing stats row means "not enough data yet"."""
    if stats is None:
        return Rating(score=None, confidence=None, n=0)
    return Rating(score=stats.rating, confidence=stats.confidence, n=stats.n_complete)  # pyright: ignore[reportArgumentType]


def ordered_windows(windows: Sequence[WindowResult]) -> list[WindowResult]:
    """`windows` sorted into the canonical ytd/1y/3y/5y order (the curve service may not)."""
    by_name = {w.window: w for w in windows}
    return [by_name[Window(name)] for name in WINDOW_ORDER if Window(name) in by_name]


def window_stat(w: WindowResult) -> WindowStat:
    return WindowStat(
        window=w.window,  # type: ignore[arg-type]
        ret=w.ret,
        ret_spy=w.ret_spy,
        ret_qqq=w.ret_qqq,
        ret_sector=w.ret_sector,
        annualized=w.annualized,
        vol=w.vol,
        max_drawdown=w.max_drawdown,
        beta=w.beta,
        time_invested_pct=w.time_invested_pct,
    )


def curve_points(points: pd.DataFrame) -> list[CurvePoint]:
    """`points` is indexed by date with columns nav/spy/qqq/sector (see analytics.types.Curve)."""
    out = []
    for idx, row in points.iterrows():
        day = idx if isinstance(idx, date) else pd.Timestamp(idx).date()  # type: ignore[arg-type]
        out.append(
            CurvePoint(
                date=day, nav=row["nav"], spy=row["spy"], qqq=row["qqq"], sector=row["sector"]
            )
        )
    return out
