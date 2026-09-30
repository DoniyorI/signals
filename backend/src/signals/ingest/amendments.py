"""Form 3/4/5 amendments: match each amendment to its original and supersede rows (spec 7.6).

An amendment restates the original form, so the original's rows are marked
`superseded_by = <amendment>`. When several amendments restate the same original, the
latest one (by filed date, then acceptance, then accession) supersedes the original and
every earlier amendment, so exactly one version of the form stays live. Amendments with
no identifiable original keep their rows live and carry the `orphan_amendment` flag.
"""

from collections.abc import Sequence

from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session, aliased

from signals.db.models import Filing, FilingOwner, InsiderHolding, InsiderTransaction

ORPHAN_FLAG = "orphan_amendment"
AMENDMENT_FORMS = ("3/A", "4/A", "5/A")

_NO_SYNC = {"synchronize_session": False}


def _base_form(form_type: str) -> str:
    return form_type.removesuffix("/A")


def _best_original(session: Session, amendment: Filing) -> str | None:
    """Same base form, issuer and filed date (= dateOfOriginalSubmission), an owner in
    common; most overlapping transaction dates first, then the latest acceptance."""
    if amendment.original_filed_date is None or amendment.issuer_cik is None:
        return None
    amendment_owners = select(FilingOwner.owner_cik).where(
        FilingOwner.accession_no == amendment.accession_no
    )
    amendment_days = select(InsiderTransaction.transaction_date).where(
        InsiderTransaction.accession_no == amendment.accession_no,
        InsiderTransaction.transaction_date.is_not(None),
    )
    rows = aliased(InsiderTransaction)
    overlap = (
        select(func.count(func.distinct(rows.transaction_date)))
        .where(rows.accession_no == Filing.accession_no, rows.transaction_date.in_(amendment_days))
        .scalar_subquery()
        .label("overlap")
    )
    query = (
        select(Filing.accession_no, overlap)
        .where(
            Filing.form_type == _base_form(amendment.form_type),
            Filing.issuer_cik == amendment.issuer_cik,
            Filing.filed_date == amendment.original_filed_date,
            Filing.accession_no != amendment.accession_no,
            exists().where(
                FilingOwner.accession_no == Filing.accession_no,
                FilingOwner.owner_cik.in_(amendment_owners),
            ),
        )
        .order_by(
            overlap.desc(), Filing.accepted_at.desc().nulls_last(), Filing.accession_no.desc()
        )
        .limit(1)
    )
    best = session.execute(query).first()
    return best.accession_no if best else None


def _set_superseded(session: Session, accessions: Sequence[str], by: str | None) -> None:
    if not accessions:
        return
    for model in (InsiderTransaction, InsiderHolding):
        session.execute(
            update(model)
            .where(
                model.accession_no.in_(list(accessions)), model.superseded_by.is_distinct_from(by)
            )
            .values(superseded_by=by)
            .execution_options(**_NO_SYNC)
        )


def _set_orphan_flag(session: Session, accession: str, orphan: bool) -> None:
    t = InsiderTransaction
    if orphan:
        stmt = (
            update(t)
            .where(t.accession_no == accession, ~t.flags.contains([ORPHAN_FLAG]))
            .values(flags=func.array_append(t.flags, ORPHAN_FLAG))
        )
    else:
        stmt = (
            update(t)
            .where(t.accession_no == accession, t.flags.contains([ORPHAN_FLAG]))
            .values(flags=func.array_remove(t.flags, ORPHAN_FLAG))
        )
    session.execute(stmt.execution_options(**_NO_SYNC))


def _apply_chain(session: Session, original: str) -> None:
    """The latest amendment of `original` supersedes the original and earlier amendments."""
    amendments = session.scalars(
        select(Filing.accession_no)
        .where(Filing.amends_accession == original)
        .order_by(Filing.filed_date, Filing.accepted_at.asc().nulls_first(), Filing.accession_no)
    ).all()
    chain = [original, *amendments]
    latest = chain[-1]
    _set_superseded(session, chain[:-1], latest)
    _set_superseded(session, [latest], None)


def link_amendment(session: Session, amendment_accession: str) -> str | None:
    """Link an amendment to its original; returns the original's accession or None."""
    amendment = session.get(Filing, amendment_accession)
    if amendment is None:
        raise LookupError(f"no filing {amendment_accession}")
    session.flush()
    previous = amendment.amends_accession
    original = _best_original(session, amendment)
    amendment.amends_accession = original
    session.flush()
    _set_orphan_flag(session, amendment_accession, orphan=original is None)
    if original is None:
        _set_superseded(session, [amendment_accession], None)
    else:
        _apply_chain(session, original)
    if previous is not None and previous != original:
        _apply_chain(session, previous)
    return original


def refresh_original(session: Session, accession: str) -> None:
    """Re-apply supersession after an original is re-normalized (its rows were rewritten)."""
    linked = session.scalar(select(exists().where(Filing.amends_accession == accession)))
    if linked:
        _apply_chain(session, accession)


def relink_orphans(session: Session) -> int:
    """Link every unlinked Form 3/4/5 amendment that now has an original on file.

    Covers amendments whose rows carry `orphan_amendment` and holdings-only amendments
    (which have no transaction rows to carry the flag). Returns how many were linked.
    """
    session.flush()
    a, o = aliased(Filing), aliased(Filing)
    a_owner, o_owner = aliased(FilingOwner), aliased(FilingOwner)
    linkable = session.scalars(
        select(a.accession_no)
        .where(
            a.form_type.in_(AMENDMENT_FORMS),
            a.amends_accession.is_(None),
            a.original_filed_date.is_not(None),
            exists().where(
                o.form_type == func.replace(a.form_type, "/A", ""),
                o.issuer_cik == a.issuer_cik,
                o.filed_date == a.original_filed_date,
                o.accession_no != a.accession_no,
                o_owner.accession_no == o.accession_no,
                a_owner.accession_no == a.accession_no,
                a_owner.owner_cik == o_owner.owner_cik,
            ),
        )
        .order_by(a.filed_date, a.accession_no)
    ).all()
    return sum(1 for acc in linkable if link_amendment(session, acc) is not None)
