"""payout-manage - database setup and seed-data import."""

from __future__ import annotations

import argparse
from pathlib import Path

from payout.auth import hash_password
from payout.db import get_connection, initialize_database
from payout.ingest import import_seed, preview_seed


def _create_admin(email: str, password: str) -> None:
    with get_connection() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            print(f"  admin '{email}' already exists - skipping")
            return
        conn.execute(
            "INSERT INTO users (email, password_hash, role) VALUES (?,?, 'admin')",
            (email, hash_password(password)),
        )
        conn.commit()
        print(f"  admin user created: {email}")


def cmd_init(args) -> None:
    initialize_database()
    print("  schema + reference data ready")
    if args.email and args.password:
        _create_admin(args.email.strip().lower(), args.password)
    else:
        print("  (no --email/--password; add an admin later with `payout-admin add-user`)")


def _print_report(report) -> None:
    print(f"  committed: {report.committed}")
    for section, stats in report.stats.items():
        print(f"  [{section}] " + ", ".join(f"{k}={v}" for k, v in stats.items()))
    for w in report.warnings:
        print(f"    - {w}")
    for e in report.errors:
        print(f"    ! {e}")


def cmd_seed(args) -> None:
    data = Path(args.workbook).read_bytes()
    print("DRY RUN (nothing written):")
    _print_report(preview_seed(data))
    if args.commit:
        print("\nCOMMITTING:")
        _print_report(import_seed(data, created_by=args.created_by))
    else:
        print("\nPreview only. Re-run with --commit to apply.")


def cmd_rollback(args) -> None:
    """Undo a committed cycle: delete its transactions, rewind balances,
    rewind ev_arrears and rent_charged_through. Idempotent — safe to re-run.

    Cycles are matched on (company, cycle_start, cycle_end). After deleting the
    cycle's transactions, balances and ev_arrears are recomputed from whatever
    transactions remain for each affected person.
    """
    company, cs, ce = args.company, args.cycle_start, args.cycle_end
    with get_connection() as conn:
        affected = [
            r["person_id"]
            for r in conn.execute(
                "SELECT DISTINCT person_id FROM transactions "
                "WHERE company=? AND cycle_start=? AND cycle_end=?",
                (company, cs, ce),
            ).fetchall()
        ]
        if not affected and not args.force:
            print(f"  No transactions found for {company} {cs}..{ce}. Nothing to do.")
            return
        print(f"  Affecting {len(affected)} person(s)")
        if not args.commit:
            print("  DRY RUN — re-run with --commit to actually delete")
            return

        n = conn.execute(
            "DELETE FROM transactions WHERE company=? AND cycle_start=? AND cycle_end=?",
            (company, cs, ce),
        ).rowcount
        print(f"  Deleted {n} transaction(s)")

        # Recompute each affected person's general balance + EV arrears from
        # whatever transactions remain.
        for pid in affected:
            # Balance = sum of all PAYOUT/RENT/ADJUSTMENT/DUES_CARRY/OPENING amounts,
            # clamped to <= 0 (positive balances aren't carried; they're released).
            # Simpler: pick the most-recent transaction's balance_after.
            row = conn.execute(
                "SELECT balance_after FROM transactions WHERE person_id=? ORDER BY id DESC LIMIT 1",
                (pid,),
            ).fetchone()
            bal = float(row["balance_after"]) if row else 0.0
            conn.execute(
                "UPDATE balances SET current_balance=?, last_updated=date('now') WHERE person_id=?",
                (bal, pid),
            )
            # EV arrears: total_missed = sum of RENT_MISSED amounts (positive),
            # total_recovered = sum of RENT_RECOVERED amounts.
            missed = conn.execute(
                "SELECT COALESCE(SUM(-amount), 0) AS s FROM transactions "
                "WHERE person_id=? AND event_type='RENT_MISSED'",
                (pid,),
            ).fetchone()["s"]
            recovered = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) AS s FROM transactions "
                "WHERE person_id=? AND event_type='RENT_RECOVERED'",
                (pid,),
            ).fetchone()["s"]
            opening = conn.execute(
                "SELECT COALESCE(SUM(-amount), 0) AS s FROM transactions "
                "WHERE person_id=? AND event_type='OPENING' "
                "AND remarks LIKE '%EV arrears%'",
                (pid,),
            ).fetchone()["s"]
            total_missed = float(missed) + float(opening)
            outstanding = max(0.0, total_missed - float(recovered))
            conn.execute(
                "UPDATE ev_arrears SET total_missed=?, total_recovered=?, "
                "outstanding=?, last_updated=date('now') WHERE person_id=?",
                (total_missed, float(recovered), outstanding, pid),
            )
            # rent_charged_through: rewind to the latest cycle_end still present
            # for this person, else NULL.
            last = conn.execute(
                "SELECT MAX(cycle_end) AS m FROM transactions "
                "WHERE person_id=? AND event_type='RENT'",
                (pid,),
            ).fetchone()
            rct = last["m"] if last and last["m"] else None
            conn.execute(
                "UPDATE ev_assignments SET rent_charged_through=? "
                "WHERE person_id=? AND returned_date IS NULL",
                (rct, pid),
            )
        # Also drop COD holds for this cycle so the same file can be re-uploaded.
        conn.execute(
            "DELETE FROM cod_holds WHERE company=? AND cycle_start=? AND cycle_end=?",
            (company, cs, ce),
        )
        conn.commit()
        print(f"  Rebalanced {len(affected)} person(s); rolled back COD holds.")


def cmd_reset_cycles(args) -> None:
    """Delete every committed cycle, rewind balances back to the seed openings.

    Keeps person_registry, rider_master, ev_units, ev_assignments, ev_models,
    companies, users — and any OPENING transactions from the seed import.
    Wipes RENT / PAYOUT / RENT_MISSED / RENT_RECOVERED / COD_* / DUES_CARRY /
    ADJUSTMENT rows. Recomputes balances + arrears from the surviving OPENING
    rows so the system is at "post-seed, pre-first-cycle" state.
    """
    with get_connection() as conn:
        n_txn_before = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        n_op = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE event_type = 'OPENING'"
        ).fetchone()[0]
        n_to_delete = n_txn_before - n_op
        print(
            f"  {n_txn_before} total transactions, {n_op} OPENING (kept), "
            f"{n_to_delete} cycle/adjustment (will delete)"
        )
        if not args.commit:
            print("  DRY RUN — re-run with --commit to actually delete")
            return

        conn.execute("DELETE FROM transactions WHERE event_type <> 'OPENING'")
        conn.execute("DELETE FROM cod_holds")
        conn.execute("UPDATE ev_assignments SET rent_charged_through = NULL")

        # Rewind balances from surviving OPENING rows (sum of opening dues entries).
        conn.execute(
            "UPDATE balances SET current_balance = COALESCE(("
            "    SELECT SUM(t.amount) FROM transactions t "
            "    WHERE t.person_id = balances.person_id "
            "      AND t.event_type = 'OPENING' "
            "      AND (t.remarks LIKE 'Opening dues%' OR t.remarks IS NULL)"
            "), 0), last_updated = date('now')"
        )

        # Rewind ev_arrears from surviving OPENING EV-arrears rows.
        conn.execute(
            "UPDATE ev_arrears SET "
            "  total_missed = COALESCE((SELECT -SUM(t.amount) FROM transactions t "
            "    WHERE t.person_id = ev_arrears.person_id AND t.event_type='OPENING' "
            "      AND t.remarks LIKE 'Opening EV arrears%'), 0), "
            "  total_recovered = 0, "
            "  outstanding = COALESCE((SELECT -SUM(t.amount) FROM transactions t "
            "    WHERE t.person_id = ev_arrears.person_id AND t.event_type='OPENING' "
            "      AND t.remarks LIKE 'Opening EV arrears%'), 0), "
            "  cod_missed = COALESCE((SELECT -SUM(t.amount) FROM transactions t "
            "    WHERE t.person_id = ev_arrears.person_id AND t.event_type='OPENING' "
            "      AND t.remarks LIKE 'Opening COD%'), 0), "
            "  cod_recovered = 0, "
            "  cod_outstanding = COALESCE((SELECT -SUM(t.amount) FROM transactions t "
            "    WHERE t.person_id = ev_arrears.person_id AND t.event_type='OPENING' "
            "      AND t.remarks LIKE 'Opening COD%'), 0), "
            "  last_updated = date('now')"
        )
        conn.commit()
        print(f"  Deleted {n_to_delete} cycle/adjustment transactions.")
        print("  Cleared cod_holds and rent_charged_through.")
        print("  Balances + arrears rewound to seed-opening state.")


def cmd_set_password(args) -> None:
    """Set (or reset) a user's password from the server — the escape hatch
    when nobody can sign in and email reset is not configured."""
    import getpass

    from payout.auth import hash_password
    from payout.db.connection import get_connection

    email = args.email.strip().lower()
    pw = args.password or getpass.getpass(f"New password for {email}: ")
    if len(pw) < 8:
        raise SystemExit("Password must be at least 8 characters.")
    conn = get_connection()
    try:
        if not conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise SystemExit(f"No user {email}. Existing users: payout-manage users")
        conn.execute(
            "UPDATE users SET password_hash=?, is_active=1 WHERE email=?",
            (hash_password(pw), email),
        )
        conn.execute(
            "UPDATE password_reset_tokens SET used_at=datetime('now') "
            "WHERE email=? AND used_at IS NULL",
            (email,),
        )
        conn.commit()
        print(f"Password set for {email} (account active).")
    finally:
        conn.close()


def cmd_test_email(args) -> None:
    """Send one test email through the configured SMTP settings and say
    exactly what went wrong if it did not go out."""
    import logging

    from payout.notifications import _smtp_settings, email_configured, send_email

    host, port, user, _pwd, sender = _smtp_settings()
    if not email_configured():
        raise SystemExit(
            "SMTP is not configured. Set PAYOUT_SMTP_HOST/PORT/USER/PASS (and optionally "
            "PAYOUT_SMTP_FROM) in deploy/.env, then `docker compose ... up -d`."
        )
    print(f"SMTP {host}:{port} as {user}, from {sender} -> {args.to}")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ok = send_email(
        args.to,
        "Payout System - test email",
        "This is a test from payout-manage test-email. If you can read this, "
        "password-reset emails will work.\n",
    )
    print("Sent." if ok else "FAILED - see the error above (wrong app password? 2-Step off?).")
    raise SystemExit(0 if ok else 1)


def cmd_test_whatsapp(args) -> None:
    """Send one test code through the WhatsApp Cloud API template."""
    import logging

    from payout.auth.phone import normalize_phone
    from payout.notifications import send_whatsapp_otp, whatsapp_configured

    to = normalize_phone(args.to)
    if not to:
        raise SystemExit("--to must be a phone number (10 digits or +country code).")
    if not whatsapp_configured():
        raise SystemExit(
            "WhatsApp is not configured. Set PAYOUT_WA_TOKEN and PAYOUT_WA_PHONE_ID "
            "(optionally PAYOUT_WA_TEMPLATE / PAYOUT_WA_LANG) in deploy/.env, then up -d."
        )
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ok = send_whatsapp_otp(to, "123456")
    print(f"Accepted by Meta for {to} (code 123456)." if ok else "FAILED - see the error above.")
    raise SystemExit(0 if ok else 1)


def cmd_users(args) -> None:
    from payout.db.connection import get_connection

    conn = get_connection()
    try:
        for r in conn.execute("SELECT email, role, is_active FROM users ORDER BY email"):
            print(f"{r['email']:40} {r['role']:10} {'active' if r['is_active'] else 'inactive'}")
    finally:
        conn.close()


def cmd_unbilled_days(args) -> None:
    """List (and with --apply, book to arrears) EV days behind a meter that no
    cycle ever billed — the 2026-09-04 rent-gap sweep."""
    from payout.db.connection import get_connection
    from payout.domain.unbilled import apply_unbilled, scan_unbilled

    conn = get_connection()
    try:
        found = scan_unbilled(conn, lookback_days=args.lookback)
        if args.person:
            found = [f for f in found if f["person_id"] in args.person]
        if not found:
            print("No unbilled EV days found.")
            return
        total = 0
        for f in found:
            print(
                f"#{f['person_id']} {f['name']}  {f['ev_id']}  handover={f['handover']}  "
                f"meter={f['meter']}  returned={f['returned'] or '-'}"
            )
            for r in f["runs"]:
                print(f"    {r['from']}..{r['to']}  {r['days']:>3}d  Rs.{r['amount'] / 100:,.2f}")
            total += f["amount"]
        print(f"{len(found)} assignment(s), Rs.{total / 100:,.2f} unbilled in total.")
        if not args.apply:
            print("Dry run. Re-run with --apply (optionally --person ID ...) to book to arrears.")
            return
        booked = 0
        for f in found:
            for r in f["runs"]:
                amt = apply_unbilled(
                    conn,
                    person_id=f["person_id"],
                    ev_id=f["ev_id"],
                    day_from=r["from"],
                    day_to=r["to"],
                    created_by=args.created_by,
                )
                booked += amt
                print(
                    f"  booked #{f['person_id']} {f['name']} {r['from']}..{r['to']} "
                    f"Rs.{amt / 100:,.2f}"
                )
        conn.commit()
        print(f"Booked Rs.{booked / 100:,.2f} to EV arrears (RENT_MISSED).")
    finally:
        conn.close()


def main() -> None:
    p = argparse.ArgumentParser(prog="payout-manage", description="Payout System - setup & import")
    sub = p.add_subparsers(dest="command")
    pi = sub.add_parser("init", help="Create schema, seed reference data, optional admin user")
    pi.add_argument("--email")
    pi.add_argument("--password")
    ps = sub.add_parser("seed", help="Import the onboarding workbook (preview unless --commit)")
    ps.add_argument("workbook", help="Path to the seed .xlsx")
    ps.add_argument("--commit", action="store_true", help="Actually write to the database")
    ps.add_argument("--created-by", default="seed_import")
    prx = sub.add_parser("reset-cycles", help="Delete every committed cycle (keeps seed openings)")
    prx.add_argument("--commit", action="store_true", help="Actually delete")
    pr = sub.add_parser("rollback", help="Undo a previously committed cycle")
    pr.add_argument("--company", required=True)
    pr.add_argument("--cycle-start", dest="cycle_start", required=True)
    pr.add_argument("--cycle-end", dest="cycle_end", required=True)
    pr.add_argument("--commit", action="store_true", help="Actually delete")
    pr.add_argument(
        "--force", action="store_true", help="Proceed even if no transactions are matched"
    )
    pu = sub.add_parser(
        "unbilled-days", help="EV days behind a meter that no cycle billed (report; --apply books)"
    )
    pu.add_argument("--apply", action="store_true", help="Book the runs to EV arrears")
    pu.add_argument("--lookback", type=int, default=120, help="Days back to scan (default 120)")
    pu.add_argument(
        "--person", type=int, nargs="*", help="Only these person ids (default: everyone)"
    )
    pu.add_argument("--created-by", default="unbilled-days")
    pp = sub.add_parser("set-password", help="Set or reset a user's password (prompts if omitted)")
    pp.add_argument("--email", required=True)
    pp.add_argument("--password", help="Omit to be prompted without echo")
    sub.add_parser("users", help="List users and roles")
    pt = sub.add_parser("test-email", help="Send a test email via PAYOUT_SMTP_* settings")
    pt.add_argument("--to", required=True)
    pw = sub.add_parser("test-whatsapp", help="Send a test code via the WhatsApp Cloud API")
    pw.add_argument("--to", required=True, help="Phone number, e.g. 98765 43210")
    args = p.parse_args()
    if args.command == "init":
        cmd_init(args)
    elif args.command == "seed":
        cmd_seed(args)
    elif args.command == "rollback":
        cmd_rollback(args)
    elif args.command == "reset-cycles":
        cmd_reset_cycles(args)
    elif args.command == "unbilled-days":
        cmd_unbilled_days(args)
    elif args.command == "set-password":
        cmd_set_password(args)
    elif args.command == "users":
        cmd_users(args)
    elif args.command == "test-email":
        cmd_test_email(args)
    elif args.command == "test-whatsapp":
        cmd_test_whatsapp(args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
