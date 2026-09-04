# Recruiter API — what the Android app talks to

The recruiter app is a native client of the same FastAPI server the office
console uses. Nothing here is app-specific: every call works from curl, and
the office console (admin / creator) uses the same endpoints to review what
recruiters did.

Base URL: `https://<SITE_ADDRESS>/api`. All bodies are JSON unless noted.
Money is **rupees** at this boundary (the server keeps paise).

## Roles

```
creator > admin > recruiter > user
```

| role      | may                                                                 |
|-----------|---------------------------------------------------------------------|
| user      | read the office console (money included); write nothing            |
| recruiter | riders, hubs, bank details, documents, EVs (add/assign/return/spare/maintenance), money **requests**; sees no money |
| admin     | everything operational, incl. payouts, ledger, approving requests   |
| creator   | admin + users/roles + system; invisible below itself (shows as admin) |

A recruiter calling any money-side route (`/ledger`, `/arrears`, `/cod`,
`/payments`, `/dashboard`, `/cycles`, `/corrections`, `/inactive`,
`/ev-rent`, `/providers`) gets `403 {"detail": "Not permitted"}`.
`GET /persons/{id}` returns `current_balance` / `arrears_outstanding` as
`null` to a recruiter.

Accounts are created by the creator: `POST /users {"email","password","role":"recruiter"}`.

## Auth

```
POST /auth/login          form: username=<email or phone>&password=<pw>   (phone: 10 digits or +country code)
                          → {"access_token","token_type":"bearer","role","email"}
GET  /auth/me             → {"email","role"}
POST /auth/logout
```

Send `Authorization: Bearer <access_token>` on every call (the cookie the
web console uses is not needed). Tokens last 12 h; the role is re-read from
the database on every request, so a role change or deactivation takes effect
immediately. Login is rate-limited server-side.

## Riders

```
GET   /riders?company=&q=                 roster (rider_id, company, person_id, name, hub, vehicle, bank, is_active)
GET   /riders/{rider_id}?company=
POST  /riders                             {"company","name","rider_id"?,"hub"?,"vehicle"?,"account_no"?,"ifsc"?,"person_id"?}
                                          rider_id blank → placeholder QSPEND<NNNN>; person_id → attach to an existing person (2nd company)
PATCH /riders/{rider_id}?company=         any of {"name","hub","vehicle","account_no","ifsc","mob_no","is_active","new_rider_id","new_company"}
POST  /riders/rename-rider-id             {"person_id","company","new_rider_id","current_rider_id"?}  — tag the real id; the QSPEND placeholder is retired
GET   /persons/{person_id}                person: display_name, riders[], ev (open), ev_history[]
GET   /companies                          company list (for the company picker)
```

A bank account already owned by another person is refused with `409` naming
the owner. Deleting riders, merging/splitting people and onboarding unknown
ids from payout files are admin-only.

## Documents (KYC)

```
GET    /documents/types                       {"doc_types":[aadhaar,pan,driving_licence,bank_proof,photo,agreement,other],
                                               "content_types":[application/pdf,image/jpeg,image/png,image/webp],"max_bytes"}
GET    /persons/{person_id}/documents         [{id,doc_type,filename,content_type,size_bytes,notes,uploaded_by,uploaded_at}]
POST   /persons/{person_id}/documents         multipart/form-data: file, doc_type, notes?   → 201 document
GET    /documents/{doc_id}/download           the bytes (Content-Disposition: inline)
DELETE /documents/{doc_id}                    admin: any; recruiter: only their own uploads
```

Documents hang off the **person**, not the rider id, so one set of papers
covers every company the person rides for. Files are stored under opaque
keys (local volume or an S3/R2 bucket — server config, invisible to the app).

## EVs

```
GET   /evs                                    units with current rider/hub/handover
GET   /evs/{ev_id}/profile                    unit + assignment history + maintenance
GET   /evs/models                             provider/model rate card
POST  /evs                                    {"ev_id","provider","model","notes"?,"person_id"?,"handover_date"?}  — with person_id the unit is handed over in the same call
POST  /evs/assign                             {"ev_id","person_id"} or {"ev_id","rider_id","company"} (+ "handover_date"?)
POST  /evs/return                             {"ev_id"} or {"rider_id","company"} (+ "returned_date"?)  — retire to provider; works for in-use or spare
POST  /evs/to-spare                           same body — take back into the pool; on a RETURNED unit brings it back as spare
GET   /evs/maintenance                        log
POST  /evs/maintenance                        {"ev_id","from_date","to_date"?,"reason"?}   → unit status 'maintenance'
PATCH /evs/maintenance/{id}                   {"to_date"?}  — close the window; unit goes back to in_use / spare
```

`amend-return`, `backrent` and everything that changes money stay admin-only.

## Money requests (the recruiter's only money action)

```
POST /requests                     {"person_id","direction":"credit"|"debit","amount":<rupees>,"reason"}  → 201 request (status "open")
GET  /requests?status=&person_id=  recruiter: own requests; admin: all. Open first.
GET  /requests/summary             {"open": n}   (recruiter: own open count)
POST /requests/{id}/approve        admin — {"amount"?: <rupees override>, "note"?}  posts the ledger adjustment
POST /requests/{id}/reject         admin — {"note"?}
```

Approving posts an `ADJUSTMENT` on the person's ledger whose remark names
the request and the recruiter; a credit also settles EV arrears automatically.

## Activity (admins reviewing recruiters)

```
GET /activity?email=&entity_type=&action=&person_id=&since=&limit=
    admin/creator: everything; recruiter: their own rows only
    → [{id, at, email, role, action, action_label, entity_type, entity_id, entity_label, person_id, details}]
GET /activity/people        [{email, role, actions, last_at}]
GET /activity/actions       {action: label}
```

Actions: `rider.create rider.update rider.rename rider.link rider.delete
person.merge ev.create ev.assign ev.return ev.spare ev.maintenance_open
ev.maintenance_close document.upload document.delete request.create
request.approve request.reject`. `details` is a small JSON object — for
`rider.update` it is `{"changed": {"hub": ["old", "new"], …}}`.

## Errors

Standard FastAPI shape: `{"detail": "…"}`. `401` = not signed in / token
expired, `403` = role not allowed, `404` = no such thing, `409` = would
double-book (EV already assigned, bank account owned elsewhere, request
already resolved), `413` / `415` = document too big / wrong type, `422` =
body validation.
