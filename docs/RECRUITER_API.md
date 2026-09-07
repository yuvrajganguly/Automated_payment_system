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
POST /auth/login          form: username=<email or phone>&password=<pw>&device=<"android <model>">
                          → {"access_token","token_type":"bearer","role","email","expires_in":43200,
                             "refresh_token":"qrt_…"}          (refresh_token only when device is sent)
POST /auth/refresh        {"refresh_token"} → same shape, NEW refresh_token (the old one is retired)
GET  /auth/me             → {"email","role","phone","zone"}
POST /auth/logout         {"refresh_token"}   revokes this phone's session
POST /auth/logout-everywhere                  revokes all of my sessions (needs a valid access token)
```

Send `Authorization: Bearer <access_token>` on every call (the cookie the
web console uses is not needed). The access token lasts 12 h; the app keeps
the **refresh token** in encrypted storage and calls `/auth/refresh` when a
request comes back 401 (or shortly before `expires_in` runs out). Every
refresh rotates the token — store the new one, discard the old. Presenting a
retired token again revokes every session of the account (a copy exists
somewhere), and the user must sign in again. Refresh tokens live 30 days from
issue; a password change, a creator "set password", "sign out everywhere" or
deactivation revokes them at once. The role is re-read from the database on
every request, so a role change takes effect immediately. Login and refresh
are rate-limited server-side.

A refresh that answers 401 means: clear stored tokens and show the sign-in
screen with the server's `detail` as the reason.

## Riders

```
GET   /app/bootstrap                      one call for first paint: me (incl. zone), active companies, hubs, hub_zones {hub: zone|null},
                                          zones ["North","South"], ev_models, counts, api_version
GET   /riders?company=&hub=&active=&q=&limit=&offset=&zone=&mine=&recruited_by=
                                          roster (rider_id, company, person_id, name, hub, vehicle, bank, phone, is_active,
                                          recruited_by, zone); q matches name / rider id / phone / hub;
                                          zone=North|South|unassigned (by the rider's hub); mine=1 → riders I onboarded;
                                          recruited_by=<email> → theirs (anyone may ask); X-Total-Count header = total before paging
GET   /persons/{person_id}/photo[?size=thumb]   the profile photo (thumb = 160 px JPEG for tiles); 404 = none
GET   /riders/{rider_id}?company=
POST  /riders                             {"company","name","rider_id"?,"hub"?,"vehicle"?,"account_no"?,"ifsc"?,"person_id"?}
                                          rider_id blank → placeholder QSPEND<NNNN>; person_id → attach to an existing person (2nd company)
PATCH /riders/{rider_id}?company=         any of {"name","hub","vehicle","account_no","ifsc","mob_no","is_active","new_rider_id","new_company"}
                                          ("recruited_by" and "salary" are admin-only)
POST  /riders/rename-rider-id             {"person_id","company","new_rider_id","current_rider_id"?}  — tag the real id; the QSPEND placeholder is retired
GET   /persons/{person_id}                person: display_name, riders[], ev (open), ev_history[]
GET   /companies                          company list (for the company picker)
```

`POST /riders` stamps `recruited_by` with the caller's email — that is what
"my riders" and the recruiting numbers are built on. A bank account already
owned by another person is refused with `409` naming the owner. Deleting riders, merging/splitting people and onboarding unknown
ids from payout files are admin-only.

## Zones, stores and the to-do list

```
GET   /hubs                               [{hub, zone, riders, evs}] — every hub seen on a rider row (+ pre-classified ones)
PUT   /hubs/{hub}                         admin: {"zone": "North"|"South"|null}   classify a store; null clears
PATCH /users/{email}/zone                 admin: {"zone": "North"|"South"|null}   the zone a recruiter works
GET   /app/todo?zone=                     what needs a visit, grouped by store, for one zone (default: my zone; "all";
                                          "unassigned" = stores with no zone yet)
                                          → {zone, my_zone, as_of, counts{cod_items, ev_dues_items, inactive_ev_items, total, stores},
                                             stores:[{hub, zone, items:[…]}]}
GET   /app/my-recruiting[?email=]         my onboarding numbers: counts{today, week, month, all_time, persons, active, ev_holders},
                                          by_company[], recent[] (email= is admin-only: another recruiter's)
GET   /app/recruiting                     every recruiter side by side (admins); a recruiter gets only their own row
```

To-do items are one visit each and carry `kind`:

* `cod` — the rider still holds COD (`cod_outstanding`). Collect it.
* `ev_dues` — an EV holder with rent arrears and/or general dues
  (`outstanding`, `dues_outstanding`, `total_dues`). Chase or take the unit.
* `inactive_ev` — a unit still with a rider who has no active rider id left
  (`ev_id`, `handover_date`). Pick it up.

Every item has `person_id`, `name`, `hub`, `companies`, `mob_no`, `ev_id`,
`ev_model` and a ready `title`. Amounts are rupees, like everywhere else.
Stores are ordered by how much is waiting at them. A recruiter with no
zone on their account sees every store, labelled with its zone.

### Where an action happened (Level 1 location)

The app may send `X-Client-Location: <lat>,<lng>[,<accuracy_m>]` on any
request. It is stamped onto the activity-log row of that action (rider
created, EV handed over, …) and nowhere else — there is no background
tracking and no location endpoint. Malformed or out-of-range values are
ignored, never rejected. Send it only on writes, only while the app is in
the foreground, and only after the user has granted location permission.

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
GET   /evs?status=&zone=&mine=                units with current rider/hub/handover, zone (holder's hub) and recruited_by;
                                              zone=North|South|unassigned; mine=1 → units held by riders I onboarded
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
