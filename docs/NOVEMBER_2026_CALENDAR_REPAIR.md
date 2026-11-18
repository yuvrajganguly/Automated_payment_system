# November 2026 payout calendar repair

This maintenance changes cycle reporting and company metadata. It does not post
adjustments, recompute payouts, change balances or arrears, or rewind rent meters.
The original financial entries remain available in Transactions. Reporting uses
`reporting_transactions` to exclude duplicate windows and display corrected dates.
Corrections apply only to entries that existed when the repair ran.

## Verified duplicate windows

- Jiffy: 8 November repeats all 236 gross payouts from 1–7 November.
- Myntra: 12–13 October repeats all 78 gross payouts from 5–11 October.
- Myntra: 21 October repeats 68 gross payouts from 14–20 October.

The repair verifies the per-person amounts again before removing these run
summaries. Original summary rows are recorded in the activity log. The ledger
and financial state remain available for the operator's manual reconciliation.

## Corrected calendar

The retained Blitz runs resume consecutive Sunday–Saturday weeks from
4–10 October through 1–7 November. The retained Myntra runs resume consecutive
Monday–Sunday weeks from 12–18 October through 2–8 November. Jiffy ends on
7 November. Next starts are 8 November for Jiffy/Blitz and 9 November for Myntra.

## Company consolidation

Kaptan's parser configuration becomes Blitz. Nykaa IDs join the same company;
matching real IDs collapse only when their person IDs agree. Temporary IDs are
retired into that person's real ID through the placeholder helper, never by
merging unrelated people. Shared historical cycle summaries are combined, with
both original summaries archived in the activity log. Startup seeding does not
recreate Nykaa or Kaptan after consolidation.

## Runbook

1. Take and verify a `pg_dump -Fc` backup outside the repository.
2. Use the deployed environment and current package source to run
   `python scripts/repair_november_calendar.py --dry-run`.
3. Inspect the result. The verified incident plan reports 12 calendar changes,
   2 companies consolidated, 17 duplicate roster rows collapsed, and
   `money_unchanged: true`.
4. Run `python scripts/repair_november_calendar.py --apply --backup PATH`.
5. Verify company names, next-cycle dates, roster uniqueness and API health.

The script runs pending migrations in the repair transaction, locks the relevant
PostgreSQL tables against concurrent writes, compares financial fingerprints,
and commits only if they match. Dry runs roll back. Repeating a successful repair
is a no-op. Use an image that includes migration 0042 and the reporting readers.
