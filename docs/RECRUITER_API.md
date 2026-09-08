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

### Forgotten password (emailed code)

Accounts are created by an admin, who hands over the first password. When a
recruiter forgets it, the app asks the server for a one-time code instead of
routing it through the office:

```
POST /auth/forgot-password   {"email": "<email or phone>"} → {"ok": true, "message": …}
POST /auth/reset-password    {"email", "otp": "123456", "new_password"} → {"ok": true, …}
```

The code is six digits, lives 10 minutes, dies after five wrong guesses, and
always goes to the account's **email** (a phone number is accepted on the
first call and resolved to that address). The answer to `forgot-password` is
identical for known and unknown accounts — don't tell the user whether the
address exists. A successful reset revokes every session of that account, so
the app must sign in again. Both routes are rate-limited per IP, and a server
without SMTP configured answers 503 with a message pointing at the admin.

## Riders

```
GET   /app/bootstrap                      one call for first paint: me (incl. zone), active companies, hubs, hub_zones {hub: zone|null},
                                          company_hubs [{company,hub,zone}], zones ["North","South","Misc"], ev_models, counts, api_version
GET   /riders?company=&hub=&active=&q=&limit=&offset=&zone=&mine=&recruited_by=
                                          roster (rider_id, company, person_id, name, hub, vehicle, bank, phone, is_active,
                                          recruited_by, zone); q matches name / rider id / phone / hub;
                                          zone=North|South|Misc|unassigned (by the rider's store); mine=1 → riders I onboarded;
                                          recruited_by=<email> → theirs (anyone may ask); X-Total-Count header = total before paging
GET   /persons/{person_id}/photo[?size=thumb]   the profile photo (thumb = 160 px JPEG for tiles); 404 = none
GET   /riders/{rider_id}?company=
POST  /riders                             {"company","name","rider_id"?,"hub"?,"vehicle"?,"account_no"?,"ifsc"?,"mob_no"?,
                                           "aadhaar_no"?,"pan_no"?,"person_id"?,"allow_duplicate_name"?,"referred_by_person_id"?}
                                          rider_id blank → placeholder QSPEND<NNNN>; person_id → attach to an existing person (2nd company);
                                          referred_by_person_id → records a referral (response carries "referred_by": the referrer's name)
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
GET   /hubs?company=                      [{company, hub, zone, per_order_rate, salary, incentive_per_order, incentive_per_day,
                                           notes, is_active, riders, evs, payment_model}] — every store per company
PUT   /hubs/{company}/{hub}               admin: any of {"zone": North|South|Misc|null, "per_order_rate", "salary",
                                          "incentive_per_order", "incentive_per_day", "notes", "is_active"} (rupees)
POST  /companies                          …accepts "hubs": [{"hub","zone"?}] to create a company's stores with it
PATCH /users/{email}/zone                 admin: {"zone": "North"|"South"|null}   the zone a recruiter works
GET   /app/todo?zone=                     what needs a visit, grouped by store, for one zone (default: my zone; "all";
                                          "unassigned" = stores with no zone yet)
                                          → {zone, my_zone, as_of, counts{cod_items, ev_dues_items, inactive_ev_items, total, stores},
                                             stores:[{hub, zone, items:[…]}]}
GET   /app/my-recruiting[?email=]         my onboarding numbers: counts{today, week, month, all_time, persons, active, ev_holders},
                                          by_company[], recent[] (email= is admin-only: another recruiter's)
GET   /app/recruiting                     every recruiter side by side (admins); a recruiter gets only their own row
```

A rider's `zone` is the hub's zone when the hub has one, else the zone of
the recruiter who onboarded them (`users.zone`) — so hub-less riders (Blitz
and co.) follow their recruiter. `?zone=unassigned` (alias `misc`) is the
rest. In the to-do list, hub-less riders sit under a store called "Misc".

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

### Where the recruiter is (app-open location)

```
POST /app/location        {"lat","lng","accuracy_m"?,"area"?,"source"?="app_open"}
                          → {"recorded": true|false, "last_at", "next_after"}
GET  /app/locations?email=&since=&limit=   my trail (newest first); email= is admin-only
```

Every time the app comes to the foreground it takes one fix and posts it
here with the phone's reverse-geocoded `area` ("Salt Lake, Kolkata").
The server keeps **at most one row per 30 minutes per account** — a post
inside the gap answers `recorded: false` with `next_after`, so the app need
not keep its own timer (it may, to save a request). There is no background
collection: no service, no periodic job, nothing while the app is closed.

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

The app puts these behind one tap on a unit: an in-use unit offers "take back
— spare", "take back — return to the provider" and "send for repair"; a spare
or returned unit offers "give it to a rider" (with a rider search) and
"send for repair"; a vehicle that is not in the system yet is created and
handed over in one call with `POST /evs {ev_id, provider, model, person_id}`; a unit in maintenance offers "back in service", which
closes its open window. A rider's page has the same actions from the other
side — "Give an EV" lists the free units.

## Referrals

```
GET   /referrals?person_id=&status=&mine=     referrals (either side of person_id; mine=1 → ones I recorded)
POST  /referrals                              {"new_person_id","referrer_person_id","company"?,"note"?}  → 201; 409 if the rider already has one
GET   /referrals/rules                        {qualify_days:28, bonus:1000, installments:2, installment_amount:500, text}
POST  /referrals/{id}/void                    admin: cancel (what was paid stays)
```

Once the new rider has worked four weeks (28 days from onboarding, still
active, at least one payout received) the referrer gets ₹1,000 in two ₹500
instalments — the first in the referrer's payout processed after the month
is reached, the second in the next. The payout engine pays them; the app
only records who referred whom.

## EV close-out (web, admins)

When an EV comes back from a rider (`/evs/return`, `/evs/to-spare`) the
response carries `closeout` and the assignment stays `closeout_pending`
until an admin answers on the web (`GET /evs/closeouts`, `POST
/evs/closeouts/{assignment_id}`): was the security deposit returned; if not,
the deposit held (₹2,700), damage and rent charges, and whether the leftover
goes into the rider's next payout. Recruiters never see money here; they
just return the unit.

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

## EV requests (asking the fleet desk for vehicles)

```
POST /ev-requests                  {"quantity": 1..25, "hub"?, "company"?, "note"?}  → 201 request (status "open")
GET  /ev-requests?status=&zone=    recruiter: own requests; admin: all. Open first.
GET  /ev-requests/summary          {"open": n, "units": n}   (recruiter: own)
POST /ev-requests/{id}/fulfil      admin — {"quantity"?: <units actually given>, "note"?}
POST /ev-requests/{id}/reject      admin — {"note"?}
POST /ev-requests/{id}/cancel      the recruiter who filed it (or an admin) withdraws it
```

`quantity` is a count of vehicles, not money — nothing here is rupeeized and
nothing touches the ledger. The `zone` is filled in from the store's zone if
the store is classified, else from the recruiter's own zone, so the fleet
desk can read the queue North/South. Fulfilling only closes the ask; the
units are still handed over on the EV pages as usual.

## Crash reports from the app

```
POST /app/crash     no auth — {"version","device","android","kind":"crash"|"trail","trail","detail"}  → 201 {"id","stored"}
GET  /app/crashes   admin — newest first
```

There is no logcat on a recruiter's phone, so the app reports its own
start-up failures. It posts on two occasions: from the uncaught-exception
handler (blocking, a few seconds, before the process dies), and at the next
start when the previous run never drew a frame — that second one is what
catches deaths with no exception at all. Unauthenticated because the crash
usually happens before anyone can sign in; fields are capped, the route is
rate-limited per IP and write-only.

## Live console (the change cursor)

```
GET /activity/changes[?since=<cursor>]   → {"cursor": <last activity id>, "changed": ["rider","ev",…]}
```

One indexed read, polled by the web console every 3 seconds while something is
happening and its tab is visible, backing off to 10 s after two quiet minutes
and 30 s after ten (any change, or the tab coming back to the front, makes it
eager again). When the cursor moves, the pages reload themselves — a rider
onboarded from a phone shows up in the office within seconds instead of at the
next manual refresh, which is what stops the same rider being onboarded twice.
`changed` lists the entity types touched since the cursor you sent, so a page
can ignore what it does not show.

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
request.approve request.reject ev_request.create ev_request.fulfil
ev_request.reject ev_request.cancel ev.amend_return ev.closeout
ev.suspected_return.dismiss ev.suspected_return.undismiss person.identity
company.create company.update profile.update shift.start shift.end`.
`details` is a small JSON object — for `rider.update` it is
`{"changed": {"hub": ["old", "new"], …}}`. Bank and identity fields appear
there as the fact that they changed, never as values.

## The recruiter as a subject

Profile, odometer and per-recruiter numbers, all under `/recruiters`. `me` is
an alias for the signed-in caller everywhere an `{email}` appears, so the app
uses one URL shape and an admin uses the same one with a name in it.

```
GET   /recruiters/me/profile
        → {email, full_name, display_name, phone, address, account_name,
           account_no, ifsc, bank_name, aadhaar_no, pan_no, role, zone,
           is_active, has_photo, updated_at, masked}
PATCH /recruiters/me/profile      {full_name?, phone?, address?, account_name?,
                                   account_no?, ifsc?, bank_name?, aadhaar_no?, pan_no?}
GET   /recruiters/{email}/profile  full for the recruiter and for an admin;
                                   masked (••••1234) for anyone else
POST  /recruiters/me/photo         multipart `file` (jpeg/png/webp, ≤8 MB)
GET   /recruiters/{email}/photo    the picture; any signed-in member of staff
```

Only the fields you send are written, so the app saves one section at a time
and a failed save on a weak signal costs one section rather than the form.
Aadhaar, PAN, IFSC and account number are normalised and validated server-side;
a bad one comes back as `400` with a sentence to put against the field. The
values never appear in the activity feed or the audit log — the feed records
*which* fields changed, and the audit middleware scrubs the request body.

### Odometer

```
GET  /recruiters/me/shift/today
       → {id, email, day, start_km, end_km, distance_km, start_at, end_at,
          has_start_photo, has_end_photo, note, complete}
POST /recruiters/me/shift          {kind: "start"|"end", km, day?, note?}
       → the same shape, plus {warnings: [str]}
POST /recruiters/me/shift/photo?kind=start|end&day=YYYY-MM-DD   multipart `file`
GET  /recruiters/{email}/shift/photo?kind=&day=
GET  /recruiters/{email}/shifts?days=30
       → {email, since, days: [...], total_km, days_recorded, average_km, incomplete: [day]}
GET  /recruiters/{email}/shifts/monthly?months=12
       → {email, months: [{month, km, days_recorded, days_open}]}
```

Whole kilometres — that is what a dash reads. One row per (email, day):
re-sending a reading corrects it rather than adding a second. Save the reading
first and upload the photo after; the number is the claim and the photo is the
evidence, and a failed upload on a hub's signal must not lose the number.

A closing reading below the opening one is refused, and the comparison is
repeated inside the UPDATE so two saves racing cannot leave a negative
distance behind. A *opening* reading below yesterday's close only warns —
vehicles get swapped and serviced, and blocking the shift would leave a
recruiter unable to record their day. A day with only one reading counts as
zero and is reported in `days_open`, so a month's total is never quietly short
by a day somebody forgot to close.

### Numbers

```
GET /recruiters?days=30                    admin only — every recruiter, best first
      → {since, window_days, active_within_days,
         recruiters: [{email, name, zone, is_active, has_photo,
                       onboarded_all_time, onboarded_recent, onboarded_month,
                       still_working, retention_pct, evs_deployed,
                       evs_deployed_recent, km_this_month}]}
GET /recruiters/{email}/series?grain=day|week|month&buckets=12
      → {email, grain, active_within_days,
         series: [{bucket, onboarded, still_working, evs_deployed, km}], totals}
GET /recruiters/{email}/riders?status=all|working|idle
GET /recruiters/{email}/evs                every EV they handed over
```

`still_working` is a **cohort** number: of the riders signed up in that bucket,
how many are working now. It is not "how many were working then" — the ledger
cannot answer that retrospectively without replaying every cycle.

## Working and idle riders

A rider is **working** when a company that sends us a paysheet
(`payment_model='payout_file'`) paid them for a cycle that ended within the
last 12 days (`payout/domain/worked.py`). `GET /riders` takes
`activity=all|working|idle` and every rider row carries `working` and
`last_worked_on`.

Two things worth knowing before quoting the number. It measures the end of the
last paid cycle, not a payment date, so a company whose cycle has not been run
for a fortnight makes all of its riders read idle — we know when we last paid
someone, not when they last rode. And riders at `direct` or `per_order`
companies (Elastic, Zomato, Shadowfax, Pidge, Delhivery) are structurally never
"working", because we never see whether they worked.

## A rider's timeline

```
GET /app/person/{person_id}/timeline?limit=100
      → [{id, at, email, role, action, action_label, entity_type, entity_id,
          entity_label, details, lat, lng}]
```

Everything that has happened to one rider, newest first: added, edited, EV
handed over, returned, sent for repair, brought back, closed out, documents,
referrals. Unlike `/activity`, which confines a recruiter to rows they wrote
themselves, this shows every hand that touched the rider — a timeline that hid
a colleague's handover would lie by omission.

## Errors

Standard FastAPI shape: `{"detail": "…"}`. `401` = not signed in / token
expired, `403` = role not allowed, `404` = no such thing, `409` = would
double-book (EV already assigned, bank account owned elsewhere, request
already resolved), `413` / `415` = document too big / wrong type, `422` =
body validation.
