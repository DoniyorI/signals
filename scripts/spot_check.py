"""Compare stored Form 4 P/S rows with freshly archived SEC filings.

Run inside the worker container with the scheduled worker stopped. The worker advisory
lock prevents concurrent SEC clients; no writes are made to parsed data or checkpoints.
"""

import argparse
from collections.abc import Sequence
from datetime import date, datetime
from math import isclose
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signals.config import get_settings
from signals.db.models import Filing, InsiderTransaction
from signals.db.session import make_engine, make_session_factory, session_scope
from signals.domain.accession import filing_index_url
from signals.domain.appstate import set_state
from signals.ingest.handlers.insider import _ownership_xml
from signals.ingest.parsers.ownership import OwnershipDoc, parse_ownership
from signals.sec.archive import RawArchive
from signals.sec.client import build_sec_client
from signals.sec.sgml import SgmlFiling
from signals.worker import worker_lock


def pick_sample(session: Session, n: int = 20, seed: int = 7) -> list[str]:
    """Deterministic year-balanced sample, bounded results and no full-table random sort.

    Twenty cannot fit two filings from each of eleven years. Take one per populated year,
    then a second round while capacity remains, and fill any remainder deterministically.
    """
    if n < 1:
        return []
    eligible = (
        select(Filing.accession_no)
        .where(
            Filing.form_type.in_(("4", "4/A")),
            Filing.filed_date >= date(2016, 1, 1),
            Filing.filed_date < date(2027, 1, 1),
            select(InsiderTransaction.id)
            .where(
                InsiderTransaction.accession_no == Filing.accession_no,
                InsiderTransaction.code.in_(("P", "S")),
            )
            .exists(),
        )
        .order_by(func.md5(Filing.accession_no + str(seed)), Filing.accession_no)
    )
    by_year = [
        list(
            session.scalars(
                eligible.where(
                    Filing.filed_date >= date(year, 1, 1), Filing.filed_date < date(year + 1, 1, 1)
                ).limit(2)
            )
        )
        for year in range(2016, 2027)
    ]
    sample = [rows[round_no] for round_no in range(2) for rows in by_year if len(rows) > round_no][
        :n
    ]
    if len(sample) < n:
        sample.extend(
            session.scalars(
                eligible.where(Filing.accession_no.not_in(sample)).limit(n - len(sample))
            )
        )
    return sample


def compare(db_rows: Sequence[Any], parsed_doc: OwnershipDoc) -> list[str]:
    """Match natural row identities and values, retaining missing-vs-null distinctions."""
    stored = {(r.table_kind, r.row_no): r for r in db_rows if r.code in ("P", "S")}
    fresh = {
        (r.table_kind, r.row_no): r
        for r in parsed_doc.rows
        if r.row_kind == "transaction" and r.code in ("P", "S")
    }
    mismatches = []
    tolerances = {"shares": 0.005, "price": 0.005, "shares_owned_after": 0.5}
    for key in sorted(stored.keys() | fresh.keys()):
        if key not in stored or key not in fresh:
            mismatches.append(
                f"{key}: {'missing stored' if key not in stored else 'extra stored'} P/S row"
            )
            continue
        for field in ("code", "transaction_date", *tolerances):
            actual, expected = getattr(stored[key], field), getattr(fresh[key], field)
            equal = actual == expected
            if actual is not None and expected is not None and field in tolerances:
                equal = isclose(actual, expected, rel_tol=0, abs_tol=tolerances[field] + 1e-10)
            if not equal:
                mismatches.append(f"{key} {field}: stored={actual}, SEC={expected}")
    return mismatches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    if args.n < 1:
        parser.error("--n must be positive")
    settings = get_settings()
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    archive = RawArchive(settings.raw_archive_dir)
    with worker_lock(engine):

        def blocked(until: datetime) -> None:
            with session_scope(factory) as session:
                set_state(session, "sec_blocked_until", {"until": until.isoformat()})

        sec = build_sec_client(settings, archive=archive, on_block=blocked)
        with session_scope(factory) as session:
            accessions = pick_sample(session, args.n, args.seed)
        matched = 0
        links = []
        for accession in accessions:
            with session_scope(factory) as session:
                filing = session.get(Filing, accession)
                assert filing is not None
                cik = filing.primary_cik
                rows = list(
                    session.scalars(
                        select(InsiderTransaction).where(
                            InsiderTransaction.accession_no == accession
                        )
                    )
                )
                # expire_on_commit=False preserves read rows for comparison outside transaction.
            try:
                raw = sec.get_filing_txt(cik, accession)
                doc = parse_ownership(_ownership_xml(SgmlFiling.from_txt(raw)))
                errors = compare(rows, doc)
            except Exception as exc:
                errors = [f"{type(exc).__name__}: {exc}"]
            if errors:
                for error in errors:
                    print(f"{accession}: {error}")
            else:
                matched += 1
            links.append(filing_index_url(cik, accession))
        print(f"{matched}/{args.n} match ({len(accessions)} available samples)")
        for url in links[:5]:
            print(url)
        return 0 if matched == args.n else 1


if __name__ == "__main__":
    raise SystemExit(main())
