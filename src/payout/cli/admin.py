"""payout-admin - user and company administration."""

from __future__ import annotations

import argparse

from payout.auth import hash_password
from payout.db import get_connection


def cmd_add_user(args) -> None:
    if args.email:
        email = args.email.strip().lower()
        password = args.password or ""
        role = args.role or "user"
        if not password:
            print("--password is required in non-interactive mode.")
            return
    else:
        email = input("Email: ").strip().lower()
        password = input("Password: ").strip()
        role = input("Role (admin/user) [user]: ").strip() or "user"
    if role not in ("admin", "user"):
        print("Role must be 'admin' or 'user'.")
        return
    with get_connection() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            print(f"User '{email}' already exists.")
            return
        conn.execute(
            "INSERT INTO users (email, password_hash, role) VALUES (?,?,?)",
            (email, hash_password(password), role),
        )
        conn.commit()
    print(f"User '{email}' created ({role}).")


def cmd_list_users(args) -> None:
    with get_connection() as conn:
        users = conn.execute(
            "SELECT email, role, is_active, created_at FROM users ORDER BY email"
        ).fetchall()
    if not users:
        print("No users.")
        return
    print(f"\n{'Email':28} {'Role':7} {'Active':7} Created")
    print("-" * 64)
    for u in users:
        active = "yes" if u["is_active"] else "no"
        print(f"{u['email']:28} {u['role']:7} {active:7} {u['created_at']}")


def cmd_deactivate_user(args) -> None:
    email = (args.email or input("Email to deactivate: ")).strip().lower()
    with get_connection() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            print(f"User '{email}' not found.")
            return
        conn.execute("UPDATE users SET is_active=0 WHERE email=?", (email,))
        conn.commit()
    print(f"User '{email}' deactivated.")


def cmd_reset_password(args) -> None:
    email = (args.email or input("Email: ")).strip().lower()
    password = args.password or input("New password: ").strip()
    if len(password) < 8:
        print("Password must be at least 8 characters.")
        return
    with get_connection() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            print(f"User '{email}' not found.")
            return
        conn.execute("UPDATE users SET password_hash=? WHERE email=?", (hash_password(password), email))
        conn.commit()
    print(f"Password reset for '{email}'.")


def cmd_list_companies(args) -> None:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT company_name, parser_type, payout_column, has_hold_sheet, "
            "hold_style, is_active FROM companies ORDER BY company_name"
        ).fetchall()
    if not rows:
        print("No companies.")
        return
    print(f"\n{'Company':12} {'Parser':10} {'Payout column':24} {'Hold':6} {'Style':8} Active")
    print("-" * 78)
    for r in rows:
        hold = "yes" if r["has_hold_sheet"] else "no"
        active = "yes" if r["is_active"] else "no"
        style = r["hold_style"] or "-"
        payout = r["payout_column"] or ""
        print(f"{r['company_name']:12} {r['parser_type']:10} {payout:24} {hold:6} {style:8} {active}")


def cmd_add_company(args) -> None:
    if not args.name or not args.rider_col or not args.payout_col:
        print("--name, --rider-col and --payout-col are required.")
        return
    with get_connection() as conn:
        if conn.execute("SELECT 1 FROM companies WHERE company_name=?", (args.name,)).fetchone():
            print(f"Company '{args.name}' already exists - use update-company.")
            return
        conn.execute(
            "INSERT INTO companies (company_name, parser_type, payout_sheet, "
            "rider_id_column, payout_column, has_hold_sheet, hold_style, hold_sheet, "
            "hold_key_column, hold_amount_column, hold_status_column, is_active) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (args.name, args.parser_type, args.payout_sheet, args.rider_col,
             args.payout_col, 1 if args.hold else 0, args.hold_style, args.hold_sheet,
             args.hold_key, args.hold_amount, args.hold_status, 1 if args.active else 0),
        )
        conn.commit()
    print(f"Company '{args.name}' added (active={bool(args.active)}).")


def cmd_update_company(args) -> None:
    with get_connection() as conn:
        if not conn.execute("SELECT 1 FROM companies WHERE company_name=?", (args.name,)).fetchone():
            print(f"Company '{args.name}' not found.")
            return
        fields = {}
        if args.active is not None:
            fields["is_active"] = 1 if args.active == "yes" else 0
        if args.payout_col:
            fields["payout_column"] = args.payout_col
        if args.rider_col:
            fields["rider_id_column"] = args.rider_col
        if args.payout_sheet:
            fields["payout_sheet"] = args.payout_sheet
        if not fields:
            print("Nothing to update.")
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE companies SET {sets} WHERE company_name=?", (*fields.values(), args.name))
        conn.commit()
    print(f"Company '{args.name}' updated: {list(fields)}")


def cmd_set_role(args) -> None:
    valid = ("user", "admin", "creator")
    if args.role not in valid:
        print(f"--role must be one of {valid}.")
        return
    email = (args.email or input("Email: ")).strip().lower()
    with get_connection() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            print(f"User '{email}' not found.")
            return
        conn.execute("UPDATE users SET role=? WHERE email=?", (args.role, email))
        conn.commit()
    print(f"Role for '{email}' set to '{args.role}'.")


def main() -> None:
    p = argparse.ArgumentParser(prog="payout-admin", description="Payout System - administration")
    sub = p.add_subparsers(dest="command")

    pu = sub.add_parser("add-user")
    pu.add_argument("--email"); pu.add_argument("--password"); pu.add_argument("--role")
    sub.add_parser("list-users")
    pd_ = sub.add_parser("deactivate-user"); pd_.add_argument("--email")
    pr = sub.add_parser("reset-password"); pr.add_argument("--email"); pr.add_argument("--password")
    psr = sub.add_parser("set-role", help="Promote/demote a user (user|admin|creator)")
    psr.add_argument("--email"); psr.add_argument("--role", required=True)

    sub.add_parser("list-companies")
    pc = sub.add_parser("add-company")
    pc.add_argument("--name"); pc.add_argument("--parser-type", dest="parser_type", default="generic")
    pc.add_argument("--payout-sheet", dest="payout_sheet", default="0")
    pc.add_argument("--rider-col", dest="rider_col"); pc.add_argument("--payout-col", dest="payout_col")
    pc.add_argument("--hold", action="store_true"); pc.add_argument("--hold-style", dest="hold_style")
    pc.add_argument("--hold-sheet", dest="hold_sheet"); pc.add_argument("--hold-key", dest="hold_key")
    pc.add_argument("--hold-amount", dest="hold_amount"); pc.add_argument("--hold-status", dest="hold_status")
    pc.add_argument("--active", action="store_true")
    pcu = sub.add_parser("update-company")
    pcu.add_argument("--name", required=True); pcu.add_argument("--active", choices=["yes", "no"])
    pcu.add_argument("--payout-col", dest="payout_col"); pcu.add_argument("--rider-col", dest="rider_col")
    pcu.add_argument("--payout-sheet", dest="payout_sheet")

    args = p.parse_args()
    dispatch = {
        "add-user": cmd_add_user, "list-users": cmd_list_users,
        "deactivate-user": cmd_deactivate_user, "reset-password": cmd_reset_password,
        "list-companies": cmd_list_companies, "add-company": cmd_add_company,
        "update-company": cmd_update_company,
        "set-role": cmd_set_role,
    }
    fn = dispatch.get(args.command)
    if fn:
        fn(args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
