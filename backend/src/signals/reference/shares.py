"""Shares outstanding from the XBRL frames API, once per quarter (spec 7.7)."""

import json
from datetime import date

from sqlalchemy.orm import Session

from signals.db.models import Issuer

FRAMES_BASE = "https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/shares"


def frames_url(year: int, quarter: int) -> str:
    return f"{FRAMES_BASE}/CY{year}Q{quarter}I.json"


def load_shares_frames(session: Session, data: bytes) -> int:
    """Apply one quarter's XBRL frame (`{"data": [{"cik", "val", "end", ...}, ...]}`).

    Only touches issuers already known (from submissions.zip or company_tickers_exchange),
    and only when the frame's `end` is newer than what's stored, so an older quarter loaded
    out of order never downgrades a more recent figure. Returns the number of rows updated.
    """
    doc = json.loads(data)
    updated = 0
    for item in doc.get("data") or []:
        issuer = session.get(Issuer, int(item["cik"]))
        if issuer is None:
            continue
        end = date.fromisoformat(item["end"])
        if issuer.shares_outstanding_as_of is not None and issuer.shares_outstanding_as_of >= end:
            continue
        issuer.shares_outstanding = item.get("val")
        issuer.shares_outstanding_as_of = end
        updated += 1
    return updated
