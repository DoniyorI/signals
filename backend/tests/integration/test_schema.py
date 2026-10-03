from sqlalchemy import inspect, text

from tests.factories import make_filing, make_issuer, make_owner, make_transaction

EXPECTED = {
    "issuers",
    "tickers",
    "ticker_evidence",
    "securities",
    "filing_acceptance",
    "owners",
    "owner_roles",
    "filings",
    "filing_owners",
    "insider_transactions",
    "insider_holdings",
    "form144_notices",
    "ownership_stakes",
    "fund_managers",
    "fund_filings",
    "fund_positions",
    "fund_position_changes",
    "prices_daily",
    "decisions",
    "decision_owners",
    "decision_returns",
    "positions",
    "profile_stats",
    "profile_windows",
    "fund_nav_daily",
    "feed_items",
    "users",
    "watchlists",
    "watchlist_items",
    "job_requests",
    "ingest_runs",
    "app_state",
    "completeness_index_members",
}


def test_all_tables_exist(db_engine):
    assert set(inspect(db_engine).get_table_names()) >= EXPECTED


def test_fund_positions_partitioned(session):
    n = session.execute(
        text(
            "select count(*) from pg_inherits i join pg_class p on p.oid = i.inhparent "
            "where p.relname = 'fund_positions'"
        )
    ).scalar_one()
    assert n >= 19  # 2013..2030 plus default


def test_pg_trgm_and_default_user(session):
    trgm = session.execute(text("select 1 from pg_extension where extname='pg_trgm'"))
    assert trgm.scalar_one() == 1
    assert session.execute(text("select name from users where id=1")).scalar_one() == "me"


def test_factories_roundtrip(session):
    make_issuer(session)
    make_owner(session)
    f = make_filing(session)
    t = make_transaction(session, accession_no=f.accession_no)
    assert (t.value_usd, t.acquired_disposed, t.owner_group) == (10000.0, "A", "2000001")
