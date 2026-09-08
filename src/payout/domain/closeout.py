"""EV close-out: what happened to the security deposit when an EV came back.

Every EV rider placed a security deposit (₹2,700 normally). When their
assignment closes (returned to the provider, or taken back as spare) the
admin answers, on the web:

* **SD returned to the rider?** Yes → the deposit went back in cash. Nothing
  moves on the books except damage charges, which the rider now owes.
* No → the deposit is held. The admin states **damage charges** and **rent
  charges** (pre-filled with what the books say is owed). Rent is cleared
  from the deposit first (EV back-rent, then carried dues — the same order
  as before), damage is covered next, and whatever is left is the rider's:
  either **credited to their next payout** or refunded in cash. If the
  charges exceed the deposit, the excess is added to the rider's dues.

Until the close-out is done the assignment carries ``closeout_pending = 1``
and the web app keeps asking. All amounts here are paise.
"""

from __future__ import annotations

from datetime import date

from payout.config import EV_DEPOSIT_PAISE
from payout.domain.adjustments import post_adjustment
from payout.domain.arrears import settle_from_deposit


class CloseoutError(ValueError):
    """The close-out cannot be applied; the message says why."""


def save_report(
    conn,
    assignment_id: int,
    *,
    sd_returned: bool,
    damage_charges: int,
    damage_note: str | None,
    reported_by: str,
) -> dict:
    """Record what the recruiter saw when the EV came back.

    An observation, not a settlement: nothing here posts a transaction, touches
    arrears or moves a rupee. The recruiter is the person standing in the hub
    with the vehicle, so they are who knows whether the deposit went back in
    cash and what the damage looks like; the admin still decides what that
    costs, on a form this pre-fills.

    Re-reporting overwrites — a recruiter who mistyped the damage should be
    able to correct it, and a second row for the same assignment would leave
    the admin guessing which one is true. Refused once the admin has settled,
    because by then the number has already been charged.
    """
    a = conn.execute(
        "SELECT assignment_id, ev_id, person_id, returned_date FROM ev_assignments "
        "WHERE assignment_id=?",
        (assignment_id,),
    ).fetchone()
    if not a:
        raise CloseoutError("Assignment not found")
    if a["returned_date"] is None:
        raise CloseoutError("This EV is still with the rider — return it or mark it spare first")
    if conn.execute(
        "SELECT 1 FROM ev_closeouts WHERE assignment_id=?", (assignment_id,)
    ).fetchone():
        raise CloseoutError("The office has already settled this deposit")
    if damage_charges < 0:
        raise CloseoutError("Damage charges cannot be negative")
    if sd_returned and damage_charges:
        raise CloseoutError(
            "The deposit cannot have gone back in full and damage be owed as well — "
            "keep the deposit, or record no damage"
        )

    conn.execute("DELETE FROM ev_closeout_reports WHERE assignment_id=?", (assignment_id,))
    conn.execute(
        "INSERT INTO ev_closeout_reports (assignment_id, ev_id, person_id, sd_returned, "
        "  damage_charges, damage_note, reported_by) VALUES (?,?,?,?,?,?,?)",
        (
            assignment_id,
            a["ev_id"],
            int(a["person_id"]),
            1 if sd_returned else 0,
            int(damage_charges),
            (damage_note or "").strip() or None,
            reported_by,
        ),
    )
    return report_for(conn, assignment_id) or {}


def report_for(conn, assignment_id: int) -> dict | None:
    """The recruiter's field report for one assignment, or None."""
    row = conn.execute(
        "SELECT assignment_id, ev_id, person_id, sd_returned, damage_charges, damage_note, "
        "       photo_key, reported_by, reported_at FROM ev_closeout_reports "
        "WHERE assignment_id=?",
        (assignment_id,),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["sd_returned"] = bool(d["sd_returned"])
    d["has_photo"] = bool(d.pop("photo_key", None))
    return d


def owed_now(conn, person_id: int) -> tuple[int, int]:
    """(EV back-rent arrears, carried dues) the person owes right now, paise."""
    row = conn.execute(
        "SELECT COALESCE(ea.outstanding, 0) AS arr, "
        "       CASE WHEN COALESCE(b.current_balance, 0) < 0 THEN -b.current_balance ELSE 0 END "
        "         AS dues "
        "FROM person_registry pr "
        "LEFT JOIN ev_arrears ea ON ea.person_id = pr.person_id "
        "LEFT JOIN balances b ON b.person_id = pr.person_id "
        "WHERE pr.person_id=?",
        (person_id,),
    ).fetchone()
    if not row:
        return 0, 0
    return int(row["arr"] or 0), int(row["dues"] or 0)


def pending_closeouts(conn) -> list[dict]:
    """Closed assignments still waiting for the admin's answer."""
    rows = conn.execute(
        "SELECT a.assignment_id, a.ev_id, a.person_id, a.handover_date, a.returned_date, "
        "       pr.display_name AS name, u.status AS ev_status, m.model_name AS model, "
        "       COALESCE(ea.outstanding, 0) AS arrears_outstanding, "
        "       CASE WHEN COALESCE(b.current_balance, 0) < 0 THEN -b.current_balance ELSE 0 END "
        "         AS dues_outstanding "
        "FROM ev_assignments a "
        "JOIN person_registry pr ON pr.person_id = a.person_id "
        "LEFT JOIN ev_units u ON u.ev_id = a.ev_id "
        "LEFT JOIN ev_models m ON m.model_id = u.model_id "
        "LEFT JOIN ev_arrears ea ON ea.person_id = a.person_id "
        "LEFT JOIN balances b ON b.person_id = a.person_id "
        "WHERE a.closeout_pending = 1 "
        "ORDER BY a.returned_date DESC, a.assignment_id DESC"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        # The recruiter who took the vehicle back may already have answered the
        # deposit and damage questions in the field. Their report becomes the
        # suggestion, so the admin confirms an answer rather than inventing one
        # about a vehicle they have not seen.
        report = report_for(conn, int(d["assignment_id"]))
        d["report"] = report
        d["suggested"] = {
            "sd_amount": 0 if (report and report["sd_returned"]) else EV_DEPOSIT_PAISE,
            "sd_returned": bool(report["sd_returned"]) if report else False,
            "rent_charges": int(d["arrears_outstanding"]) + int(d["dues_outstanding"]),
            "damage_charges": int(report["damage_charges"]) if report else 0,
        }
        out.append(d)
    return out


def mark_pending(conn, assignment_id: int) -> None:
    conn.execute(
        "UPDATE ev_assignments SET closeout_pending=1 WHERE assignment_id=?", (assignment_id,)
    )


def apply_closeout(
    conn,
    assignment_id: int,
    *,
    sd_returned: bool,
    sd_amount: int | None,
    damage_charges: int,
    rent_charges: int | None,
    credit_next_payout: bool,
    note: str | None,
    created_by: str,
) -> dict:
    """Settle the deposit for one closed assignment and record the answer.

    Returns the ev_closeouts row as a dict (paise). Raises CloseoutError when
    the assignment is unknown, still open, or already closed out."""
    a = conn.execute(
        "SELECT assignment_id, ev_id, person_id, returned_date, closeout_pending "
        "FROM ev_assignments WHERE assignment_id=?",
        (assignment_id,),
    ).fetchone()
    if not a:
        raise CloseoutError("Assignment not found")
    if a["returned_date"] is None:
        raise CloseoutError("This EV is still with the rider — return it or mark it spare first")
    if conn.execute(
        "SELECT 1 FROM ev_closeouts WHERE assignment_id=?", (assignment_id,)
    ).fetchone():
        raise CloseoutError("This EV has already been closed out")
    if damage_charges < 0 or (rent_charges is not None and rent_charges < 0):
        raise CloseoutError("Charges cannot be negative")
    pid, ev_id = int(a["person_id"]), a["ev_id"]
    arr, dues = owed_now(conn, pid)
    tag = f"EV {ev_id}"

    if sd_returned:
        sd = 0
        rent_req = 0
        rent_applied = 0
        refund = 0
        mode = None
        shortfall = damage_charges
        if damage_charges > 0:
            post_adjustment(
                conn,
                pid,
                -damage_charges,
                f"Damage charges after closing {tag} (deposit returned to rider)",
                created_by,
            )
    else:
        sd = int(EV_DEPOSIT_PAISE if sd_amount is None else sd_amount)
        if sd < 0:
            raise CloseoutError("Deposit amount cannot be negative")
        rent_req = int(arr + dues if rent_charges is None else rent_charges)
        # Rent comes off the deposit first, but only what the books actually
        # show as owed (the deposit cannot clear rent that was never charged).
        rent_applied = settle_from_deposit(
            conn, pid, created_by=created_by, ev_id=ev_id, cap=min(sd, rent_req)
        )
        left = sd - rent_applied - damage_charges
        if left >= 0:
            refund, shortfall = left, 0
            mode = None
            if refund > 0:
                mode = "next_payout" if credit_next_payout else "cash"
                if credit_next_payout:
                    post_adjustment(
                        conn,
                        pid,
                        refund,
                        f"Security deposit refund after closing {tag}"
                        + (
                            f" (damage {damage_charges / 100:,.0f} deducted)"
                            if damage_charges
                            else ""
                        ),
                        created_by,
                    )
        else:
            refund, shortfall, mode = 0, -left, None
            post_adjustment(
                conn,
                pid,
                -shortfall,
                f"Damage charges beyond the security deposit after closing {tag}",
                created_by,
            )

    conn.execute(
        "INSERT INTO ev_closeouts (assignment_id, ev_id, person_id, sd_returned, sd_amount, "
        "damage_charges, rent_charges, rent_applied, refund_due, refund_mode, shortfall, note, "
        "created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            assignment_id,
            ev_id,
            pid,
            1 if sd_returned else 0,
            sd,
            damage_charges,
            rent_req,
            rent_applied,
            refund,
            mode,
            shortfall,
            (note or "").strip() or None,
            created_by,
        ),
    )
    conn.execute(
        "UPDATE ev_assignments SET closeout_pending=0 WHERE assignment_id=?", (assignment_id,)
    )
    return {
        "assignment_id": assignment_id,
        "ev_id": ev_id,
        "person_id": pid,
        "sd_returned": sd_returned,
        "sd_amount": sd,
        "damage_charges": damage_charges,
        "rent_charges": rent_req,
        "rent_applied": rent_applied,
        "refund_due": refund,
        "refund_mode": mode,
        "shortfall": shortfall,
        "note": (note or "").strip() or None,
        "created_by": created_by,
        "closed_on": date.today().isoformat(),
    }
