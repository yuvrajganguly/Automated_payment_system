"""Money-scale guardrail: summed money must render in rupees, not paise (x100).

Money is stored as integer paise and converted to rupees only at the boundary
(rupeeize / to_rupees), which recognise int/float. On Postgres, SUM(bigint)
returns numeric -> psycopg would hand back a Decimal, which those converters
skipped, rendering 100x too large. The connection layer now loads numeric as
int/float so this can't happen. These tests lock that in on BOTH backends.
"""

from __future__ import annotations

from payout.money import rupeeize, to_rupees


def _insert_person(db, name):
    db.execute("INSERT INTO person_registry (display_name) VALUES (?)", (name,))
    return db.execute(
        "SELECT person_id FROM person_registry WHERE display_name=? "
        "ORDER BY person_id DESC LIMIT 1",
        (name,),
    ).fetchone()[0]


def test_summed_money_column_is_rupee_scaled(db):
    """A SUM of a paise column must convert to rupees (regression: x100 on PG)."""
    pid = _insert_person(db, "scale-check")
    # 500000 paise == 5000.00 rupees, across two rows to force an aggregate.
    for amt in (300000, 200000):
        db.execute(
            "INSERT INTO cod_holds (cycle_start, cycle_end, company, person_id, "
            "amount, source) VALUES ('2026-06-01','2026-06-07','X',?,?,'test')",
            (pid, amt),
        )
    db.commit()
    row = db.execute(
        "SELECT COALESCE(SUM(amount),0) AS total_pending FROM cod_holds WHERE person_id=?", (pid,)
    ).fetchone()
    # The value coming out of the DB must be a plain number the converter accepts.
    out = rupeeize({"total_pending": row["total_pending"]})
    assert out["total_pending"] == 5000.00, (
        f"summed money rendered wrong scale: got {out['total_pending']} "
        f"(raw {row['total_pending']!r}) — expected 5000.00"
    )


def test_to_rupees_basic():
    assert to_rupees(129500) == 1295.00
    assert to_rupees(0) == 0.0
    assert to_rupees(None) == 0.0
