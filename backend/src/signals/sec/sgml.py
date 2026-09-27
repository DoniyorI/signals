"""Read EDGAR's complete submission text file (.txt): the SGML header plus every document.

Header facts come from the filer-independent SEC wrapper, so they are available for every
form type, including ACCEPTANCE-DATETIME (Eastern time), which drives filed-basis returns.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from signals.domain.calendars import ET

_ROLE = re.compile(r"^([A-Z][A-Z -]*[A-Z]):\s*$")
_KEY_VALUE = re.compile(r"^\s*([A-Z][A-Z -]*[A-Z]):\s*(.*?)\s*$")
_ACCEPTED = re.compile(rb"<ACCEPTANCE-DATETIME>(\d{14})")
_DOC_TAG = re.compile(rb"^<(TYPE|SEQUENCE|FILENAME|DESCRIPTION)>(.*)$", re.MULTILINE)
_XML_BODY = re.compile(rb"<XML>\s*(.*?)\s*</XML>", re.DOTALL)

ROLE_PREFERENCE = ("REPORTING-OWNER", "FILER", "FILED BY", "ISSUER", "SUBJECT COMPANY")


@dataclass(frozen=True)
class SgmlDocument:
    type: str
    sequence: int
    filename: str | None
    description: str | None
    body: bytes

    def xml(self) -> bytes | None:
        match = _XML_BODY.search(self.body)
        return match.group(1).strip() if match else None


@dataclass(frozen=True)
class SgmlFiling:
    accession_no: str
    form_type: str
    filed_date: date
    accepted_at: datetime | None
    period_of_report: date | None
    ciks_by_role: dict[str, list[int]] = field(default_factory=dict)
    names_by_cik: dict[int, str] = field(default_factory=dict)
    documents: list[SgmlDocument] = field(default_factory=list)

    @classmethod
    def from_txt(cls, data: bytes) -> "SgmlFiling":
        if b"<SEC-HEADER>" not in data or b"</SEC-HEADER>" not in data:
            raise ValueError("not an EDGAR submission text file (no SEC-HEADER)")
        head_bytes, body = data.split(b"</SEC-HEADER>", 1)
        header = head_bytes.decode("utf-8", "replace")

        top: dict[str, str] = {}
        ciks_by_role: dict[str, list[int]] = {}
        names_by_cik: dict[int, str] = {}
        role: str | None = None
        pending_name: str | None = None
        for line in header.splitlines():
            role_match = _ROLE.match(line)
            if role_match and not line.startswith((" ", "\t")):
                role, pending_name = role_match.group(1), None
                continue
            kv = _KEY_VALUE.match(line)
            if not kv:
                continue
            key, value = kv.group(1), kv.group(2)
            if not line.startswith((" ", "\t")):
                role = None
                top[key] = value
            elif role is not None and key == "COMPANY CONFORMED NAME":
                pending_name = value
            elif role is not None and key == "CENTRAL INDEX KEY" and value.isdigit():
                cik = int(value)
                ciks_by_role.setdefault(role, []).append(cik)
                if pending_name:
                    names_by_cik.setdefault(cik, pending_name)

        accepted = _ACCEPTED.search(head_bytes)
        accepted_at = (
            datetime.strptime(accepted.group(1).decode(), "%Y%m%d%H%M%S").replace(tzinfo=ET)
            if accepted
            else None
        )
        return cls(
            accession_no=top["ACCESSION NUMBER"],
            form_type=top["CONFORMED SUBMISSION TYPE"],
            filed_date=_compact_date(top["FILED AS OF DATE"]),
            accepted_at=accepted_at,
            period_of_report=(
                _compact_date(top["CONFORMED PERIOD OF REPORT"])
                if top.get("CONFORMED PERIOD OF REPORT")
                else None
            ),
            ciks_by_role=ciks_by_role,
            names_by_cik=names_by_cik,
            documents=_documents(body),
        )

    def xml_documents(self) -> list[SgmlDocument]:
        return [d for d in self.documents if d.xml() is not None]

    def primary_cik(self) -> int:
        for role in ROLE_PREFERENCE:
            if self.ciks_by_role.get(role):
                return self.ciks_by_role[role][0]
        raise ValueError(f"{self.accession_no}: no CIK in the header")


def _compact_date(value: str) -> date:
    return datetime.strptime(value.strip(), "%Y%m%d").date()


def _documents(body: bytes) -> list[SgmlDocument]:
    docs: list[SgmlDocument] = []
    for chunk in body.split(b"<DOCUMENT>")[1:]:
        chunk = chunk.split(b"</DOCUMENT>", 1)[0]
        tags = {
            m.group(1).decode(): m.group(2).decode("utf-8", "replace").strip()
            for m in _DOC_TAG.finditer(chunk.split(b"<TEXT>", 1)[0])
        }
        sequence = tags.get("SEQUENCE", "")
        docs.append(
            SgmlDocument(
                type=tags.get("TYPE", ""),
                sequence=int(sequence) if sequence.isdigit() else len(docs) + 1,
                filename=tags.get("FILENAME"),
                description=tags.get("DESCRIPTION"),
                body=chunk,
            )
        )
    return docs
