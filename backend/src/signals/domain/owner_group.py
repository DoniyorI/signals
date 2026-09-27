"""Owner groups: the reporting owners of one filing, keyed so a joint filing counts once."""

from collections.abc import Iterable


def owner_group_key(ciks: Iterable[int]) -> str:
    """Unique CIKs sorted numerically, joined with '|' (e.g. '315090|1067983')."""
    unique = sorted({int(c) for c in ciks})
    if not unique:
        raise ValueError("an owner group needs at least one CIK")
    return "|".join(str(c) for c in unique)


def owner_group_ciks(key: str) -> list[int]:
    return [int(part) for part in key.split("|")]
