"""The live EDGAR "getcurrent" Atom feed: parsing, pagination and per-accession ingestion.

`type=4` (etc.) is a prefix match on SEC's side, so a page can carry unrelated forms
(424B2, 485APOS, ...). We filter to the exact category term ourselves. Each real filing
is listed twice (once per role, e.g. Reporting owner and Issuer), so entries are deduped
by accession before anything is fetched.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote_plus

from sqlalchemy.orm import Session

from signals.config import Settings
from signals.db.models import Filing
from signals.db.session import session_scope
from signals.domain.accession import normalize_accession
from signals.domain.appstate import set_state
from signals.domain.types import FEED_POLL_FORMS, FUND_FORMS
from signals.ingest.amendments import relink_orphans
from signals.ingest.parsers.xmlutil import parse_xml
from signals.ingest.pipeline import ingest_accession
from signals.jobs import request_job
from signals.logging import get_logger
from signals.sec.archive import RawArchive
from signals.sec.client import Priority, SecClient

log = get_logger(__name__)

_TITLE = re.compile(r"^(?P<form>.+?) - (?P<company>.+) \((?P<cik>\d{10})\) \((?P<role>[^)]+)\)$")
_ID_ACCESSION = re.compile(r"accession-number=([\d-]+)")
_HREF_ACCESSION = re.compile(r"/([\d-]{18,20})-index\.htm")
_HREF_CIK = re.compile(r"/data/(\d+)/")


@dataclass(frozen=True)
class FeedEntry:
    accession_no: str
    form_type: str
    cik: int
    company: str
    role: str | None
    updated: datetime


@dataclass(frozen=True)
class PollResult:
    pages: int
    entries: int
    new: int
    errors: int
    issuer_ciks: frozenset[int]
    owner_ciks: frozenset[int]
    filer_ciks: frozenset[int]


def feed_url(form_type: str, start: int) -> str:
    return (
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent"
        f"&type={quote_plus(form_type)}&company=&dateb=&owner=include"
        f"&start={start}&count=100&output=atom"
    )


def _accession_from(id_text: str | None, href: str | None) -> str | None:
    """Prefer <id>'s accession-number; fall back to the index page link."""
    for text, pattern in ((id_text, _ID_ACCESSION), (href, _HREF_ACCESSION)):
        if text:
            match = pattern.search(text)
            if match:
                return normalize_accession(match.group(1))
    return None


def parse_atom(xml: bytes) -> list[FeedEntry]:
    root = parse_xml(xml)
    entries: list[FeedEntry] = []
    for el in root.findall("entry"):
        title = (el.findtext("title") or "").strip()
        link_el = el.find("link")
        href = link_el.get("href") if link_el is not None else None
        category_el = el.find("category")
        term = category_el.get("term") if category_el is not None else None
        updated_text = el.findtext("updated")
        accession = _accession_from(el.findtext("id"), href)
        if accession is None or term is None or updated_text is None:
            log.warning("feed_entry_unparseable", title=title)
            continue

        match = _TITLE.match(title)
        if match:
            cik = int(match.group("cik"))
            company = match.group("company")
            role: str | None = match.group("role")
        else:
            href_cik = _HREF_CIK.search(href or "")
            if href_cik is None:
                log.warning("feed_entry_no_cik", title=title)
                continue
            cik, company, role = int(href_cik.group(1)), title, None

        entries.append(
            FeedEntry(
                accession_no=accession,
                form_type=term,
                cik=cik,
                company=company,
                role=role,
                updated=datetime.fromisoformat(updated_text),
            )
        )
    return entries


def _bucket_new_filing(
    filing: Filing, issuer_ciks: set[int], owner_ciks: set[int], filer_ciks: set[int]
) -> None:
    if filing.issuer_cik is not None:
        issuer_ciks.add(filing.issuer_cik)
    if filing.form_type in FUND_FORMS:
        filer_ciks.add(filing.primary_cik)
    else:
        owner_ciks.add(filing.primary_cik)


def poll_feed(
    client: SecClient,
    session_factory: Callable[[], Session],
    *,
    form_types: Sequence[str] = FEED_POLL_FORMS,
    max_pages: int = 5,
    now: datetime,
    settings: Settings,
    archive: RawArchive,
) -> PollResult:
    seen: set[str] = set()
    pages = 0
    total_entries = 0
    new = 0
    errors = 0
    issuer_ciks: set[int] = set()
    owner_ciks: set[int] = set()
    filer_ciks: set[int] = set()

    for form in form_types:
        allowed = {form, f"{form}/A"}
        for page_no in range(max_pages):
            start = page_no * 100
            body = client.get(feed_url(form, start), priority=Priority.LIVE)
            archive.put("feed", f"{form}-{now:%Y%m%dT%H%M%S}-{start}", body, "xml")
            pages += 1
            page_entries = [e for e in parse_atom(body) if e.form_type in allowed]
            total_entries += len(page_entries)

            page_has_known = False
            for entry in page_entries:
                if entry.accession_no in seen:
                    continue
                seen.add(entry.accession_no)
                with session_scope(session_factory) as s:
                    try:
                        outcome = ingest_accession(
                            client,
                            s,
                            cik=entry.cik,
                            accession=entry.accession_no,
                            source="feed",
                            priority=Priority.LIVE,
                            first_seen_at=now,
                            settings=settings,
                            archive=archive,
                        )
                    except Exception as exc:  # network/SEC error for this one entry
                        errors += 1
                        log.warning(
                            "feed_fetch_error", accession=entry.accession_no, error=str(exc)
                        )
                        continue
                    if outcome.status == "duplicate":
                        page_has_known = True
                    elif outcome.status == "error":
                        errors += 1
                    elif outcome.status == "parsed":
                        new += 1
                        filing = s.get(Filing, outcome.accession_no)
                        if filing is not None:
                            _bucket_new_filing(filing, issuer_ciks, owner_ciks, filer_ciks)

            if page_has_known:
                break

    with session_scope(session_factory) as s:
        relink_orphans(s)
        set_state(s, "live_poll_last_success", {"at": now.isoformat(), "new": new})
        if issuer_ciks or owner_ciks:
            request_job(
                s,
                "analytics_incremental",
                {"issuer_ciks": sorted(issuer_ciks), "owner_ciks": sorted(owner_ciks)},
            )
        if filer_ciks:
            request_job(s, "fund_changes", {"filer_ciks": sorted(filer_ciks)})

    return PollResult(
        pages=pages,
        entries=total_entries,
        new=new,
        errors=errors,
        issuer_ciks=frozenset(issuer_ciks),
        owner_ciks=frozenset(owner_ciks),
        filer_ciks=frozenset(filer_ciks),
    )
