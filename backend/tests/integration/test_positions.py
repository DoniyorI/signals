"""Reconstructed insider positions: the latest reported non-derivative holdings."""

from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import delete, select

from signals.analytics.positions import build_positions
from signals.db.models import InsiderHolding, InsiderTransaction, Position
from signals.domain.calendars import ET
from tests.factories import make_filing, make_holding, make_transaction

JAN, MAR = date(2024, 1, 16), date(2024, 3, 12)


def _filing(
    session,
    accession_no: str,
    filed: date,
    *,
    owners: Sequence[int] = (2000001,),
    at: tuple[int, int] | None = (16, 30),
    form_type: str = "4",
) -> str:
    accepted = None if at is None else datetime(filed.year, filed.month, filed.day, *at, tzinfo=ET)
    make_filing(
        session,
        accession_no=accession_no,
        form_type=form_type,
        filed_date=filed,
        accepted_at=accepted,
        owners=owners,
    )
    return accession_no


def _row(row: InsiderTransaction | InsiderHolding, **fields: object) -> None:
    for name, value in fields.items():
        setattr(row, name, value)


def _positions(session) -> list[tuple]:
    session.expire_all()
    rows = session.scalars(
        select(Position).order_by(
            Position.owner_cik,
            Position.issuer_cik,
            Position.security_title,
            Position.direct_indirect,
        )
    )
    return [
        (
            p.owner_cik,
            p.issuer_cik,
            p.security_title,
            p.direct_indirect,
            p.shares,
            p.as_of_date,
            p.last_accession,
        )
        for p in rows
    ]


def test_latest_shares_win(session):
    jan = _filing(session, "0002000001-24-000001", JAN)
    make_transaction(session, accession_no=jan, shares_owned_after=1000.0)
    mar = _filing(session, "0002000001-24-000002", MAR)
    make_transaction(session, accession_no=mar, shares_owned_after=1500.0)

    assert build_positions(session) == 1
    assert _positions(session) == [(2000001, 1000001, "", "D", 1500.0, MAR, mar)]


def test_superseded_ignored(session):
    jan = _filing(session, "0002000001-24-000001", JAN)
    make_transaction(session, accession_no=jan, shares_owned_after=1000.0)
    mar = _filing(session, "0002000001-24-000002", MAR)
    make_transaction(
        session,
        accession_no=mar,
        shares_owned_after=1500.0,
        superseded_by="0002000001-24-000009",
    )
    build_positions(session)
    assert _positions(session) == [(2000001, 1000001, "", "D", 1000.0, JAN, jan)]


def test_form3_holdings_count(session):
    acc = _filing(session, "0002000001-24-000003", JAN, form_type="3")
    make_holding(session, accession_no=acc, shares_owned=5000.0)
    build_positions(session)
    assert _positions(session) == [(2000001, 1000001, "Common Stock", "D", 5000.0, JAN, acc)]


def test_derivatives_excluded(session):
    acc = _filing(session, "0002000001-24-000001", JAN)
    make_transaction(session, accession_no=acc, table_kind="deriv", shares_owned_after=300.0)
    _row(make_holding(session, accession_no=acc, shares_owned=700.0), table_kind="deriv")
    session.flush()
    assert build_positions(session) == 0
    assert _positions(session) == []


def test_joint_rows_attributed_to_each_owner(session):
    acc = _filing(session, "0002000003-24-000001", JAN, owners=(2000003, 2000004))
    make_transaction(
        session, accession_no=acc, owner_ciks=(2000003, 2000004), shares_owned_after=2000.0
    )
    build_positions(session)
    assert _positions(session) == [
        (2000003, 1000001, "", "D", 2000.0, JAN, acc),
        (2000004, 1000001, "", "D", 2000.0, JAN, acc),
    ]


def test_last_row_of_the_latest_filing_wins(session):
    acc = _filing(session, "0002000001-24-000001", JAN)
    make_transaction(session, accession_no=acc, row_no=1, shares_owned_after=1000.0)
    make_transaction(session, accession_no=acc, row_no=2, shares_owned_after=800.0)
    build_positions(session)
    assert _positions(session) == [(2000001, 1000001, "", "D", 800.0, JAN, acc)]


def test_unknown_acceptance_counts_as_the_filing_days_close(session):
    morning = _filing(session, "0002000001-24-000009", MAR, at=(10, 0))
    make_transaction(session, accession_no=morning, shares_owned_after=1000.0)
    unknown = _filing(session, "0002000001-24-000001", MAR, at=None)  # counts as 16:00 ET
    make_transaction(session, accession_no=unknown, shares_owned_after=1200.0)
    build_positions(session)
    assert _positions(session) == [(2000001, 1000001, "", "D", 1200.0, MAR, unknown)]


def test_rows_without_shares_do_not_count(session):
    jan = _filing(session, "0002000001-24-000001", JAN)
    make_transaction(session, accession_no=jan, shares_owned_after=1000.0)
    mar = _filing(session, "0002000001-24-000002", MAR)
    make_transaction(session, accession_no=mar, shares_owned_after=None)
    build_positions(session)
    assert _positions(session) == [(2000001, 1000001, "", "D", 1000.0, JAN, jan)]


def test_indirect_natures_in_the_latest_filing_are_summed(session):
    jan = _filing(session, "0002000001-24-000001", JAN)
    _row(
        make_holding(session, accession_no=jan, shares_owned=9999.0),
        direct_indirect="I",
        nature_of_ownership="By Trust",
    )
    mar = _filing(session, "0002000001-24-000002", MAR)
    _row(
        make_transaction(session, accession_no=mar, row_no=1, shares_owned_after=1000.0),
        security_title="Common Stock",
    )
    for row_no, nature, shares in ((1, "By Trust", 20000.0), (2, "By Spouse", 5000.0)):
        _row(
            make_holding(session, accession_no=mar, row_no=row_no, shares_owned=shares),
            direct_indirect="I",
            nature_of_ownership=nature,
        )
    session.flush()
    build_positions(session)
    assert _positions(session) == [
        (2000001, 1000001, "Common Stock", "D", 1000.0, MAR, mar),
        (2000001, 1000001, "Common Stock", "I", 25000.0, MAR, mar),
    ]


def test_title_case_and_spacing_variants_are_one_position(session):
    jan = _filing(session, "0002000001-24-000001", JAN)
    make_holding(session, accession_no=jan, shares_owned=5000.0)  # "Common Stock"
    mar = _filing(session, "0002000001-24-000002", MAR)
    _row(
        make_holding(session, accession_no=mar, shares_owned=6000.0),
        security_title=" common  stock ",
    )
    session.flush()
    build_positions(session)
    assert _positions(session) == [(2000001, 1000001, "common stock", "D", 6000.0, MAR, mar)]


def test_scoped_build_replaces_only_the_given_owners(session):
    for owner, shares in ((2000001, 1000.0), (2000002, 2000.0)):
        acc = _filing(session, f"{owner:010d}-24-000001", JAN, owners=(owner,))
        make_transaction(session, accession_no=acc, owner_ciks=(owner,), shares_owned_after=shares)
    joint = _filing(session, "0002000003-24-000001", JAN, owners=(2000003, 2000004))
    make_transaction(
        session, accession_no=joint, owner_ciks=(2000003, 2000004), shares_owned_after=3000.0
    )
    assert build_positions(session) == 4
    for owner, shares in ((2000001, 1200.0), (2000002, 2500.0)):
        acc = _filing(session, f"{owner:010d}-24-000002", MAR, owners=(owner,))
        make_transaction(session, accession_no=acc, owner_ciks=(owner,), shares_owned_after=shares)
    session.execute(delete(Position).where(Position.owner_cik == 2000004))

    assert build_positions(session, owner_ciks=[2000002, 2000004]) == 2

    assert [(p[0], p[4]) for p in _positions(session)] == [
        (2000001, 1000.0),  # not rebuilt
        (2000002, 2500.0),
        (2000003, 3000.0),
        (2000004, 3000.0),
    ]
