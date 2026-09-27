import csv
from pathlib import Path

from tests.conftest import fixture_path

TRACKED_CSV = Path(__file__).resolve().parents[2] / "src/signals/reference/tracked_funds.csv"

REQUIRED = [
    "form4_buy_single", "form4_joint", "form4a_original", "form4a_amendment",
    "form4_10b5_1_flag", "form4_10b5_1_footnote", "form4_exercise_sale", "form4_footnote_price",
    "form4_value_owned", "form3", "form5", "form144", "f13f_small", "f13f_pre2023",
    "f13f_restatement", "sc13d", "sc13g", "atom_form4_p1", "atom_form4_p2", "atom_form4_424b2",
    "daily_index", "full_index", "bulk_345_slice", "bulk_13f_slice_2022", "bulk_13f_slice_2025",
    "listing_345_html", "listing_13f_html", "submissions_owner", "company_tickers_exchange",
    "frames_sample", "alpaca_raw_p1", "alpaca_raw_p2", "alpaca_all_p1", "alpaca_all_p2",
    "openfigi_sample",
]


def test_manifest_complete(manifest):
    missing = [k for k in REQUIRED if k not in manifest]
    assert not missing
    for k in REQUIRED:
        assert fixture_path(manifest[k]["file"]).exists(), k
        assert manifest[k]["expect"], k


def test_tracked_funds_csv():
    with open(TRACKED_CSV) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 40
    assert all(r["cik"].isdigit() and r["reason"] == "curated" for r in rows)
