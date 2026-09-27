"""Record real SEC / Alpaca / OpenFIGI responses as test fixtures (the only network use in tests).

Run from backend/:  uv run python ../scripts/record_fixtures.py <command> ...

Every fixture gets a MANIFEST.json entry. `expect` anchors are read straight from the
source document (plain XPath over the XML, or row counts over the SEC TSVs) and never
through the production parsers, so parser tests are checked against an independent reading.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import httpx
import typer
from lxml import etree

from signals.config import get_settings
from signals.domain.accession import filing_index_url, filing_txt_url, normalize_accession
from signals.domain.calendars import ET
from signals.sec.client import SecClient

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "backend" / "tests" / "fixtures" / "sec"
MANIFEST = FIX / "MANIFEST.json"
TMP = REPO / "data" / "tmp"

app = typer.Typer(add_completion=False, no_args_is_help=True)
_client: SecClient | None = None


def client() -> SecClient:
    global _client
    if _client is None:
        _client = SecClient(get_settings())
    return _client


# ---------------------------------------------------------------- manifest helpers
def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}


def merge_manifest(key: str, entry: dict[str, Any]) -> None:
    data = load_manifest()
    data[key] = {**data.get(key, {}), **entry}
    FIX.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(dict(sorted(data.items())), indent=2, default=str) + "\n")


# ---------------------------------------------------------------- SGML header (independent)
def sgml_header(txt: bytes) -> dict[str, Any]:
    head = txt.split(b"</SEC-HEADER>", 1)[0].decode("utf-8", "replace")
    out: dict[str, Any] = {}
    m = re.search(r"<ACCEPTANCE-DATETIME>(\d{14})", head)
    if m:
        stamp = datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
        out["accepted_at"] = stamp.replace(tzinfo=ET).isoformat()
    for label, key in (
        ("ACCESSION NUMBER", "accession"),
        ("CONFORMED SUBMISSION TYPE", "form_type"),
        ("FILED AS OF DATE", "filed_date"),
    ):
        m = re.search(rf"^{label}:\s*(.+)$", head, re.MULTILINE)
        if m:
            out[key] = m.group(1).strip()
    if "filed_date" in out:
        d = out["filed_date"]
        out["filed_date"] = f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return out


def xml_docs(txt: bytes) -> list[tuple[str, bytes]]:
    """(document type, xml bytes) for every <XML> block, read independently of signals.sec."""
    docs = []
    for part in txt.split(b"<DOCUMENT>")[1:]:
        m = re.search(rb"<TYPE>([^\r\n]+)", part)
        x = re.search(rb"<XML>\s*(.*?)\s*</XML>", part, re.DOTALL)
        if m and x:
            docs.append((m.group(1).decode().strip(), x.group(1)))
    return docs


def _x(el: etree._Element, path: str) -> list[Any]:
    return cast(list[Any], el.xpath(path))


def _t(el: etree._Element, path: str) -> str | None:
    found = _x(el, path)
    if not found:
        return None
    node = found[0]
    text = node if isinstance(node, str) else node.text
    return text.strip() if text and text.strip() else None


def _num(s: str | None) -> float | None:
    return float(s.replace(",", "")) if s else None


def ownership_anchors(xml: bytes) -> dict[str, Any]:
    root = etree.fromstring(xml)
    L = "*[local-name()='{}']".format
    owners = [int(c) for c in _x(root, f"//{L('rptOwnerCik')}/text()")]
    nd_tx = _x(root, f"//{L('nonDerivativeTransaction')}")
    d_tx = _x(root, f"//{L('derivativeTransaction')}")
    nd_h = _x(root, f"//{L('nonDerivativeHolding')}")
    codes = [_t(t, f".//{L('transactionCode')}") for t in nd_tx]
    exp: dict[str, Any] = {
        "issuer_cik": int(_t(root, f"//{L('issuerCik')}") or 0),
        "owner_ciks": owners,
        "document_type": _t(root, f"//{L('documentType')}"),
        "n_nonderiv_trans": len(nd_tx),
        "n_deriv_trans": len(d_tx),
        "n_nonderiv_holdings": len(nd_h),
        "codes": codes,
        "deriv_codes": [_t(t, f".//{L('transactionCode')}") for t in d_tx],
    }
    aff = _t(root, f"//{L('aff10b5One')}")
    exp["aff10b5one"] = None if aff is None else aff.lower() in ("1", "true")
    orig = _t(root, f"//{L('dateOfOriginalSubmission')}")
    if orig:
        exp["date_of_original_submission"] = orig[:10]
    if nd_tx:
        t = nd_tx[0]
        exp["first_nonderiv"] = {
            "transaction_date": (_t(t, f".//{L('transactionDate')}/{L('value')}") or "")[:10],
            "shares": _num(_t(t, f".//{L('transactionShares')}/{L('value')}")),
            "price": _num(_t(t, f".//{L('transactionPricePerShare')}/{L('value')}")),
            "shares_owned_after": _num(
                _t(t, f".//{L('sharesOwnedFollowingTransaction')}/{L('value')}")
            ),
        }
    notes = {n.get("id"): (n.text or "") for n in _x(root, f"//{L('footnote')}")}
    exp["footnote_ids_with_10b5_1"] = sorted(
        k for k, v in notes.items() if re.search(r"10b5-?1", v, re.IGNORECASE)
    )
    return exp


def f13f_anchors(primary: bytes, table: bytes | None) -> dict[str, Any]:
    root = etree.fromstring(primary)
    L = "*[local-name()='{}']".format
    exp: dict[str, Any] = {
        "period_of_report": _t(root, f"//{L('periodOfReport')}"),
        "report_calendar_or_quarter": _t(root, f"//{L('reportCalendarOrQuarter')}"),
        "amendment_type": _t(root, f"//{L('amendmentType')}"),
        "table_entry_total": int(_t(root, f"//{L('tableEntryTotal')}") or 0),
        "table_value_total": _num(_t(root, f"//{L('tableValueTotal')}")),
    }
    if table is not None:
        troot = etree.fromstring(table)
        rows = _x(troot, f"//{L('infoTable')}")
        exp["n_rows"] = len(rows)
        if rows:
            exp["first_row"] = {
                "cusip": _t(rows[0], f"./{L('cusip')}"),
                "value_reported": _num(_t(rows[0], f"./{L('value')}")),
            }
        exp["sum_value_reported"] = sum(_num(_t(r, f"./{L('value')}")) or 0 for r in rows)
    return exp


# ---------------------------------------------------------------- commands
@app.command()
def filing(key: str, cik: int, accession: str, why: str = "", expect: str = "{}") -> None:
    """Fetch one filing's complete .txt and add it to the manifest with anchors."""
    acc = normalize_accession(accession)
    body = client().get(filing_txt_url(cik, acc))
    path = FIX / "filings" / f"{key}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    head = sgml_header(body)
    anchors: dict[str, Any] = {}
    docs = xml_docs(body)
    if head.get("form_type", "").split("/")[0] in {"3", "4", "5"} and docs:
        anchors = ownership_anchors(docs[0][1])
    elif head.get("form_type", "").startswith("13F") and docs:
        by_type = dict(docs)
        primary = next((x for t, x in docs if t.startswith("13F")), docs[0][1])
        anchors = f13f_anchors(primary, by_type.get("INFORMATION TABLE"))
    anchors.update(json.loads(expect))
    merge_manifest(
        key,
        {
            "file": f"filings/{key}.txt",
            "source_url": filing_index_url(cik, acc),
            "why": why,
            "accession": acc,
            "cik": cik,
            "form_type": head.get("form_type"),
            "filed_date": head.get("filed_date"),
            "accepted_at": head.get("accepted_at"),
            "expect": anchors,
        },
    )
    typer.echo(f"{key}: {head.get('form_type')} {acc} ({len(body):,} bytes)")


@app.command()
def url(key: str, source: str, path: str, why: str = "", expect: str = "{}") -> None:
    body = client().get(source)
    out = FIX / path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    merge_manifest(
        key, {"file": path, "source_url": source, "why": why, "expect": json.loads(expect)}
    )
    typer.echo(f"{key}: {len(body):,} bytes -> {path}")


def _slice_zip(src: Path, out: Path, accessions: set[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    buf = io.BytesIO()
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in zin.namelist():
            if not name.lower().endswith(".tsv"):
                continue
            text = zin.read(name).decode("utf-8", "replace")
            lines = text.splitlines()
            header = lines[0]
            cols = header.split("\t")
            idx = cols.index("ACCESSION_NUMBER")
            kept = [ln for ln in lines[1:] if ln.split("\t")[idx] in accessions]
            counts[name] = len(kept)
            zout.writestr(name, "\n".join([header, *kept]) + "\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(buf.getvalue())
    return counts


@app.command()
def slice_zip(key: str, src_zip: Path, accessions: list[str], expect: str = "{}") -> None:
    """Keep only the given accessions in every TSV of an SEC data set ZIP (headers kept)."""
    out = FIX / "bulk" / f"{key}.zip"
    counts = _slice_zip(src_zip, out, set(accessions))
    merge_manifest(
        key,
        {
            "file": f"bulk/{key}.zip",
            "source_url": src_zip.name,
            "why": "sliced from an SEC data set",
            "expect": {
                "accessions": sorted(accessions),
                "row_counts": counts,
                **json.loads(expect),
            },
        },
    )
    typer.echo(f"{key}: {counts}")


@app.command()
def dataset(name_url: str) -> Path:
    """Download an SEC data set ZIP into data/tmp (not committed)."""
    TMP.mkdir(parents=True, exist_ok=True)
    dest = TMP / name_url.rsplit("/", 1)[-1]
    if not dest.exists():
        client().download(name_url, dest)
    typer.echo(str(dest))
    return dest


@app.command()
def alpaca() -> None:
    s = get_settings()
    assert s.alpaca_api_key and s.alpaca_secret_key
    headers = {
        "APCA-API-KEY-ID": s.alpaca_api_key,
        "APCA-API-SECRET-KEY": s.alpaca_secret_key.get_secret_value(),
    }
    for adj in ("raw", "all"):
        token = None
        for page in (1, 2):
            params = {
                "symbols": "SPY,AAPL",
                "timeframe": "1Day",
                "start": "2016-01-04T00:00:00Z",
                "end": "2016-02-29T23:59:59Z",
                "limit": 40,
                "adjustment": adj,
                "feed": s.alpaca_feed,
                "sort": "asc",
            }
            if token:
                params["page_token"] = token
            bars_url = f"{s.alpaca_data_url}/v2/stocks/bars"
            resp = httpx.get(bars_url, params=params, headers=headers)
            resp.raise_for_status()
            body = resp.json()
            key = f"alpaca_{adj}_p{page}"
            path = f"alpaca/{key}.json"
            (FIX / "alpaca").mkdir(parents=True, exist_ok=True)
            (FIX / path).write_text(json.dumps(body, indent=1))
            n = {sym: len(bars) for sym, bars in body.get("bars", {}).items()}
            merge_manifest(
                key,
                {
                    "file": path,
                    "source_url": "https://data.alpaca.markets/v2/stocks/bars",
                    "why": f"SPY+AAPL daily bars Jan-Feb 2016, adjustment={adj}, page {page}",
                    "expect": {
                        "symbols": sorted(n),
                        "n_bars": n,
                        "has_next_page_token": bool(body.get("next_page_token")),
                        "params": {k: v for k, v in params.items() if k != "page_token"},
                    },
                },
            )
            token = body.get("next_page_token")
            typer.echo(f"{key}: {n} next={bool(token)}")


@app.command()
def openfigi() -> None:
    jobs = [
        {"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"}
        for c in ("037833100", "084670702", "000000000")
    ]
    resp = httpx.post("https://api.openfigi.com/v3/mapping", json=jobs, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    (FIX / "openfigi").mkdir(parents=True, exist_ok=True)
    (FIX / "openfigi/openfigi_sample.json").write_text(json.dumps(body, indent=1))
    tickers = {
        jobs[i]["idValue"]: (item["data"][0]["ticker"] if item.get("data") else None)
        for i, item in enumerate(body)
    }
    merge_manifest(
        "openfigi_sample",
        {
            "file": "openfigi/openfigi_sample.json",
            "source_url": "https://api.openfigi.com/v3/mapping",
            "why": "AAPL, BRK.B and a bogus CUSIP",
            "expect": {
                "jobs": jobs,
                "tickers": tickers,
                "n_warnings": sum(1 for item in body if "warning" in item),
            },
        },
    )
    typer.echo(json.dumps(tickers))


@app.command()
def manifest_set(key: str, data: str) -> None:
    merge_manifest(key, json.loads(data))


# ---------------------------------------------------------------- discovery helpers (TSV)
def read_tsv(zip_path: Path, table: str) -> list[dict[str, str]]:
    with zipfile.ZipFile(zip_path) as z:
        name = next(n for n in z.namelist() if n.upper().startswith(table.upper()))
        text = z.read(name).decode("utf-8", "replace")
    return list(csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE))


if __name__ == "__main__":
    app()
