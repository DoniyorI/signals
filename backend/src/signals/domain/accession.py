"""SEC accession numbers and the EDGAR URLs built from them."""

import re

_DASHED = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_PLAIN = re.compile(r"^\d{18}$")


def normalize_accession(s: str) -> str:
    """Return the dashed form `0001234567-24-000123`, accepting it or 18 plain digits."""
    value = s.strip()
    if _DASHED.match(value):
        return value
    if _PLAIN.match(value):
        return f"{value[:10]}-{value[10:12]}-{value[12:]}"
    raise ValueError(f"not an accession number: {s!r}")


def accession_nodash(s: str) -> str:
    return normalize_accession(s).replace("-", "")


def filing_txt_url(cik: int, accession: str) -> str:
    """The complete submission text file (header plus every document)."""
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{normalize_accession(accession)}.txt"


def filing_index_url(cik: int, accession: str) -> str:
    """The human-readable filing index page on sec.gov."""
    acc = normalize_accession(accession)
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash(acc)}/{acc}-index.htm"
