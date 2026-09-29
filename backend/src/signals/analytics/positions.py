"""Reconstructed insider positions (spec 8, 9.7): the latest reported non-derivative holdings.

Every non-superseded, non-derivative transaction row with shares owned after it and every
holding row with shares owned counts, for each owner in the row's owner group (a joint row
belongs to every owner). Per owner and (issuer, security title, direct/indirect):

- the latest filing reporting it wins, by acceptance (unknown acceptance counts as 16:00 ET on
  the filing date) and then accession;
- within that filing, the last row (by row number, holdings after transactions) of each
  nature of ownership counts, and the natures are summed, so indirect holdings reported
  together ("By Trust", "By Spouse") add up;
- titles and natures match ignoring case and repeated spaces.

`positions.as_of_date` is that filing's filed date and `last_accession` its accession. SQL does
the work because a full run reads every insider row since 2016.
"""

from collections.abc import Collection
from typing import Any

from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from signals.db.models import Position

_REPORTED = """
    SELECT t.owner_group, t.issuer_cik, t.security_title AS title, t.direct_indirect AS di,
           t.nature_of_ownership AS nature, t.shares_owned_after AS shares, t.accession_no,
           t.row_no, 0 AS part
    FROM insider_transactions t
    WHERE t.table_kind = 'nonderiv' AND t.superseded_by IS NULL
      AND t.shares_owned_after IS NOT NULL {rows_t}
    UNION ALL
    SELECT h.owner_group, h.issuer_cik, h.security_title, h.direct_indirect,
           h.nature_of_ownership, h.shares_owned, h.accession_no, h.row_no, 1
    FROM insider_holdings h
    WHERE h.table_kind = 'nonderiv' AND h.superseded_by IS NULL
      AND h.shares_owned IS NOT NULL {rows_h}
"""

_POSITIONS_SQL = r"""
WITH reported AS ({reported}),
keyed AS (
    SELECT o.owner_cik, r.issuer_cik,
           coalesce(regexp_replace(btrim(r.title), '\s+', ' ', 'g'), '') AS title,
           upper(coalesce(btrim(r.di), '')) AS di,
           lower(coalesce(regexp_replace(btrim(r.nature), '\s+', ' ', 'g'), '')) AS nature,
           r.shares, r.accession_no, r.row_no, r.part, f.filed_date,
           coalesce(f.accepted_at,
                    (f.filed_date + time '16:00') AT TIME ZONE 'America/New_York') AS public_at
    FROM reported r
    JOIN filings f ON f.accession_no = r.accession_no
    CROSS JOIN LATERAL unnest(string_to_array(r.owner_group, '|')::bigint[]) AS o(owner_cik)
    {owners}
),
latest AS (
    SELECT DISTINCT ON (owner_cik, issuer_cik, lower(title), di)
           owner_cik, issuer_cik, lower(title) AS title_key, di, accession_no
    FROM keyed
    ORDER BY owner_cik, issuer_cik, lower(title), di, public_at DESC, accession_no DESC
),
last_rows AS (
    SELECT DISTINCT ON (k.owner_cik, k.issuer_cik, lower(k.title), k.di, k.nature)
           k.owner_cik, k.issuer_cik, k.title, k.di, k.shares, k.accession_no, k.filed_date,
           k.part, k.row_no
    FROM keyed k
    JOIN latest l
      ON l.owner_cik = k.owner_cik AND l.issuer_cik = k.issuer_cik
     AND l.title_key = lower(k.title) AND l.di = k.di AND l.accession_no = k.accession_no
    ORDER BY k.owner_cik, k.issuer_cik, lower(k.title), k.di, k.nature, k.part DESC,
             k.row_no DESC
)
INSERT INTO positions
    (owner_cik, issuer_cik, security_title, direct_indirect, shares, as_of_date, last_accession)
SELECT owner_cik, issuer_cik, (array_agg(title ORDER BY part DESC, row_no DESC))[1], di,
       sum(shares), max(filed_date), max(accession_no)
FROM last_rows
GROUP BY owner_cik, issuer_cik, lower(title), di
"""

_ROW_SCOPE = "AND string_to_array({alias}.owner_group, '|')::bigint[] && CAST(:owners AS bigint[])"


def build_positions(session: Session, *, owner_ciks: Collection[int] | None = None) -> int:
    """Replace `positions` for the owners (or all). Returns the number of rows written."""
    scope = delete(Position)
    params: dict[str, Any] = {}
    if owner_ciks is None:
        rows_t = rows_h = owners = ""
    else:
        params["owners"] = sorted({int(c) for c in owner_ciks})
        scope = scope.where(Position.owner_cik.in_(params["owners"]))
        rows_t, rows_h = _ROW_SCOPE.format(alias="t"), _ROW_SCOPE.format(alias="h")
        owners = "WHERE o.owner_cik = ANY(CAST(:owners AS bigint[]))"
    session.execute(scope)
    sql = _POSITIONS_SQL.format(
        reported=_REPORTED.format(rows_t=rows_t, rows_h=rows_h), owners=owners
    )
    result = session.execute(text(sql), params)
    return int(getattr(result, "rowcount", 0) or 0)
