from payout.money import prorate, rupeeize, split_evenly, to_paise, to_rupees


def test_to_paise_half_up():
    assert to_paise(1250) == 125000
    assert to_paise(178.57) == 17857
    assert to_paise(0.005) == 1            # half-up
    assert to_paise("1295.00") == 129500
    assert to_paise(None) == 0


def test_to_rupees():
    assert to_rupees(125000) == 1250.0
    assert to_rupees(17857) == 178.57


def test_prorate_full_week_is_exact():
    assert prorate(125000, 7) == 125000
    assert prorate(129500, 7) == 129500
    assert prorate(125000, 14) == 250000   # catch-up: 2 weeks
    assert prorate(125000, 9) == 160714    # >1wk prorates up, not capped


def test_prorate_partial_rounds_once():
    # 1250/7*5 = 892.857.. -> 89286 paise (half-up)
    assert prorate(125000, 5) == 89286
    assert prorate(125000, 1) == 17857     # 1250/7 = 178.571 -> 178.57
    assert prorate(125000, 0) == 0


def test_split_evenly_sums_to_total():
    for total, n in [(125000, 7), (89286, 5), (129500, 7), (17857, 1), (100, 7)]:
        parts = split_evenly(total, n)
        assert len(parts) == n
        assert sum(parts) == total                       # exact reconciliation
        assert max(parts) - min(parts) <= 1              # spread by at most 1p


def test_rupeeize_converts_arrears_and_dues_fields_without_touching_counts():
    payload = {
        "charts": {
            "top_arrears": [
                {
                    "person_id": 1,
                    "ev_arrears": 126000,
                    "dues": 50000,
                    "arrears_total": 176000,
                }
            ],
        },
        "arrears_page": {
            "outstanding": 126000,
            "dues_outstanding": 50000,
        },
        "total": 3,
    }

    assert rupeeize(payload) == {
        "charts": {
            "top_arrears": [
                {
                    "person_id": 1,
                    "ev_arrears": 1260.0,
                    "dues": 500.0,
                    "arrears_total": 1760.0,
                }
            ],
        },
        "arrears_page": {
            "outstanding": 1260.0,
            "dues_outstanding": 500.0,
        },
        "total": 3,
    }
