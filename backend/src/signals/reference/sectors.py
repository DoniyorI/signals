"""SIC code to sector (spec 7.7).

The versioned `sic_sectors.csv` holds `sic_from,sic_to,sector` rows, checked top to bottom
with the first match winning, so exceptions (6798 REITs -> Real Estate) sit above the broad
ranges they carve out of. An empty sector means "no sector" (blank checks, ADRs, public
administration). The mapping approximates GICS, so each sector has one SPDR sector ETF.
"""

import csv
from collections.abc import Collection
from dataclasses import dataclass
from functools import cache
from importlib import resources

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from signals.db.models import Issuer
from signals.domain.types import Sector

SIC_SECTORS_CSV = "sic_sectors.csv"


@dataclass(frozen=True)
class SicRule:
    sic_from: int
    sic_to: int
    sector: Sector | None


@cache
def load_sic_rules() -> tuple[SicRule, ...]:
    """Parse the CSV. A bad range or an unknown sector name raises instead of guessing."""
    text = resources.files("signals.reference").joinpath(SIC_SECTORS_CSV).read_text("utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    rules: list[SicRule] = []
    for row in csv.DictReader(lines):
        low, high = int(row["sic_from"]), int(row["sic_to"])
        if low > high:
            raise ValueError(f"{SIC_SECTORS_CSV}: empty range {low}-{high}")
        name = (row["sector"] or "").strip()
        rules.append(SicRule(low, high, Sector(name) if name else None))
    return tuple(rules)


@cache
def sector_for_sic(sic: int | None) -> Sector | None:
    if sic is None:
        return None
    for rule in load_sic_rules():
        if rule.sic_from <= sic <= rule.sic_to:
            return rule.sector
    return None


def assign_sectors(session: Session, issuer_ciks: Collection[int] | None = None) -> int:
    """Set `issuers.sector` from `sic` (a pure derivation: no SIC means no sector).

    Runs one UPDATE per distinct SIC and only touches rows whose sector changes.
    Returns the number of issuers changed.
    """
    ciks = None if issuer_ciks is None else list(issuer_ciks)
    distinct_sics = select(Issuer.sic).distinct()
    if ciks is not None:
        distinct_sics = distinct_sics.where(Issuer.cik.in_(ciks))
    changed = 0
    for sic in session.scalars(distinct_sics).all():
        sector = sector_for_sic(sic)
        value = sector.value if sector is not None else None
        stmt = update(Issuer).where(
            Issuer.sic.is_(None) if sic is None else Issuer.sic == sic,
            Issuer.sector.is_distinct_from(value),
        )
        if ciks is not None:
            stmt = stmt.where(Issuer.cik.in_(ciks))
        stmt = stmt.values(sector=value).returning(Issuer.cik)
        changed += len(session.execute(stmt).all())
    return changed
