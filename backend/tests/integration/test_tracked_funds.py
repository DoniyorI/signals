from sqlalchemy import select

from signals.db.models import FundManager
from signals.reference.tracked_funds import CuratedFund, load_curated, refresh_tracked_funds


def _seed_manager(session, *, cik: int, value_usd: float, positions: int) -> None:
    session.add(
        FundManager(
            cik=cik,
            name=f"Manager {cik}",
            latest_value_usd=value_usd,
            latest_positions=positions,
        )
    )
    session.flush()


def test_curated_plus_top_active(session):
    ciks = {5e9: 5000001, 4e9: 5000002, 3e9: 5000003, 2e9: 5000004, 1e9: 5000005}
    positions = {5000001: 500, 5000002: 20, 5000003: 30, 5000004: 40, 5000005: 10}
    for value, cik in ciks.items():
        _seed_manager(session, cik=cik, value_usd=value, positions=positions[cik])

    curated = [CuratedFund(cik=5000005, name="Manager 5000005", reason="curated")]
    tracked_count = refresh_tracked_funds(session, curated=curated, top_n=2, max_positions=100)

    assert tracked_count == 3
    tracked = dict(
        session.execute(
            select(FundManager.cik, FundManager.tracked_reason).where(FundManager.is_tracked)
        ).all()
    )
    assert tracked == {5000005: "curated", 5000002: "top_active", 5000003: "top_active"}
    # The 500-position manager is the largest by value but exceeds max_positions, so it's out.
    untracked = session.get(FundManager, 5000001)
    assert untracked is not None and untracked.is_tracked is False


def test_refresh_is_idempotent_and_clears_stale_tracking(session):
    _seed_manager(session, cik=5000001, value_usd=5e9, positions=10)
    _seed_manager(session, cik=5000002, value_usd=1e9, positions=10)
    refresh_tracked_funds(
        session,
        curated=[CuratedFund(cik=5000002, name="Manager 5000002", reason="curated")],
        top_n=1,
        max_positions=100,
    )
    # Drop 5000002 from curated: it should lose tracking on the next refresh.
    count = refresh_tracked_funds(session, curated=[], top_n=1, max_positions=100)
    assert count == 1
    tracked = {
        cik
        for (cik,) in session.execute(select(FundManager.cik).where(FundManager.is_tracked)).all()
    }
    assert tracked == {5000001}


def test_load_curated_csv():
    funds = load_curated()
    assert len(funds) >= 40
    assert all(isinstance(f.cik, int) for f in funds)
    assert all(f.reason for f in funds)
