from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def load_script():
    spec = spec_from_file_location(
        "coverage_summary", Path(__file__).parents[2] / "scripts/coverage_summary.py"
    )
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report():
    return {
        "as_of": "2026-09-30",
        "checked_at": None,
        "quarters": [
            {
                "year": 2025,
                "quarter": 1,
                "family": "ownership",
                "indexed": None,
                "stored": 99,
                "pct": None,
                "status": "unknown",
            },
            {
                "year": 2025,
                "quarter": 1,
                "family": "13f",
                "indexed": 100,
                "stored": 99,
                "pct": 0.99,
                "status": "gap",
            },
        ],
        "insider_transactions": [{"year": 2025, "count": 1234}],
        "prices": {
            "total": 10,
            "covered": 0,
            "pct": 0,
            "through": "2026-09-29",
            "loading": True,
            "missing_symbols": ["ACME"],
        },
        "returns": {
            "filed": {"eligible": 10, "covered": 3, "pct": 0.3},
            "executed": {"eligible": 11, "covered": 4, "pct": 4 / 11},
        },
        "funds": {"tracked": 2, "total": 8, "covered": 3, "pct": 0.375, "quarters": []},
        "unavailable": [
            {"accession_no": "0001000001-25-000001", "attempts": 3, "error": "SEC returned 404"}
        ],
    }


def test_unknown_baseline_is_not_reported_as_complete():
    text = load_script().render_report(report())
    ownership = next(line for line in text.splitlines() if "ownership" in line)
    assert "unknown" in ownership and "n/a" in ownership
    assert "complete" not in ownership
    assert "99.0%" in text and "gap" in text
    assert "Not checked yet" in text


def test_summary_distinguishes_bases_and_unavailable_filings():
    text = load_script().render_report(report())
    assert "filed" in text and "3/10" in text and "30.0%" in text
    assert "executed" in text and "4/11" in text
    assert "0/10" in text and "0.0%" in text and "loading" in text
    assert "3/8" in text and "37.5%" in text
    assert "2025" in text and "1,234" in text
    assert "0001000001-25-000001" in text and "3 attempts" in text


def test_empty_denominators_remain_unknown():
    data = report()
    data["prices"].update(total=0, pct=None, loading=False)
    data["returns"]["filed"].update(eligible=0, covered=0, pct=None)
    text = load_script().render_report(data)
    assert "0/0 (n/a)" in text
    assert "100.0%" not in text
