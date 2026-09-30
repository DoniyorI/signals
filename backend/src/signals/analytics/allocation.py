"""Insider conviction (spec 9.7): a buy decision is high conviction when it raises the
insider's stake by 20% or more, is worth $1M or more, or opens a new position.

The portfolio concentration helpers (effective_n, top5_weight, allocation_slices,
fund_high_conviction) are shared with the API and live in `signals.domain.portfolio`.
"""

BIG_STAKE_CHANGE = 0.20
BIG_VALUE_USD = 1_000_000.0


def insider_high_conviction(
    stake_change_pct: float | None, value_usd: float | None, is_new_position: bool
) -> bool:
    return (
        is_new_position
        or (stake_change_pct is not None and stake_change_pct >= BIG_STAKE_CHANGE)
        or (value_usd is not None and value_usd >= BIG_VALUE_USD)
    )
