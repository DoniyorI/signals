"""Pure portfolio helpers shared by analytics and the API."""

from collections.abc import Mapping, Sequence


def _normalized(weights: Sequence[float]) -> list[float]:
    total = sum(weights)
    return [w / total for w in weights] if total else []


def effective_n(weights: Sequence[float]) -> float | None:
    """Effective number of positions, 1 / sum(w^2), after normalizing the weights."""
    w = _normalized(weights)
    return 1.0 / sum(x * x for x in w) if w else None


def top5_weight(weights: Sequence[float]) -> float | None:
    """Share of the portfolio held in the five largest positions."""
    w = _normalized(weights)
    return sum(sorted(w, reverse=True)[:5]) if w else None


def allocation_slices(
    values: Mapping[str, float], labels: Mapping[str, str] | None = None
) -> list[dict]:
    total = sum(values.values())
    ordered = sorted(values.items(), key=lambda kv: kv[1], reverse=True)
    return [
        {
            "key": key,
            "label": (labels or {}).get(key, key),
            "value_usd": value,
            "weight": value / total if total else 0.0,
        }
        for key, value in ordered
    ]


def fund_high_conviction(
    weights: Sequence[float | None], changes: Sequence[str], values: Sequence[float]
) -> list[bool]:
    """Weight of 5% or more, or a NEW position ranked in the top 20 by value."""
    by_value = sorted(range(len(values)), key=lambda i: values[i], reverse=True)
    rank = {idx: pos + 1 for pos, idx in enumerate(by_value)}
    flags: list[bool] = []
    for i, weight in enumerate(weights):
        heavy = weight is not None and weight >= 0.05
        flags.append(heavy or (changes[i] == "NEW" and rank[i] <= 20))
    return flags
