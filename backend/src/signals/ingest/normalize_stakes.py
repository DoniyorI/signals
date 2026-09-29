"""Normalize a parsed Schedule 13D/13G into `ownership_stakes` and the feed.

One row per accession (`ownership_stakes.accession_no` is the primary key), so a re-parse of the
same filing simply re-upserts that row. `is_current` marks, within a reporting-person group and
issuer, the newest stake by `(event_date, accepted_at, accession_no)`; older filings for the same
group and issuer are demoted, never deleted (spec 7.6).
"""

from dataclasses import asdict

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from signals.db.models import Filing, OwnershipStake
from signals.domain.feed import FeedItemIn, upsert_feed_item
from signals.domain.types import Direction
from signals.ingest.normalize_funds import expire_instances
from signals.ingest.parsers.schedule13 import ReportingPerson, Schedule13Doc


def _group_key(persons: tuple[ReportingPerson, ...]) -> str:
    return "|".join(sorted(str(p.cik) if p.cik else p.name.upper() for p in persons))


def _top_person(persons: tuple[ReportingPerson, ...]) -> ReportingPerson | None:
    """The person with the maximum `percent_of_class`; persons with none are ignored."""
    best: ReportingPerson | None = None
    best_pct = -1.0
    for p in persons:
        if p.percent_of_class is not None and p.percent_of_class > best_pct:
            best, best_pct = p, p.percent_of_class
    return best


# Within one reporting-person group and issuer, only the newest stake (by event date, then
# acceptance time, then accession as a tiebreaker) is current. Recomputed in full on every write
# so the flag stays correct across backfills and reparses, however filings arrive.
# `ownership_stakes` has no `accepted_at` of its own (spec 8): it's joined from `filings`, the
# one place acceptance time lives.
_REFRESH_CURRENT = text(
    """
    WITH ranked AS (
        SELECT o.accession_no,
               row_number() OVER (
                   ORDER BY o.event_date DESC NULLS LAST, f.accepted_at DESC NULLS LAST,
                            o.accession_no DESC
               ) AS rn
        FROM ownership_stakes o
        JOIN filings f ON f.accession_no = o.accession_no
        WHERE o.group_key = :group_key AND o.issuer_cik IS NOT DISTINCT FROM :issuer_cik
    )
    UPDATE ownership_stakes o
    SET is_current = (r.rn = 1), updated_at = now()
    FROM ranked r
    WHERE o.accession_no = r.accession_no AND o.is_current IS DISTINCT FROM (r.rn = 1)
    """
)


def normalize_stake(session: Session, filing: Filing, doc: Schedule13Doc) -> None:
    """Write one parsed Schedule 13D/13G. Runs inside the caller's transaction; re-runs replace."""
    session.flush()
    is_activist = filing.form_type.upper().startswith("SCHEDULE 13D")
    group_key = _group_key(doc.persons)
    top = _top_person(doc.persons)
    pct = top.percent_of_class if top is not None else None

    values = {
        "accession_no": filing.accession_no,
        "form_type": filing.form_type,
        "issuer_cik": doc.issuer_cik,
        "cusip": doc.cusip,
        "event_date": doc.event_date,
        "amendment_no": doc.amendment_no,
        "is_activist": is_activist,
        "percent_of_class": pct,
        "shares": top.aggregate_owned if top is not None else None,
        "reporting_persons": [asdict(p) for p in doc.persons],
        "group_key": group_key,
        "purpose_excerpt": doc.purpose,
        "is_current": True,
    }
    stmt = insert(OwnershipStake).values(**values)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[OwnershipStake.accession_no],
            set_={
                **{k: stmt.excluded[k] for k in values if k != "accession_no"},
                "updated_at": func.now(),
            },
        )
    )
    session.flush()
    session.execute(_REFRESH_CURRENT, {"group_key": group_key, "issuer_cik": doc.issuer_cik})

    label = "13D" if is_activist else "13G"
    summary = f"{label}: {pct:.1%} of class" if pct is not None else f"{label} filed"
    upsert_feed_item(
        session,
        FeedItemIn(
            accession_no=filing.accession_no,
            form_type=filing.form_type,
            accepted_at=filing.accepted_at,
            filed_date=filing.filed_date,
            issuer_cik=doc.issuer_cik,
            issuer_name=doc.issuer_name,
            owner_group=group_key,
            owner_ciks=tuple(p.cik for p in doc.persons if p.cik is not None),
            owner_names=", ".join(p.name for p in doc.persons) or None,
            direction=Direction.OTHER.value,
            codes=(filing.form_type,),
            shares=top.aggregate_owned if top is not None else None,
            summary=summary,
        ),
    )
    session.flush()
    expire_instances(session, OwnershipStake)
