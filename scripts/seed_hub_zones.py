"""One-off: classify the stores on the live roster into zones (2026-09-07).

Run on the server after deploying migration 0018+:

    cd /root/payout && PYTHONPATH=src python3 scripts/seed_hub_zones.py

Idempotent — sets the zone on every (company, hub) whose hub name matches
(case-insensitively) an entry below; leaves everything else untouched and
prints what it did. The list is what the operator answered in chat; hub
spellings are kept exactly as the roster has them because company files
re-sync the roster hub every cycle.
"""

from __future__ import annotations

from payout.db import get_connection

ZONES: dict[str, str] = {
    # South
    "Acropollis Mall": "South",
    "Alipore": "South",
    "Avisar": "South",
    "Behala_mnow": "South",
    "Gariahat Super": "South",
    "Hazra": "South",
    "Hazra Super": "South",
    "Maheshtala": "South",
    "Marlin, Tolly DS": "South",
    "MVT Kasba(SS)": "South",
    "MVT Maheshtala(SS)": "South",
    "MVT Nagar Bazar(SS)": "South",
    "MVT New Alipore(SS)": "South",
    "Quest Mall Hyper": "South",
    "Rajpur_mnow": "South",
    "Rashbihari Hyper": "South",
    "Raynagar": "South",
    "Raynagar Daily": "South",
    "South City": "South",
    "Springdale": "South",
    "Sucasa Narendrapur": "South",
    "Tolly DS": "South",
    "UPAHAR": "South",
    # North
    "Axis Hyper": "North",
    "B. T. Road": "North",
    "Barasat Super": "North",
    "BARRACKPORE SUPER": "North",
    "Belur": "North",
    "DLF": "North",
    "Dum Dum": "North",
    "Dum dum_mnow": "North",
    "Dum dum_MNOW": "North",
    "Dumdum": "North",
    "Laketown Super": "North",
    "Madhyamgram": "North",
    "Mani Square": "North",
    "MEENA ICON": "North",
    "MVT Chinar Park(SS)": "North",
    "MVT Kalyani(SS)": "North",
    "MVT Nirodhe(SS)": "North",
    "New town Mnow": "North",
    "NTS": "North",
    "Ramrajatala Daily": "North",
    # Misc (outside Kolkata, or not a real store)
    "Bhelupur": "Misc",
    "Bhojuveer": "Misc",
    "City Centre, Siliguri": "Misc",
    "Gorakhpur": "Misc",
    "Gorakhpur Padri bazaar": "Misc",
    "Padri Bazar": "Misc",
    "Missing": "Misc",
    "Senpura Super": "Misc",
    "Sigra": "Misc",
}


def main() -> None:
    wanted = {k.lower(): v for k, v in ZONES.items()}
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT company, hub FROM rider_master WHERE hub IS NOT NULL AND hub<>'' "
            "UNION SELECT company, hub FROM company_hubs"
        ).fetchall()
        done, skipped = [], []
        for r in rows:
            zone = wanted.get(str(r["hub"]).strip().lower())
            if not zone:
                skipped.append(f"{r['hub']} ({r['company']})")
                continue
            if conn.execute(
                "SELECT 1 FROM company_hubs WHERE company=? AND hub=?", (r["company"], r["hub"])
            ).fetchone():
                conn.execute(
                    "UPDATE company_hubs SET zone=?, updated_at=datetime('now'), "
                    "updated_by='seed_hub_zones' WHERE company=? AND hub=?",
                    (zone, r["company"], r["hub"]),
                )
            else:
                conn.execute(
                    "INSERT INTO company_hubs (company, hub, zone, updated_by) VALUES (?,?,?,?)",
                    (r["company"], r["hub"], zone, "seed_hub_zones"),
                )
            done.append(f"{r['hub']} ({r['company']}) → {zone}")
        conn.commit()
    print(f"classified {len(done)} store(s):")
    for d in done:
        print("  " + d)
    if skipped:
        print(f"left unassigned ({len(skipped)}):")
        for s_ in skipped:
            print("  " + s_)


if __name__ == "__main__":
    main()
