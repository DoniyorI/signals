"""Decisions (spec 9.1): an owner group's same-direction open-market trades in one issuer.

Only codes P (buy) and S (sell) count. Trades each within 10 trading days of the previous
one form one episode; pre-planned (10b5-1) and discretionary trades never merge, so the
analytics toggle can drop the planned ones cleanly.
"""

from collections.abc import Collection, Sequence
from datetime import date, datetime, time
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import delete, insert, select, text
from sqlalchemy.orm import Session

from signals.db.models import Decision, DecisionOwner, Filing, InsiderTransaction
from signals.domain.calendars import ET, sec_business_days_between, trading_days_between
from signals.domain.owner_group import owner_group_ciks
from signals.domain.types import PlanFlag

EPISODE_GAP_TRADING_DAYS = 10
# An unknown acceptance time is treated as 16:00 ET on the filing date (spec 9.2).
UNKNOWN_ACCEPTANCE_TIME = time(16, 0)

DECISION_COLUMNS = (
    "owner_group",
    "owner_ciks",
    "issuer_cik",
    "direction",
    "is_planned",
    "plan_10b5_1",
    "first_trade_date",
    "last_trade_date",
    "shares",
    "value_usd",
    "vwap",
    "stake_change_pct",
    "is_new_position",
    "sell_fraction",
    "first_accession",
    "accessions",
    "accepted_at",
    "filed_date",
    "lag_days",
)

_TRADE_COLUMNS = (
    "tx_id",
    "accession_no",
    "owner_group",
    "issuer_cik",
    "code",
    "plan_10b5_1",
    "transaction_date",
    "shares",
    "price",
    "shares_owned_after",
    "row_no",
    "accepted_at",
    "filed_date",
)


def _float(value: Any) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def _date(value: Any) -> date | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    return value


def _datetime(value: Any) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return value


def effective_acceptance(accepted_at: datetime | None, filed_date: date) -> datetime:
    """When a filing became public; unknown acceptance counts as 16:00 ET on the filing date."""
    return accepted_at or datetime.combine(filed_date, UNKNOWN_ACCEPTANCE_TIME, ET)


def _frame(records: Sequence[dict[str, Any]]) -> pd.DataFrame:
    # object columns keep None (not NaN), Python dates and lists intact
    return pd.DataFrame(
        {c: pd.Series([r[c] for r in records], dtype=object) for c in DECISION_COLUMNS}
    )


def _episode(rows: Sequence[Any]) -> dict[str, Any]:
    first, last = rows[0], rows[-1]
    first_day: date = first.transaction_date
    shares = [s for r in rows if (s := _float(r.shares)) is not None]
    total_shares = float(sum(shares)) if shares else None
    priced = [
        (s, p)
        for r in rows
        if (s := _float(r.shares)) is not None and (p := _float(r.price)) is not None
    ]
    value_usd = float(sum(s * p for s, p in priced)) if priced else None
    day_one = [
        (s, p)
        for s, p in (
            (_float(r.shares), _float(r.price)) for r in rows if r.transaction_date == first_day
        )
        if s is not None and p is not None and s > 0 and p > 0
    ]
    vwap = sum(s * p for s, p in day_one) / sum(s for s, _ in day_one) if day_one else None

    stake_change_pct, is_new_position, sell_fraction = None, False, None
    if first.direction == "buy":
        after, bought = _float(first.shares_owned_after), _float(first.shares)
        if after is not None and bought is not None and total_shares is not None:
            before = after - bought
            if abs(before) <= 1e-9:
                is_new_position = True
            elif before > 0:
                stake_change_pct = total_shares / before
            # before < 0: the owned-after figure is inconsistent, so the stake is unknown
    else:
        after = _float(last.shares_owned_after)
        if after is not None and total_shares is not None and total_shares + after > 0:
            sell_fraction = total_shares / (total_shares + after)

    filings: dict[str, tuple[datetime, datetime | None, date]] = {}
    for r in rows:
        accepted, filed = _datetime(r.accepted_at), r.filed_date
        when = effective_acceptance(accepted, filed)
        if r.accession_no not in filings or when < filings[r.accession_no][0]:
            filings[r.accession_no] = (when, accepted, filed)
    ordered = sorted(filings.items(), key=lambda kv: (kv[1][0], kv[0]))
    first_accession, (_, accepted_at, filed_date) = ordered[0]
    public_on = accepted_at.astimezone(ET).date() if accepted_at is not None else filed_date

    plans = {r.plan_10b5_1 for r in rows}
    plan = next((p.value for p in (PlanFlag.FLAG, PlanFlag.FOOTNOTE) if p in plans), "none")
    return {
        "owner_group": first.owner_group,
        "owner_ciks": [int(c) for c in first.owner_ciks],
        "issuer_cik": int(first.issuer_cik),
        "direction": first.direction,
        "is_planned": bool(first.is_planned),
        "plan_10b5_1": plan,
        "first_trade_date": first_day,
        "last_trade_date": last.transaction_date,
        "shares": total_shares,
        "value_usd": value_usd,
        "vwap": vwap,
        "stake_change_pct": stake_change_pct,
        "is_new_position": is_new_position,
        "sell_fraction": sell_fraction,
        "first_accession": first_accession,
        "accessions": [acc for acc, _ in ordered],
        "accepted_at": accepted_at,
        "filed_date": filed_date,
        "lag_days": sec_business_days_between(first_day, public_on),
    }


def group_episodes(trades: pd.DataFrame) -> pd.DataFrame:
    """One row per decision (DECISION_COLUMNS) from P/S trade rows; see the module docstring."""
    if trades.empty:
        return _frame([])
    df = trades.loc[trades["code"].isin(["P", "S"])].copy()
    df["transaction_date"] = df["transaction_date"].map(_date)
    df["filed_date"] = df["filed_date"].map(_date)
    df = df.loc[df["transaction_date"].notna()]
    df["direction"] = np.where(df["code"] == "P", "buy", "sell")
    df["is_planned"] = df["is_planned"].astype(bool)
    df = df.sort_values(
        ["owner_group", "issuer_cik", "direction", "is_planned", "transaction_date", "row_order"],
        kind="stable",
    )
    episodes: list[dict[str, Any]] = []
    current: list[Any] = []
    key: tuple | None = None
    rows: list[Any] = list(df.itertuples(index=False))
    for row in rows:
        row_key = (row.owner_group, row.issuer_cik, row.direction, row.is_planned)
        if (
            current
            and row_key == key
            and trading_days_between(current[-1].transaction_date, row.transaction_date)
            <= EPISODE_GAP_TRADING_DAYS
        ):
            current.append(row)
            continue
        if current:
            episodes.append(_episode(current))
        current, key = [row], row_key
    if current:
        episodes.append(_episode(current))
    return _frame(episodes)


def load_trades(
    session: Session,
    *,
    issuer_ciks: Collection[int] | None = None,
    owner_ciks: Collection[int] | None = None,
) -> pd.DataFrame:
    """Non-superseded, non-derivative P and S rows with their filing's acceptance."""
    query = (
        select(
            InsiderTransaction.id,
            InsiderTransaction.accession_no,
            InsiderTransaction.owner_group,
            InsiderTransaction.issuer_cik,
            InsiderTransaction.code,
            InsiderTransaction.plan_10b5_1,
            InsiderTransaction.transaction_date,
            InsiderTransaction.shares,
            InsiderTransaction.price,
            InsiderTransaction.shares_owned_after,
            InsiderTransaction.row_no,
            Filing.accepted_at,
            Filing.filed_date,
        )
        .join(Filing, Filing.accession_no == InsiderTransaction.accession_no)
        .where(
            InsiderTransaction.table_kind == "nonderiv",
            InsiderTransaction.code.in_(("P", "S")),
            InsiderTransaction.superseded_by.is_(None),
            InsiderTransaction.transaction_date.is_not(None),
        )
    )
    if issuer_ciks is not None:
        query = query.where(InsiderTransaction.issuer_cik.in_(list(issuer_ciks)))
    if owner_ciks is not None:
        from signals.db.models import FilingOwner

        accessions = select(FilingOwner.accession_no).where(
            FilingOwner.owner_cik.in_(list(owner_ciks))
        )
        query = query.where(
            InsiderTransaction.accession_no.in_(accessions),
            text(
                "string_to_array(insider_transactions.owner_group, '|')::bigint[] "
                "&& CAST(:owners AS bigint[])"
            ),
        ).params(owners=list(owner_ciks))
    rows = [tuple(r) for r in session.execute(query)]
    df = pd.DataFrame(
        {c: pd.Series([r[i] for r in rows], dtype=object) for i, c in enumerate(_TRADE_COLUMNS)}
    )
    if df.empty:
        return df
    df["owner_ciks"] = df["owner_group"].map(owner_group_ciks)
    df["is_planned"] = df["plan_10b5_1"] != PlanFlag.NONE.value
    when = [
        effective_acceptance(a, f).timestamp()
        for a, f in zip(df["accepted_at"], df["filed_date"], strict=True)
    ]
    order = np.lexsort((df["row_no"].to_numpy(dtype=np.int64), df["accession_no"].to_numpy(), when))
    row_order = np.empty(len(df), dtype=np.int64)
    row_order[order] = np.arange(len(df))
    df["row_order"] = row_order
    return df.rename(columns={"id": "tx_id"})


def build_decisions(
    session: Session,
    *,
    issuer_ciks: Collection[int] | None = None,
    owner_ciks: Collection[int] | None = None,
) -> int:
    """Replace `decisions` and `decision_owners` for the issuers (or all). Returns the count.

    Deleting a decision cascades to its `decision_owners` and `decision_returns`.
    """
    trades = load_trades(session, issuer_ciks=issuer_ciks, owner_ciks=owner_ciks)
    scope = delete(Decision)
    if issuer_ciks is not None:
        scope = scope.where(Decision.issuer_cik.in_(list(issuer_ciks)))
    if owner_ciks is not None:
        ids = select(DecisionOwner.decision_id).where(DecisionOwner.owner_cik.in_(list(owner_ciks)))
        scope = scope.where(Decision.id.in_(ids))
    session.execute(scope)
    episodes = group_episodes(trades)
    if episodes.empty:
        return 0
    records = [
        {c: row[c] for c in DECISION_COLUMNS if c != "owner_ciks"}
        for row in episodes.to_dict("records")
    ]
    ids = session.scalars(
        insert(Decision).returning(Decision.id, sort_by_parameter_order=True), records
    ).all()
    owners = [
        {"decision_id": decision_id, "owner_cik": cik}
        for decision_id, ciks in zip(ids, episodes["owner_ciks"], strict=True)
        for cik in ciks
    ]
    session.execute(insert(DecisionOwner), owners)
    return len(ids)
