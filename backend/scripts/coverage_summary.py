"""Print the database-only completeness report; no SEC/provider traffic or writes.

Run from backend/: uv run python scripts/coverage_summary.py [--as-of YYYY-MM-DD]
"""

import argparse
from collections.abc import Mapping
from datetime import date
from typing import Any


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def render_report(report: Mapping[str, Any]) -> str:
    rows = [
        f"Coverage as of {report['as_of']}",
        f"SEC baseline: {report['checked_at'] or 'Not checked yet'}",
        "",
        "Quarter  Family      Indexed  Stored    Coverage  Status",
    ]
    for row in report["quarters"]:
        indexed = "n/a" if row["indexed"] is None else f"{row['indexed']:,}"
        rows.append(
            f"{row['year']}Q{row['quarter']}   {row['family']:<10}  {indexed:>7}  "
            f"{row['stored']:>7,}  {_pct(row['pct']):>10}  {row['status']}"
        )
    rows.extend(["", "Insider transactions by year"])
    rows.extend(f"{row['year']}: {row['count']:,}" for row in report["insider_transactions"])
    prices = report["prices"]
    rows.append(
        f"\nPrices through {prices['through']}: {prices['covered']}/{prices['total']} "
        f"({_pct(prices['pct'])}); {'loading' if prices['loading'] else 'no active price load'}"
    )
    rows.append("Six-month returns (elapsed horizons only)")
    for basis in ("filed", "executed"):
        coverage = report["returns"][basis]
        rows.append(
            f"{basis}: {coverage['covered']}/{coverage['eligible']} ({_pct(coverage['pct'])})"
        )
    funds = report["funds"]
    rows.append(
        f"Tracked funds: {funds['tracked']}; fund quarters: "
        f"{funds['covered']}/{funds['total']} ({_pct(funds['pct'])})"
    )
    rows.append(f"Unavailable accessions: {len(report['unavailable'])}")
    rows.extend(
        f"{row['accession_no']}: {row['attempts']} attempts; {row['error']}"
        for row in report["unavailable"]
    )
    return "\n".join(rows)


def main() -> None:
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from signals.completeness import completeness_report
    from signals.config import get_settings
    from signals.db.session import make_engine
    from signals.domain.calendars import now_et

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, default=now_et().date())
    args = parser.parse_args()
    engine = make_engine(get_settings().database_url)
    try:
        with Session(engine) as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            report = completeness_report(session, as_of=args.as_of)
            print(render_report(report.model_dump(mode="json")))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
