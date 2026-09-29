"""Queries behind `GET /screener/insiders` and `GET /screener/funds`.

Both screeners are driven FROM `profile_stats` (an inner join to `owners`/`fund_managers`),
so a profile with no stats row for the requested kind/basis/toggle never appears -- the same
rule that keeps NEWBIE (no decisions yet) off the insider screener. `profile_windows` is
joined once more, scoped to the requested `window`, purely so `min_return`/`max_return` and
the `return` sort key can see it; the full four-window pivot shown in each row is fetched
separately afterward, following the `{row.window: row for row in ...}` pattern from
`queries/funds.py::get_fund_header`.
"""

from collections.abc import Callable, Sequence
from datetime import date

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, aliased

from signals.api.pagination import SortColumn, SortKey, paginate, parse_date, parse_float, parse_int
from signals.api.queries.common import WINDOW_ORDER, issuer_refs, rating_of
from signals.api.schemas import (
    FundScreenPage,
    FundScreenRow,
    InsiderScreenPage,
    InsiderScreenRow,
    OwnerRef,
)
from signals.db.models import (
    FundManager,
    FundNavDaily,
    Owner,
    OwnerRole,
    ProfileStats,
    ProfileWindow,
)

Windows = dict[int, dict[str, float | None]]


def _sort_column(sort: str, return_col: SortColumn) -> tuple[SortColumn, Callable]:
    columns: dict[str, tuple[SortColumn, Callable]] = {
        "rating": (ProfileStats.rating, parse_int),
        "avg_roi_6m": (ProfileStats.avg_roi_6m, parse_float),
        "hit_rate": (ProfileStats.hit_rate, parse_float),
        "n_decisions": (ProfileStats.n_decisions, parse_int),
        "last_trade_date": (ProfileStats.last_trade_date, parse_date),
        "return": (return_col, parse_float),
    }
    return columns.get(sort, columns["rating"])


def _windows_by_cik(
    session: Session, kind: str, ciks: Sequence[int], basis: str, toggle: bool
) -> Windows:
    if not ciks:
        return {}
    rows = session.execute(
        select(ProfileWindow).where(
            ProfileWindow.kind == kind,
            ProfileWindow.cik.in_(ciks),
            ProfileWindow.basis == basis,
            ProfileWindow.include_10b5_1.is_(toggle),
        )
    ).scalars()
    out: Windows = {}
    for row in rows:
        out.setdefault(row.cik, {})[row.window] = row.ret
    return out


def _window_dict(windows: Windows, cik: int) -> dict[str, float | None]:
    by_name = windows.get(cik, {})
    return {name: by_name.get(name) for name in WINDOW_ORDER}


# --------------------------------------------------------------------------- insiders
def screen_insiders(
    session: Session,
    *,
    roles: Sequence[str] | None,
    sectors: Sequence[str] | None,
    min_decisions: int,
    last_trade_from: date | None,
    last_trade_to: date | None,
    min_rating: int | None,
    confidence: Sequence[str] | None,
    window: str,
    min_return: float | None,
    max_return: float | None,
    risk: Sequence[str] | None,
    basis: str,
    include_10b5_1: bool,
    sort: str,
    order: str,
    cursor: str | None,
    limit: int,
) -> InsiderScreenPage:
    window_row = aliased(ProfileWindow)
    stmt = (
        select(ProfileStats)
        .join(Owner, Owner.cik == ProfileStats.cik)
        .outerjoin(
            OwnerRole,
            and_(
                OwnerRole.owner_cik == ProfileStats.cik,
                OwnerRole.issuer_cik == ProfileStats.primary_issuer_cik,
            ),
        )
        .outerjoin(
            window_row,
            and_(
                window_row.kind == ProfileStats.kind,
                window_row.cik == ProfileStats.cik,
                window_row.basis == ProfileStats.basis,
                window_row.include_10b5_1 == ProfileStats.include_10b5_1,
                window_row.window == window,
            ),
        )
        .where(
            ProfileStats.kind == "insider",
            ProfileStats.basis == basis,
            ProfileStats.include_10b5_1.is_(include_10b5_1),
            ProfileStats.n_complete >= min_decisions,
        )
    )
    if roles:
        stmt = stmt.where(OwnerRole.roles.overlap(list(roles)))
    if sectors:
        stmt = stmt.where(ProfileStats.sector.in_(sectors))
    if last_trade_from is not None:
        stmt = stmt.where(ProfileStats.last_trade_date >= last_trade_from)
    if last_trade_to is not None:
        stmt = stmt.where(ProfileStats.last_trade_date <= last_trade_to)
    if min_rating is not None:
        stmt = stmt.where(ProfileStats.rating >= min_rating)
    if confidence:
        stmt = stmt.where(ProfileStats.confidence.in_(confidence))
    if min_return is not None:
        stmt = stmt.where(window_row.ret >= min_return)
    if max_return is not None:
        stmt = stmt.where(window_row.ret <= max_return)
    if risk:
        stmt = stmt.where(ProfileStats.risk_label.in_(risk))

    sort_col, parse = _sort_column(sort, window_row.ret)
    is_desc = order != "asc"
    keys = [
        SortKey("v", sort_col, desc=is_desc, nullable=True, parse=parse),
        SortKey("c", ProfileStats.cik, desc=is_desc, parse=parse_int),
    ]
    rows, next_cursor = paginate(session, stmt, keys, cursor, limit)
    stats_list = [row[0] for row in rows]
    return InsiderScreenPage(
        items=_insider_rows(session, stats_list, basis=basis, include_10b5_1=include_10b5_1),
        next_cursor=next_cursor,
    )


def _insider_rows(
    session: Session, stats_list: Sequence[ProfileStats], *, basis: str, include_10b5_1: bool
) -> list[InsiderScreenRow]:
    if not stats_list:
        return []
    ciks = [s.cik for s in stats_list]
    owners = {o.cik: o for o in session.execute(select(Owner).where(Owner.cik.in_(ciks))).scalars()}
    issuer_ciks = {s.primary_issuer_cik for s in stats_list if s.primary_issuer_cik is not None}
    issuers = issuer_refs(session, issuer_ciks)
    role_rows = session.execute(select(OwnerRole).where(OwnerRole.owner_cik.in_(ciks))).scalars()
    roles_by_pair = {(r.owner_cik, r.issuer_cik): list(r.roles or []) for r in role_rows}
    windows = _windows_by_cik(session, "insider", ciks, basis, include_10b5_1)

    items = []
    for s in stats_list:
        owner = owners.get(s.cik)
        primary_issuer_cik = s.primary_issuer_cik
        roles = roles_by_pair.get((s.cik, primary_issuer_cik), []) if primary_issuer_cik else []
        items.append(
            InsiderScreenRow(
                owner=OwnerRef(cik=s.cik, name=owner.name if owner else f"CIK {s.cik}"),
                primary_issuer=issuers.get(primary_issuer_cik) if primary_issuer_cik else None,
                roles=roles,
                sector=s.sector,
                rating=rating_of(s),
                avg_roi_6m=s.avg_roi_6m,
                hit_rate=s.hit_rate,
                n_decisions=s.n_decisions,
                last_trade_date=s.last_trade_date,
                windows=_window_dict(windows, s.cik),
                risk_label=s.risk_label,  # type: ignore[arg-type]
            )
        )
    return items


# --------------------------------------------------------------------------- funds
def screen_funds(
    session: Session,
    *,
    sectors: Sequence[str] | None,
    min_rating: int | None,
    confidence: Sequence[str] | None,
    window: str,
    min_return: float | None,
    max_return: float | None,
    risk: Sequence[str] | None,
    basis: str,
    tracked_only: bool,
    sort: str,
    order: str,
    cursor: str | None,
    limit: int,
) -> FundScreenPage:
    window_row = aliased(ProfileWindow)
    stmt = (
        select(ProfileStats)
        .join(FundManager, FundManager.cik == ProfileStats.cik)
        .outerjoin(
            window_row,
            and_(
                window_row.kind == ProfileStats.kind,
                window_row.cik == ProfileStats.cik,
                window_row.basis == ProfileStats.basis,
                window_row.include_10b5_1 == ProfileStats.include_10b5_1,
                window_row.window == window,
            ),
        )
        .where(
            ProfileStats.kind == "fund",
            ProfileStats.basis == basis,
            ProfileStats.include_10b5_1.is_(False),
        )
    )
    if tracked_only:
        stmt = stmt.where(FundManager.is_tracked.is_(True))
    if sectors:
        stmt = stmt.where(ProfileStats.sector.in_(sectors))
    if min_rating is not None:
        stmt = stmt.where(ProfileStats.rating >= min_rating)
    if confidence:
        stmt = stmt.where(ProfileStats.confidence.in_(confidence))
    if min_return is not None:
        stmt = stmt.where(window_row.ret >= min_return)
    if max_return is not None:
        stmt = stmt.where(window_row.ret <= max_return)
    if risk:
        stmt = stmt.where(ProfileStats.risk_label.in_(risk))

    sort_col, parse = _sort_column(sort, window_row.ret)
    is_desc = order != "asc"
    keys = [
        SortKey("v", sort_col, desc=is_desc, nullable=True, parse=parse),
        SortKey("c", ProfileStats.cik, desc=is_desc, parse=parse_int),
    ]
    rows, next_cursor = paginate(session, stmt, keys, cursor, limit)
    stats_list = [row[0] for row in rows]
    return FundScreenPage(
        items=_fund_rows(session, stats_list, basis=basis), next_cursor=next_cursor
    )


def _fund_rows(
    session: Session, stats_list: Sequence[ProfileStats], *, basis: str
) -> list[FundScreenRow]:
    if not stats_list:
        return []
    ciks = [s.cik for s in stats_list]
    managers = {
        m.cik: m
        for m in session.execute(select(FundManager).where(FundManager.cik.in_(ciks))).scalars()
    }
    windows = _windows_by_cik(session, "fund", ciks, basis, False)
    coverage_rows = session.execute(
        select(FundNavDaily.cik, FundNavDaily.coverage)
        .where(FundNavDaily.cik.in_(ciks), FundNavDaily.basis == "filed")
        .order_by(FundNavDaily.cik, FundNavDaily.date.desc())
        .ext(distinct_on(FundNavDaily.cik))
    ).all()
    coverage_by_cik = {row.cik: row.coverage for row in coverage_rows}

    items = []
    for s in stats_list:
        manager = managers.get(s.cik)
        items.append(
            FundScreenRow(
                fund=OwnerRef(cik=s.cik, name=manager.name if manager else f"CIK {s.cik}"),
                latest_value_usd=manager.latest_value_usd if manager else None,
                positions=manager.latest_positions if manager else None,
                top_sector=s.sector,
                rating=rating_of(s),
                windows=_window_dict(windows, s.cik),
                risk_label=s.risk_label,  # type: ignore[arg-type]
                coverage_pct=coverage_by_cik.get(s.cik),
            )
        )
    return items
