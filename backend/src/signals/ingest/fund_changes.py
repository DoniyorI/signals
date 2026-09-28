"""Quarter-over-quarter 13F changes, fund manager summary stats, and a unit sanity check.

Everything reads *effective* positions (after amendments), summed per
(filer, period, CUSIP, put/call), and runs as set-based SQL inside the caller's transaction.
"""

from collections.abc import Collection
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from signals.db.models import FundManager, FundPositionChange
from signals.domain.appstate import set_state
from signals.ingest.normalize_funds import expire_instances

ANOMALY_STATE_KEY = "f13f_unit_anomalies"
ANOMALY_SAMPLE = 20
# A quarter-end can fall on a weekend or holiday: use the last close within this many days.
CLOSE_LOOKBACK_DAYS = 7


def _filters(
    filer_ciks: Collection[int] | None, periods: Collection[date] | None, alias: str = ""
) -> tuple[str, dict[str, Any]]:
    prefix = f"{alias}." if alias else ""
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if filer_ciks is not None:
        clauses.append(f"{prefix}filer_cik = ANY(CAST(:filers AS bigint[]))")
        params["filers"] = sorted({int(c) for c in filer_ciks})
    if periods is not None:
        clauses.append(f"{prefix}period = ANY(CAST(:periods AS date[]))")
        params["periods"] = sorted(set(periods))
    return " AND ".join(clauses), params


_CHANGES_SQL = """
WITH eff AS (
    SELECT filer_cik, period, cusip, put_call,
           sum(coalesce(shares, 0)) AS shares, sum(coalesce(value_usd, 0)) AS value_usd
    FROM fund_positions
    WHERE is_effective {filer_filter}
    GROUP BY filer_cik, period, cusip, put_call
),
periods AS (
    SELECT filer_cik, period,
           lag(period) OVER (PARTITION BY filer_cik ORDER BY period) AS prev_period
    FROM (SELECT DISTINCT filer_cik, period FROM eff) d
),
targets AS (
    SELECT filer_cik, period, prev_period FROM periods WHERE TRUE {period_filter}
),
totals AS (
    SELECT filer_cik, period, sum(value_usd) FILTER (WHERE put_call = '') AS total
    FROM eff GROUP BY filer_cik, period
),
cur AS (
    SELECT t.filer_cik, t.period, e.cusip, e.put_call, e.shares, e.value_usd
    FROM targets t JOIN eff e ON e.filer_cik = t.filer_cik AND e.period = t.period
),
prev AS (
    SELECT t.filer_cik, t.period, e.cusip, e.put_call, e.shares, e.value_usd
    FROM targets t JOIN eff e ON e.filer_cik = t.filer_cik AND e.period = t.prev_period
),
joined AS (
    SELECT coalesce(c.filer_cik, p.filer_cik) AS filer_cik,
           coalesce(c.period, p.period) AS period,
           coalesce(c.cusip, p.cusip) AS cusip,
           coalesce(c.put_call, p.put_call) AS put_call,
           c.cusip IS NOT NULL AS has_cur, p.cusip IS NOT NULL AS has_prev,
           c.shares AS cur_shares, c.value_usd AS cur_value,
           p.shares AS prev_shares, p.value_usd AS prev_value
    FROM cur c
    FULL JOIN prev p
      ON p.filer_cik = c.filer_cik AND p.period = c.period
     AND p.cusip = c.cusip AND p.put_call = c.put_call
)
INSERT INTO fund_position_changes (
    filer_cik, period, cusip, put_call, prev_shares, shares, change,
    shares_change_pct, value_usd, weight, prev_weight
)
SELECT j.filer_cik, j.period, j.cusip, j.put_call,
       j.prev_shares,
       coalesce(j.cur_shares, 0),
       CASE WHEN NOT j.has_prev THEN 'NEW'
            WHEN NOT j.has_cur THEN 'EXIT'
            WHEN j.cur_shares > j.prev_shares THEN 'ADD'
            WHEN j.cur_shares < j.prev_shares THEN 'TRIM'
            ELSE 'SAME' END,
       CASE WHEN j.prev_shares > 0
            THEN (coalesce(j.cur_shares, 0) - j.prev_shares) / j.prev_shares END,
       coalesce(j.cur_value, 0),
       CASE WHEN j.put_call = '' THEN coalesce(j.cur_value, 0) / NULLIF(tc.total, 0) END,
       CASE WHEN j.put_call = '' AND j.has_prev THEN j.prev_value / NULLIF(tp.total, 0) END
FROM joined j
JOIN targets t ON t.filer_cik = j.filer_cik AND t.period = j.period
LEFT JOIN totals tc ON tc.filer_cik = j.filer_cik AND tc.period = j.period
LEFT JOIN totals tp ON tp.filer_cik = j.filer_cik AND tp.period = t.prev_period
"""


def compute_fund_changes(
    session: Session,
    *,
    filer_ciks: Collection[int] | None = None,
    periods: Collection[date] | None = None,
) -> int:
    """Rebuild `fund_position_changes` for the selected filers and periods (all by default).

    NEW has no row in the previous period, EXIT is a previous row absent now (written with
    zero shares and value), then ADD / TRIM / SAME by share count. "Previous" is the filer's
    latest earlier period with effective positions. Weights are shares of the period's
    stock (put_call '') value; option rows get no weight. Returns rows written.
    """
    session.flush()
    where, params = _filters(filer_ciks, periods)
    session.execute(
        text(f"DELETE FROM fund_position_changes WHERE TRUE {'AND ' + where if where else ''}"),
        params,
    )
    filer_filter, filer_params = _filters(filer_ciks, None)
    period_filter, period_params = _filters(None, periods)
    sql = _CHANGES_SQL.format(
        filer_filter=f"AND {filer_filter}" if filer_filter else "",
        period_filter=f"AND {period_filter}" if period_filter else "",
    )
    result = session.execute(text(sql), {**filer_params, **period_params})
    expire_instances(session, FundPositionChange)
    return int(getattr(result, "rowcount", 0) or 0)


_MANAGER_STATS_SQL = """
WITH latest AS (
    SELECT filer_cik, max(period) AS period
    FROM fund_positions
    WHERE is_effective {filer_filter}
    GROUP BY filer_cik
),
agg AS (
    SELECT p.filer_cik, l.period,
           sum(coalesce(p.value_usd, 0)) AS value_usd,
           count(DISTINCT p.cusip) FILTER (WHERE p.put_call = '') AS positions
    FROM fund_positions p
    JOIN latest l ON l.filer_cik = p.filer_cik AND l.period = p.period
    WHERE p.is_effective
    GROUP BY p.filer_cik, l.period
)
UPDATE fund_managers m
SET latest_period = a.period, latest_value_usd = a.value_usd,
    latest_positions = a.positions, updated_at = now()
FROM agg a
WHERE m.cik = a.filer_cik
"""


def refresh_fund_manager_stats(
    session: Session, *, filer_ciks: Collection[int] | None = None
) -> int:
    """Set each manager's latest period, its effective value and stock position count.

    Managers without effective positions (13F-NT filers, for example) are left unchanged.
    Returns the number of managers updated.
    """
    session.flush()
    filer_filter, params = _filters(filer_ciks, None)
    sql = _MANAGER_STATS_SQL.format(filer_filter=f"AND {filer_filter}" if filer_filter else "")
    result = session.execute(text(sql), params)
    expire_instances(session, FundManager)
    return int(getattr(result, "rowcount", 0) or 0)


_ANOMALY_SQL = """
WITH flagged AS (
    SELECT p.accession_no, p.cusip, p.period, p.value_usd / p.shares AS implied, px.close
    FROM fund_positions p
    JOIN securities s ON s.cusip = p.cusip AND s.ticker IS NOT NULL
    JOIN LATERAL (
        SELECT d.close FROM prices_daily d
        WHERE d.symbol = s.ticker AND d.date <= p.period AND d.date >= p.period - :lookback
        ORDER BY d.date DESC
        LIMIT 1
    ) px ON px.close > 0
    WHERE p.is_effective AND p.put_call = '' AND coalesce(p.sh_prn, 'SH') = 'SH'
      AND p.shares > 0 AND p.value_usd IS NOT NULL {period_filter}
)
SELECT accession_no, cusip, period, implied, close, count(*) OVER () AS n
FROM flagged
WHERE implied / close > 100 OR implied / close < 0.01
ORDER BY period DESC, accession_no, cusip
LIMIT :sample
"""


def flag_value_unit_anomalies(session: Session, *, periods: Collection[date] | None = None) -> int:
    """Count effective stock positions whose implied price (value / shares) is more than 100x
    off the market close, the signature of a filer mixing up thousands and dollars.

    The close is the last one on or before the period date (quarter-ends can fall on a
    weekend). Options and principal-amount (PRN) rows are skipped. The count and a sample
    go to `app_state["f13f_unit_anomalies"]`; returns the count.
    """
    session.flush()
    period_filter, params = _filters(None, periods, alias="p")
    sql = _ANOMALY_SQL.format(period_filter=f"AND {period_filter}" if period_filter else "")
    rows = session.execute(
        text(sql), {**params, "lookback": CLOSE_LOOKBACK_DAYS, "sample": ANOMALY_SAMPLE}
    ).all()
    count = int(rows[0].n) if rows else 0
    sample = [
        {
            "accession": r.accession_no,
            "cusip": r.cusip,
            "period": r.period.isoformat(),
            "implied": float(r.implied),
            "close": float(r.close),
        }
        for r in rows
    ]
    set_state(session, ANOMALY_STATE_KEY, {"count": count, "sample": sample})
    return count
