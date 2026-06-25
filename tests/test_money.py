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


def test_rupeeize_converts_dashboard_evrent_cod_payment_fields():
    """Keys added so dashboard / EV-rent / COD / payments stop leaking raw
    paise. Each money key -> rupees; counts, ids and strings untouched."""
    payload = {
        "rows": [
            {
                "person_id": 24,
                "name": "Rahul Das",
                "days_missed": 7,
                "missed_amount": 142857,
                "rent_charged": 125000,
                "rent_collected": 89300,
                "shortfall": 35700,
            }
        ],
        "evrent": {
            "expected_rent": 125000,
            "collected_rent": 89300,
            "arrears_rent": 0,
            "arrears_net": 95200,
            "arrears_recovered_later": 0,
            "future_arrears_recovered": 0,
            "future_xc_recovered": 0,
            "prior_recovered": 0,
            "rolled_forward": 0,
        },
        "cod": {"total_pending": 50000, "recent_payout": 300000},
        "payments": {"expected_amount": 250000},
        "stats": {"rent_partial": 35700},
    }
    out = rupeeize(payload)
    row = out["rows"][0]
    assert row["missed_amount"] == 1428.57
    assert row["rent_charged"] == 1250.0
    assert row["rent_collected"] == 893.0
    assert row["shortfall"] == 357.0
    assert row["days_missed"] == 7          # count untouched
    assert row["person_id"] == 24           # id untouched
    assert row["name"] == "Rahul Das"       # string untouched
    assert out["evrent"]["expected_rent"] == 1250.0
    assert out["evrent"]["arrears_net"] == 952.0
    assert out["cod"]["total_pending"] == 500.0
    assert out["cod"]["recent_payout"] == 3000.0
    assert out["payments"]["expected_amount"] == 2500.0
    assert out["stats"]["rent_partial"] == 357.0
