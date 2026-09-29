from signals.analytics.allocation import insider_high_conviction


def test_insider_high_conviction():
    assert insider_high_conviction(0.2, 10, False) and not insider_high_conviction(
        0.19, 999_999, False
    )
    assert insider_high_conviction(None, 1_000_000, False) and insider_high_conviction(
        None, 5, True
    )
    assert not insider_high_conviction(None, None, False)
