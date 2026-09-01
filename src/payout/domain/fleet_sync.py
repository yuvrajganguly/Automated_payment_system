"""Fleet-sync helpers: resolve_or_create_model + ingest_master_rows.

Two entry points share these helpers:

  * POST /api/providers/{provider}/master  — Raft / Blive tab upload.
  * The EV-register importer that runs inside the bulk payout upload —
    now uses the same resolver instead of rejecting unknown models.

Why centralize: the rate card has historically been a tight allowlist.
Operators get a master from Raft listing 68 EVs across three model
variants ("WARRIOR 2.0", "WARRIOR", "WARRIOR 2.O") — none of which are
on the seeded rate card — and the importer silently dropped all of them.
This module auto-creates missing ev_models entries, copying the rate
from any sibling model under the same provider so billing stays sane,
and normalises common typos (the capital-O in "2.O") so the fleet
doesn't fragment into spurious variants.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

# Default weekly rate when we have nothing to copy from. Flagged for review
# in the response so operators don't silently bill at the wrong amount.
_FALLBACK_WEEKLY_RATE = 125000  # paise


def normalize_model_name(name: str | None) -> str | None:
    """Tidy up vendor typos before we look up / create a model.

    * Strip whitespace, collapse multiple spaces.
    * Uppercase: model names are short identifiers, not prose.
    * Fix "2.O" → "2.0" (capital-letter-O where the digit zero belongs).
      Limited to the model-suffix pattern to avoid mangling unrelated names.
    """
    if not name:
        return None
    s = re.sub(r"\s+", " ", str(name).strip()).upper()
    # Common typo: "WARRIOR 2.O" → "WARRIOR 2.0". Only fix when an O follows
    # a digit-dot, which is the only place a real model number could be.
    s = re.sub(r"(\d)\.O\b", r"\1.0", s)
    return s or None


@dataclass
class ResolveResult:
    model_id: int
    created: bool
    weekly_rate: float
    flagged_rate: bool  # True when we fell back to _FALLBACK_WEEKLY_RATE.


def resolve_or_create_model(
    conn: sqlite3.Connection,
    provider: str,
    model_name: str | None,
) -> ResolveResult:
    """Find a model_id for (provider, model_name); create if missing.

    Rate strategy: copy from any existing model under the same provider
    (most common rate wins on tie). If the provider has no models yet,
    use _FALLBACK_WEEKLY_RATE and set flagged_rate=True so the caller
    can surface a "needs review" warning.
    """
    prov = (provider or "").strip()
    model = normalize_model_name(model_name)
    if not prov or not model:
        raise ValueError("provider and model_name are both required.")

    row = conn.execute(
        "SELECT model_id, weekly_rate FROM ev_models "
        "WHERE LOWER(provider)=LOWER(?) AND LOWER(model_name)=LOWER(?)",
        (prov, model),
    ).fetchone()
    if row:
        return ResolveResult(
            model_id=row["model_id"],
            created=False,
            weekly_rate=float(row["weekly_rate"]),
            flagged_rate=False,
        )

    # Copy rate from the provider's most-used existing model.
    sib = conn.execute(
        "SELECT m.weekly_rate, COUNT(u.ev_id) AS n FROM ev_models m "
        "LEFT JOIN ev_units u ON u.model_id=m.model_id "
        "WHERE LOWER(m.provider)=LOWER(?) "
        "GROUP BY m.model_id "
        "ORDER BY n DESC, m.model_id ASC LIMIT 1",
        (prov,),
    ).fetchone()
    if sib:
        rate, flagged = float(sib["weekly_rate"]), False
    else:
        rate, flagged = _FALLBACK_WEEKLY_RATE, True

    mid = conn.execute(
        "INSERT INTO ev_models (provider, model_name, weekly_rate) VALUES (?,?,?)",
        (prov, model, rate),
    ).lastrowid
    return ResolveResult(model_id=mid, created=True, weekly_rate=rate, flagged_rate=flagged)


@dataclass
class IngestRow:
    ev_id: str
    model_name: str | None


@dataclass
class IngestReport:
    units_added: int = 0
    units_updated: int = 0  # existing units that had their model corrected
    units_unchanged: int = 0
    skipped: list[dict] = field(default_factory=list)  # {row, reason}
    models_created: list[dict] = field(default_factory=list)
    # Model names whose rate was auto-set to the fallback (needs human review).
    rate_review_needed: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "units_added": self.units_added,
            "units_updated": self.units_updated,
            "units_unchanged": self.units_unchanged,
            "skipped": self.skipped,
            "models_created": self.models_created,
            "rate_review_needed": self.rate_review_needed,
        }


def ingest_master_rows(
    conn: sqlite3.Connection,
    provider: str,
    rows: list[IngestRow],
) -> IngestReport:
    """Upsert ev_units for a provider's fleet, auto-creating ev_models.

    Doesn't touch assignments (rider/EV pairings stay as they are) and
    doesn't retire EVs that are missing from the master — that would be
    destructive and we'd rather flag-and-confirm separately.
    """
    rep = IngestReport()
    seen_models: dict[str, ResolveResult] = {}
    for r in rows:
        ev_id = (r.ev_id or "").strip()
        if not ev_id:
            rep.skipped.append({"row": r.__dict__, "reason": "missing EV ID"})
            continue
        model = normalize_model_name(r.model_name)
        if not model:
            rep.skipped.append({"row": r.__dict__, "reason": "missing model"})
            continue

        if model not in seen_models:
            try:
                seen_models[model] = resolve_or_create_model(conn, provider, model)
            except Exception as exc:
                rep.skipped.append({"row": r.__dict__, "reason": str(exc)})
                continue
            if seen_models[model].created:
                rep.models_created.append(
                    {
                        "provider": provider,
                        "model_name": model,
                        "weekly_rate": seen_models[model].weekly_rate,
                        "needs_rate_review": seen_models[model].flagged_rate,
                    }
                )
                if seen_models[model].flagged_rate:
                    rep.rate_review_needed.append(model)

        mid = seen_models[model].model_id
        existing = conn.execute(
            "SELECT model_id FROM ev_units WHERE ev_id=?",
            (ev_id,),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO ev_units (ev_id, model_id, status) VALUES (?,?, 'spare')",
                (ev_id, mid),
            )
            rep.units_added += 1
        elif existing["model_id"] != mid:
            conn.execute(
                "UPDATE ev_units SET model_id=? WHERE ev_id=?",
                (mid, ev_id),
            )
            rep.units_updated += 1
        else:
            rep.units_unchanged += 1
    return rep
