"""Person profile + manual rider linking (merge)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from payout.api.auth import get_current_user, require_admin
from payout.api.schemas import EvSummary, LinkRidersIn, PersonOut, RiderOut, SplitPersonIn
from payout.db import get_connection

router = APIRouter()


def _rider_dict(row) -> dict:
    d = dict(row); d["is_active"] = bool(d["is_active"]); return d


@router.get("/{person_id}")
def get_person(person_id: int, _: dict = Depends(get_current_user)) -> PersonOut:
    with get_connection() as conn:
        pr = conn.execute(
            "SELECT pr.person_id, pr.display_name, pr.deduction_company, pr.deduction_rider_id, "
            "       COALESCE(b.current_balance, 0)  AS current_balance, "
            "       COALESCE(ea.outstanding, 0)     AS arrears_outstanding "
            "FROM person_registry pr "
            "LEFT JOIN balances   b  ON b.person_id  = pr.person_id "
            "LEFT JOIN ev_arrears ea ON ea.person_id = pr.person_id "
            "WHERE pr.person_id=?", (person_id,),
        ).fetchone()
        if not pr:
            raise HTTPException(404, "Person not found")
        # Vehicle derived: EV when the person currently holds an open EV
        # assignment, BIKE otherwise — same rule as the riders list.
        riders = [RiderOut(**_rider_dict(r)) for r in conn.execute(
            "SELECT rm.rider_id, rm.company, rm.person_id, rm.name, rm.hub, "
            "       CASE WHEN ea.assignment_id IS NOT NULL THEN 'EV' ELSE 'BIKE' END AS vehicle, "
            "       rm.account_no, rm.ifsc, rm.mob_no, rm.is_active "
            "FROM rider_master rm "
            "LEFT JOIN ev_assignments ea "
            "  ON ea.person_id = rm.person_id AND ea.returned_date IS NULL "
            "WHERE rm.person_id=? ORDER BY rm.company", (person_id,),
        )]
        ev_row = conn.execute(
            "SELECT a.ev_id, a.handover_date, a.rent_charged_through, "
            "       m.provider, m.model_name, m.weekly_rate "
            "FROM ev_assignments a "
            "JOIN ev_units  u ON u.ev_id    = a.ev_id "
            "JOIN ev_models m ON m.model_id = u.model_id "
            "WHERE a.person_id=? AND a.returned_date IS NULL", (person_id,),
        ).fetchone()
        # EV history (closed + open). Newest first.
        history_rows = conn.execute(
            "SELECT a.assignment_id, a.ev_id, a.handover_date, a.returned_date, "
            "       a.rent_charged_through, m.provider, m.model_name, m.weekly_rate "
            "FROM ev_assignments a "
            "JOIN ev_units  u ON u.ev_id    = a.ev_id "
            "JOIN ev_models m ON m.model_id = u.model_id "
            "WHERE a.person_id=? "
            "ORDER BY a.returned_date IS NULL DESC, "
            "         COALESCE(a.handover_date, a.created_at) DESC", (person_id,),
        ).fetchall()
    ev_summary = (
        EvSummary(ev_id=ev_row["ev_id"], provider=ev_row["provider"], model=ev_row["model_name"],
                  weekly_rate=float(ev_row["weekly_rate"]),
                  handover_date=ev_row["handover_date"],
                  rent_charged_through=ev_row["rent_charged_through"])
        if ev_row else None
    )
    ev_history = [
        {
            "assignment_id": h["assignment_id"],
            "ev_id": h["ev_id"],
            "provider": h["provider"],
            "model": h["model_name"],
            "weekly_rate": float(h["weekly_rate"]),
            "handover_date": h["handover_date"],
            "returned_date": h["returned_date"],
            "rent_charged_through": h["rent_charged_through"],
        }
        for h in history_rows
    ]
    out = PersonOut(
        person_id=pr["person_id"], display_name=pr["display_name"],
        deduction_company=pr["deduction_company"], deduction_rider_id=pr["deduction_rider_id"],
        current_balance=pr["current_balance"], arrears_outstanding=pr["arrears_outstanding"],
        riders=riders, ev=ev_summary,
    )
    return {**out.model_dump(), "ev_history": ev_history}


@router.post("/{person_id}/split")
def split_person(person_id: int, body: SplitPersonIn,
                 user: dict = Depends(require_admin)) -> dict:
    """Carve a subset of the person's rider_master rows out into a brand-new
    person. Transactions and COD holds for those (rider_id, company) pairs
    follow. Balance and EV arrears split by the fractions provided (default:
    everything stays with the source). The open EV assignment optionally
    moves to the new person.
    """
    if not body.rider_ids:
        raise HTTPException(400, "Pick at least one (rider_id, company) to split off.")
    with get_connection() as conn:
        src = conn.execute(
            "SELECT person_id, display_name FROM person_registry WHERE person_id=?",
            (person_id,),
        ).fetchone()
        if not src:
            raise HTTPException(404, f"Person {person_id} not found")

        # Verify all the riders we're about to move actually belong to this person.
        existing = {
            (r["rider_id"], r["company"])
            for r in conn.execute(
                "SELECT rider_id, company FROM rider_master WHERE person_id=?",
                (person_id,),
            )
        }
        for spec in body.rider_ids:
            if (spec.rider_id, spec.company) not in existing:
                raise HTTPException(
                    400,
                    f"Rider {spec.rider_id}@{spec.company} doesn't belong to person {person_id}.",
                )
        if len(body.rider_ids) >= len(existing):
            raise HTTPException(
                400,
                "Splitting off every rider would leave the source person empty. "
                "Keep at least one rider on the source.",
            )

        # Create the new person row.
        first = body.rider_ids[0]
        new_name = (body.new_display_name or f"{src['display_name']} (split)").strip()
        cur = conn.execute(
            "INSERT INTO person_registry (display_name, deduction_company, deduction_rider_id) "
            "VALUES (?,?,?)",
            (new_name, first.company, first.rider_id),
        )
        new_pid = cur.lastrowid

        # Move each selected rider + all of its transactions and COD holds.
        for spec in body.rider_ids:
            conn.execute(
                "UPDATE rider_master SET person_id=? WHERE rider_id=? AND company=?",
                (new_pid, spec.rider_id, spec.company),
            )
            conn.execute(
                "UPDATE transactions SET person_id=? WHERE rider_id=? AND company=?",
                (new_pid, spec.rider_id, spec.company),
            )
            conn.execute(
                "UPDATE cod_holds SET person_id=? WHERE rider_id=? AND company=?",
                (new_pid, spec.rider_id, spec.company),
            )

        # ev_assignments — move the open assignment if asked, otherwise leave alone.
        if body.transfer_open_ev:
            conn.execute(
                "UPDATE ev_assignments SET person_id=? "
                "WHERE person_id=? AND returned_date IS NULL",
                (new_pid, person_id),
            )

        # Initialise new person's bookkeeping rows.
        conn.execute(
            "INSERT OR IGNORE INTO balances (person_id, current_balance, last_updated) "
            "VALUES (?,0,date('now'))", (new_pid,))
        conn.execute(
            "INSERT OR IGNORE INTO ev_arrears (person_id, total_missed, total_recovered, "
            "outstanding, last_updated) VALUES (?,0,0,0,date('now'))", (new_pid,))
        conn.execute(
            "INSERT OR IGNORE INTO status_tracking (person_id, status) "
            "VALUES (?, 'active')", (new_pid,))

        # NOTE: pending_xc_rent intentionally stays with the source person.
        # The bucket represents a *specific* cycle's cross-company shortfall
        # tied to a specific company's run — it doesn't have a natural meaning
        # for a freshly-carved-off split, so the source keeps it. If you want
        # to clear it before splitting, post a manual adjustment first.
        # Optional money transfers.
        bf = max(0.0, min(1.0, body.transfer_balance_fraction or 0.0))
        af = max(0.0, min(1.0, body.transfer_arrears_fraction or 0.0))
        if bf > 0:
            row = conn.execute(
                "SELECT current_balance FROM balances WHERE person_id=?", (person_id,)
            ).fetchone()
            cur_bal = float(row["current_balance"] or 0)
            to_move = round(cur_bal * bf, 2)
            if to_move != 0:
                conn.execute(
                    "UPDATE balances SET current_balance = current_balance - ? "
                    "WHERE person_id=?", (to_move, person_id))
                conn.execute(
                    "UPDATE balances SET current_balance = current_balance + ? "
                    "WHERE person_id=?", (to_move, new_pid))
        if af > 0:
            arr = conn.execute(
                "SELECT total_missed, total_recovered, outstanding, "
                "       cod_missed, cod_recovered, cod_outstanding "
                "FROM ev_arrears WHERE person_id=?", (person_id,)
            ).fetchone()
            if arr:
                conn.execute(
                    "UPDATE ev_arrears SET "
                    "  total_missed    = total_missed    * (1-?), "
                    "  total_recovered = total_recovered * (1-?), "
                    "  outstanding     = outstanding     * (1-?), "
                    "  cod_missed      = cod_missed      * (1-?), "
                    "  cod_recovered   = cod_recovered   * (1-?), "
                    "  cod_outstanding = cod_outstanding * (1-?) "
                    "WHERE person_id=?",
                    (af, af, af, af, af, af, person_id))
                conn.execute(
                    "UPDATE ev_arrears SET "
                    "  total_missed    = total_missed    + ?, "
                    "  total_recovered = total_recovered + ?, "
                    "  outstanding     = outstanding     + ?, "
                    "  cod_missed      = cod_missed      + ?, "
                    "  cod_recovered   = cod_recovered   + ?, "
                    "  cod_outstanding = cod_outstanding + ? "
                    "WHERE person_id=?",
                    ((arr["total_missed"]    or 0) * af,
                     (arr["total_recovered"] or 0) * af,
                     (arr["outstanding"]     or 0) * af,
                     (arr["cod_missed"]      or 0) * af,
                     (arr["cod_recovered"]   or 0) * af,
                     (arr["cod_outstanding"] or 0) * af,
                     new_pid))
        conn.commit()

    return {
        "split": True,
        "source_person_id": person_id,
        "new_person_id": new_pid,
        "new_display_name": new_name,
        "moved_riders": [{"rider_id": s.rider_id, "company": s.company} for s in body.rider_ids],
    }


@router.post("/link")
def link_riders(body: LinkRidersIn, _: dict = Depends(require_admin)) -> dict:
    """Merge the secondary person into the primary. Primary keeps their
    person_id, display_name and history; all of secondary's rider_master rows,
    transactions, balance and arrears collapse into primary.

    Accepts either a pair of person IDs (preferred) or two (rider_id, company)
    tuples — for backwards compatibility with older API clients.
    """
    with get_connection() as conn:
        def resolve(pid, rid, co, side):
            if pid is not None:
                row = conn.execute("SELECT person_id FROM person_registry WHERE person_id=?",
                                   (pid,)).fetchone()
                if not row:
                    raise HTTPException(404, f"{side} person_id {pid} not found")
                return row["person_id"]
            if rid and co:
                row = conn.execute(
                    "SELECT person_id FROM rider_master WHERE rider_id=? AND company=?",
                    (rid, co)).fetchone()
                if not row:
                    raise HTTPException(404, f"{side} rider {rid}@{co} not found")
                return row["person_id"]
            raise HTTPException(400, f"{side}: provide person_id or rider_id+company")

        primary   = resolve(body.primary_person_id,
                            body.primary_rider_id, body.primary_company, "primary")
        secondary = resolve(body.secondary_person_id,
                            body.secondary_rider_id, body.secondary_company, "secondary")
        if primary == secondary:
            return {"merged": False, "reason": "Already same person", "person_id": primary}
        # Move everything that references person_registry from secondary →
        # primary BEFORE we drop the secondary row, otherwise the FK constraint
        # blocks the DELETE and the merge silently 500s on the client.

        # rider_master: move all rider IDs.
        conn.execute("UPDATE rider_master SET person_id=? WHERE person_id=?",
                     (primary, secondary))
        # ev_assignments: move history. If BOTH sides have an open assignment
        # we can't move the secondary's open row (UNIQUE per person), so close
        # it as of today.
        primary_open = conn.execute(
            "SELECT 1 FROM ev_assignments WHERE person_id=? AND returned_date IS NULL",
            (primary,),
        ).fetchone()
        if primary_open:
            conn.execute(
                "UPDATE ev_assignments SET returned_date = date('now') "
                "WHERE person_id=? AND returned_date IS NULL",
                (secondary,),
            )
        conn.execute("UPDATE ev_assignments SET person_id=? WHERE person_id=?",
                     (primary, secondary))
        # cod_holds: move every line item.
        conn.execute("UPDATE cod_holds SET person_id=? WHERE person_id=?",
                     (primary, secondary))
        # balances: sum secondary's into primary's. This includes the
        # pending_xc_rent bucket — if both halves had an unresolved
        # cross-company rent shortfall, we sum them so neither is lost.
        # Primary's xc_origin_company / xc_origin_cycle_end are preserved;
        # secondary's origin is dropped because we keep one of them and
        # primary's is the more authoritative target for any subsequent
        # company that processes the merged person.
        bal = conn.execute(
            "SELECT current_balance, pending_xc_rent, xc_origin_company, "
            "       xc_origin_cycle_end "
            "FROM balances WHERE person_id=?", (secondary,),
        ).fetchone()
        if bal and (bal["current_balance"] or bal["pending_xc_rent"]):
            conn.execute(
                "INSERT OR IGNORE INTO balances (person_id, current_balance) "
                "VALUES (?, 0)", (primary,))
            # Read primary's current xc state before summing.
            prim_xc = conn.execute(
                "SELECT pending_xc_rent, xc_origin_company, xc_origin_cycle_end "
                "FROM balances WHERE person_id=?", (primary,),
            ).fetchone()
            new_xc_amt = float(prim_xc["pending_xc_rent"] or 0) + float(bal["pending_xc_rent"] or 0)
            new_xc_origin = (
                prim_xc["xc_origin_company"]
                or bal["xc_origin_company"]
            )
            new_xc_cycle_end = (
                prim_xc["xc_origin_cycle_end"]
                or bal["xc_origin_cycle_end"]
            )
            conn.execute(
                "UPDATE balances SET "
                "  current_balance = current_balance + ?, "
                "  pending_xc_rent = ?, "
                "  xc_origin_company = ?, "
                "  xc_origin_cycle_end = ? "
                "WHERE person_id=?",
                (bal["current_balance"] or 0, new_xc_amt,
                 new_xc_origin if new_xc_amt > 0 else None,
                 new_xc_cycle_end if new_xc_amt > 0 else None,
                 primary),
            )
        # ev_arrears: sum the EV-rent + COD buckets.
        arr = conn.execute(
            "SELECT total_missed, total_recovered, outstanding, "
            "       cod_missed, cod_recovered, cod_outstanding "
            "FROM ev_arrears WHERE person_id=?",
            (secondary,)).fetchone()
        if arr:
            conn.execute(
                "INSERT OR IGNORE INTO ev_arrears (person_id) VALUES (?)", (primary,))
            conn.execute(
                "UPDATE ev_arrears SET "
                "  total_missed    = total_missed    + ?, "
                "  total_recovered = total_recovered + ?, "
                "  outstanding     = outstanding     + ?, "
                "  cod_missed      = cod_missed      + ?, "
                "  cod_recovered   = cod_recovered   + ?, "
                "  cod_outstanding = cod_outstanding + ? "
                "WHERE person_id=?",
                (arr["total_missed"] or 0, arr["total_recovered"] or 0,
                 arr["outstanding"] or 0, arr["cod_missed"] or 0,
                 arr["cod_recovered"] or 0, arr["cod_outstanding"] or 0, primary),
            )
        # transactions: move every event so the ledger follows the person.
        conn.execute("UPDATE transactions SET person_id=? WHERE person_id=?",
                     (primary, secondary))
        # ev_daily_ledger: re-attribute the day rows. Without this, recovery
        # walks for the merged person would miss the secondary's pre-merge
        # missed/billed days and the Provider Weekly report would silently
        # under-count their history.
        conn.execute(
            "UPDATE ev_daily_ledger SET assigned_person_id=? "
            "WHERE assigned_person_id=?",
            (primary, secondary),
        )
        # Drop secondary's now-orphaned rows + the person_registry row last.
        for t in ("balances", "ev_arrears", "status_tracking", "person_registry"):
            conn.execute(f"DELETE FROM {t} WHERE person_id=?", (secondary,))
        conn.commit()
    return {"merged": True, "into_person_id": primary, "from_person_id": secondary}
