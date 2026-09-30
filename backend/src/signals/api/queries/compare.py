"""Queries behind `GET /compare`.

Up to 4 profiles (insiders and/or tracked funds) side by side: each gets its own rating,
windows and curve from the curve service, plus an allocation breakdown reused straight from
the insider-holdings / fund-holdings queries. Curves are rebased to a common start date so
every profile's line begins at 1.0 -- see `_common_start`/`_rebase`.
"""

from datetime import date

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from signals.api.queries.common import WINDOW_ORDER, curve_points, rating_of, today
from signals.api.queries.funds import get_fund_holdings
from signals.api.queries.insiders import get_holdings
from signals.api.schemas import AllocationSlice, CompareOut, CompareProfile, WindowStat
from signals.db.models import FundManager, Owner, ProfileStats, ProfileWindow

MAX_PROFILES = 4


def parse_ids(ids: str) -> list[tuple[str, int]]:
    """`ids` like `insider:123,fund:456`, 1 to 4 entries. Anything else is a 400."""
    parts = [p.strip() for p in ids.split(",") if p.strip()]
    if not (1 <= len(parts) <= MAX_PROFILES):
        raise HTTPException(400, "ids must list 1 to 4 profiles")
    parsed: list[tuple[str, int]] = []
    for part in parts:
        kind, sep, cik_text = part.partition(":")
        if not sep or kind not in ("insider", "fund") or not cik_text.isdigit():
            raise HTTPException(400, f"invalid id {part!r}; expected insider:<cik> or fund:<cik>")
        parsed.append((kind, int(cik_text)))
    return parsed


def _name(session: Session, kind: str, cik: int) -> str:
    if kind == "insider":
        owner = session.get(Owner, cik)
        if owner is None:
            raise HTTPException(404, f"insider {cik} not found")
        return owner.name
    manager = session.get(FundManager, cik)
    if manager is None:
        raise HTTPException(404, f"fund {cik} not found")
    return manager.name


def _window_stat(row: ProfileWindow) -> WindowStat:
    return WindowStat(
        window=row.window,  # type: ignore[arg-type]
        ret=row.ret,
        ret_spy=row.ret_spy,
        ret_qqq=row.ret_qqq,
        ret_sector=row.ret_sector,
        annualized=row.annualized,
        vol=row.vol,
        max_drawdown=row.max_drawdown,
        beta=row.beta,
        time_invested_pct=row.time_invested_pct,
    )


def _windows(
    session: Session, kind: str, cik: int, basis: str, include_10b5_1: bool
) -> list[WindowStat]:
    rows = {
        row.window: row
        for row in session.execute(
            select(ProfileWindow).where(
                ProfileWindow.kind == kind,
                ProfileWindow.cik == cik,
                ProfileWindow.basis == basis,
                ProfileWindow.include_10b5_1.is_(include_10b5_1),
            )
        ).scalars()
    }
    return [_window_stat(rows[name]) for name in WINDOW_ORDER if name in rows]


def _allocation(session: Session, kind: str, cik: int) -> list[AllocationSlice]:
    if kind == "insider":
        return get_holdings(session, cik).by_sector
    return get_fund_holdings(session, cik, period=None, cursor=None, limit=50).by_sector


def _common_start(curves: list) -> date | None:
    starts = [c.points.index.min() for c in curves if not c.points.empty]
    return max(starts) if starts else None


def _rebase(points: pd.DataFrame, start: date) -> pd.DataFrame:
    trimmed = points.loc[points.index >= start]
    if trimmed.empty:
        return trimmed
    return trimmed.div(trimmed.iloc[0])


def build_compare(
    session: Session, curve_service, ids: str, *, basis: str, include_10b5_1: bool
) -> CompareOut:
    parsed = parse_ids(ids)
    names = [_name(session, kind, cik) for kind, cik in parsed]

    curves = []
    for kind, cik in parsed:
        try:
            if kind == "insider":
                curve = curve_service.insider_curve(
                    session, cik, basis=basis, include_10b5_1=include_10b5_1, as_of=today()
                )
            else:
                curve = curve_service.fund_curve(session, cik, basis=basis, as_of=today())
        except LookupError as exc:
            raise HTTPException(404, f"performance is unavailable for {kind}:{cik}") from exc
        curves.append(curve)

    common_start = _common_start(curves)

    profiles = []
    for (kind, cik), name, curve in zip(parsed, names, curves, strict=True):
        toggle = include_10b5_1 if kind == "insider" else False
        stats = session.get(ProfileStats, (kind, cik, basis, toggle))
        rebased = _rebase(curve.points, common_start) if common_start is not None else curve.points
        profiles.append(
            CompareProfile(
                id=f"{kind}:{cik}",
                kind=kind,  # type: ignore[arg-type]
                name=name,
                rating=rating_of(stats),
                avg_roi_6m=stats.avg_roi_6m if stats else None,
                hit_rate=stats.hit_rate if stats else None,
                windows=_windows(session, kind, cik, basis, toggle),
                curve=curve_points(rebased),
                by_sector=_allocation(session, kind, cik),
            )
        )
    return CompareOut(basis=basis, profiles=profiles)  # type: ignore[arg-type]
