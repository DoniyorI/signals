"""Historical owner writes and live ownership parsing must not invert their row locks."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event, get_ident

from sqlalchemy import delete, event

from signals.db.models import (
    FeedItem,
    Filing,
    FilingOwner,
    InsiderHolding,
    InsiderTransaction,
    Issuer,
    Owner,
    OwnerRole,
    Ticker,
    TickerEvidence,
)
from signals.db.session import make_session_factory, session_scope
from signals.domain.tickers import record_ticker_evidence
from signals.ingest.handlers.insider import _ownership_xml
from signals.ingest.normalize_insider import normalize_ownership, upsert_owner
from signals.ingest.parsers.ownership import parse_ownership
from signals.sec.sgml import SgmlFiling
from tests.factories import make_filing, make_issuer


def test_live_ownership_and_backfill_owner_ticker_writes_do_not_deadlock(db_engine, fixture_bytes):
    sgml = SgmlFiling.from_txt(fixture_bytes("form4_buy_single"))
    doc = parse_ownership(_ownership_xml(sgml))
    owner = doc.owners[0]
    factory = make_session_factory(db_engine)
    with session_scope(factory) as session:
        make_issuer(session, cik=doc.issuer_cik, ticker=None)
        make_filing(
            session,
            accession_no=sgml.accession_no,
            issuer_cik=doc.issuer_cik,
            primary_cik=owner.cik,
            owners=[owner.cik],
            filed_date=sgml.filed_date,
        )
        record_ticker_evidence(session, doc.issuer_cik, doc.issuer_symbol, date(2016, 1, 1), "test")
    owner_locked, live_ticker_locked = Event(), Event()
    live_thread = None

    def observe(connection, cursor, statement, parameters, context, executemany):
        if get_ident() == live_thread and statement.startswith("INSERT INTO ticker_evidence"):
            live_ticker_locked.set()

    def backfill():
        with session_scope(factory) as session:
            upsert_owner(session, owner.cik, "Historical owner", "person")
            owner_locked.set()
            # Old parser obtains ticker first, then waits on our owner. New parser waits
            # on owner immediately, so this bounded gate expires and we finish safely.
            live_ticker_locked.wait(timeout=1)
            record_ticker_evidence(
                session, doc.issuer_cik, doc.issuer_symbol, date(2016, 2, 1), "bulk_345"
            )

    def live():
        nonlocal live_thread
        live_thread = get_ident()
        assert owner_locked.wait(timeout=5)
        with session_scope(factory) as session:
            filing = session.get(Filing, sgml.accession_no)
            assert filing is not None
            normalize_ownership(session, filing, doc)

    event.listen(db_engine, "after_cursor_execute", observe)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            historical, current = pool.submit(backfill), pool.submit(live)
            historical.result(timeout=10)
            current.result(timeout=10)
    finally:
        event.remove(db_engine, "after_cursor_execute", observe)
        with session_scope(factory) as session:
            for model in (FeedItem, InsiderTransaction, InsiderHolding, FilingOwner):
                session.execute(delete(model).where(model.accession_no == sgml.accession_no))
            session.execute(delete(Filing).where(Filing.accession_no == sgml.accession_no))
            session.execute(delete(OwnerRole).where(OwnerRole.owner_cik == owner.cik))
            session.execute(delete(Owner).where(Owner.cik == owner.cik))
            for model in (Ticker, TickerEvidence):
                session.execute(delete(model).where(model.issuer_cik == doc.issuer_cik))
            session.execute(delete(Issuer).where(Issuer.cik == doc.issuer_cik))
