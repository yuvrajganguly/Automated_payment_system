# Qwikserve Recruiter — Android

Native Android client (Kotlin + Jetpack Compose) of the payout server, for
recruiters: find and onboard riders, hand over and take back EVs, file
credit/debit requests. Scope and decisions: `claude/APP_PLAN_2026-09-06.md`
in the project; API contract: `../docs/RECRUITER_API.md`.

## Build

CI builds `app-debug.apk` on every push (Actions → the run → Artifacts).
Locally: open `android/` in Android Studio (Ladybug or newer, JDK 17) — it
creates the Gradle wrapper on first sync — and run on a device or emulator.
The debug build talks to `https://app.qwikserve.in/api/`; change
`API_BASE_URL` in `app/build.gradle.kts` to point at a local server
(`http://10.0.2.2:8000/api/` from the emulator is allowed by the debug
network config).

Code lives under `com.qwikserve.recruiter` (Kotlin allows a package named `in`, but the
annotation processors do not resolve imports through it); the installed app id is still
`in.qwikserve.recruiter`.

## Layout

```
app/src/main/kotlin/com/qwikserve/recruiter/
  QwikApp.kt            Hilt application; Coil uses the API's OkHttp client (photos need the token)
  MainActivity.kt       splash → edge-to-edge → AppRoot
  di/AppModule.kt       Json, OkHttp (auth interceptor + refresh authenticator), Retrofit, Room
  data/api/             wire models (kotlinx.serialization) + Retrofit interface
  data/auth/            TokenStore (EncryptedSharedPreferences), AuthInterceptor, TokenAuthenticator
  data/db/              Room: riders cache (recruited_by, zone, working and last_worked_on —
                        every Riders-tab filter reads the cache, so all of them work offline)
  data/location/        AppOpenLocation (one fix per foreground, ≥30 min apart), header interceptor
  data/repo/            RiderRepository — read cached, write online; AppRepository — bootstrap;
                        PhotoRepository — shrink once, upload anywhere (rider, recruiter, dash)
  ui/                   AppRoot (nav), SessionViewModel, home/ (tab shell), today/, riders/, evs/,
                        requests/, stats/, person/, profile/, login/, common/ (the kit), theme/
```

Look: "Modernist" from the saved Claude Design canvas (`Qwikserve Recruiter.html`
in this folder) — off-white ground, ink, one red accent, square corners, 2 px
rules, Archivo (bundled as static 400/600/800 TTFs in `res/font`). One theme,
no dark mode, by design.

Navigation: no drawer. Six tabs across the top — **Today** (today's odometer,
then the things that need a visit, grouped by store, for the recruiter's zone:
COD to collect, EV holders with dues, EVs to pick up from inactive riders),
**Riders** (All riders with a North/South zone filter, or My riders, and an
All / Working / Idle filter over both), **EVs** (All fleet by zone and state,
or My fleet with In use / Maintenance / Dues / Inactive), **Requests** (mine —
Money, and EVs asked for from the fleet desk), **My numbers** (today / week /
month / all-time onboardings, by company, week by week and month by month),
**Profile** (the recruiter's own record).

Working or idle: the server calls a rider **working** when a paysheet company
has paid them for a cycle that ended within the last twelve days, and sends
`working` and `last_worked_on` on every rider row. Both are cached with the
rest of the roster, so the filter and the "last worked 4 Sep" line on each row
work with no signal, exactly like the zone and Mine/All ones. A rider nobody
has ever paid reads "never worked" rather than showing an empty space.

A rider's page ends with their **timeline** — `GET /app/person/{id}/timeline`,
newest first: added, EV handed over, taken back, sent for repair, brought back,
deposit closed out, return date amended, document uploaded. It is the console's
activity log scoped to one person rather than to one operator, so it shows
every hand that touched them and not only this recruiter's own rows. It loads
and fails separately from the rest of the page: no history is a missing
section, not a missing rider.

My numbers: the count tiles are doors. Tapping one lists the riders behind it,
each flagged working or idle with the date a company last paid them, filtered
All / Working / Idle from `GET /recruiters/me/riders`. Under them,
`GET /recruiters/me/series` draws twelve weeks or twelve months with
`still_working` alongside `onboarded` on every bar — retention is the point of
the screen, and a cohort figure ("of the riders you signed up that week, how
many are working now") is the only one the ledger can answer honestly.

Start-up and diagnostics: the app reports its own start-up failures to
`POST /app/crash` — from the uncaught-exception handler, and at the next start
when the previous run never drew a frame (that one catches the deaths with no
exception). A copy lands in `Android/data/<package>/files/qwikserve-startup.txt`
for a phone with no signal. The launcher is `LaunchActivity`, a plain Activity
with no Hilt, no Compose and no theme of ours — whatever else breaks on a phone
we have never seen, that one still opens. `CrashLog` (installed from
`QwikApp.attachBaseContext`, the earliest point the app owns) writes a
breadcrumb per start-up step and catches uncaught exceptions; a run that never
reaches `ui.first_frame` makes the next launch show the trail and the stack
trace as plain selectable text, with Copy. There is no logcat on a recruiter's
phone in a store, so the app has to be able to say what happened to it.

Phone and tablet, one app (`ui/common/Layout.kt`): under 600 dp everything is
full width, exactly as before. From 600 dp (a tablet held upright) the page is
centred in a 720 dp column so lines stay readable, forms in 520 dp. From
900 dp (a tablet on its side) the tab strip becomes a **rail** down the left
with New rider and Sign out at its foot, the list keeps a phone-ish 400–440 dp,
and tapping a rider opens their profile in a **second pane** beside it instead
of covering the list — `PersonScreen(embedded = true)`, the same screen the
phone pushes as a route. Profile is the exception: it is nobody else's page, so
on a wide screen it takes the whole width instead of standing beside an empty
second pane.

Requests → EVs: "Ask for EVs" files `POST /ev-requests` with a count (chips,
1–10), the store and a one-line why. The zone is filled in server-side from
the store, else from the recruiter. An open request can be withdrawn; the
office fulfils or rejects it from the web Requests page.

Onboarding: the company is a **dropdown**, and it starts empty. It used to be a
chip row that pre-selected whichever company happened to be first, which is a
default masquerading as a decision — a rider signed to the wrong company is an
office correction later. Nothing is picked until somebody picks it, and the
form refuses to save without one.

Odometer: the top of Today is the shift card — "Start your shift" with a number
field and a tile for the dash photo, then the opening reading once it is saved,
then "End your shift", then the day's distance. **The reading is saved first
and the photo goes up after**, the same order the onboarding form uses: the
number is the claim and the picture is only the evidence for it, and a failed
upload on one bar of signal must never cost somebody the number. When an upload
does fail the card says so and offers a retry — the reading is already on the
server, so nobody types it twice. Readings are whole kilometres (number pad,
non-digits dropped as you type). The server's soft doubts come back in
`warnings` — an opening below yesterday's close, because vehicles get swapped —
and they are shown as a notice beside a red rule, never as a refusal.

Profile: the recruiter as a subject rather than as an operator — their photo
(`/recruiters/me/photo`, the same shrink-then-upload path as a rider's), their
details, their password, and their odometer history. The details save **section
by section** (Personal / Bank / Identity), because the profile PATCH writes only
the fields it is sent: a bad signal should cost one card, not nine
fields. The server validates Aadhaar, PAN, IFSC and the account number
and answers 400 with a plain sentence; the app reads which field the sentence
is about and shows it there instead of at the top of the screen where nobody
looks. Changing the password needs eight characters and signs out every other
session — the screen says so before the button, not after. The history is the
last 30 days day by day and the last 12 months in total, with the days nobody
closed flagged: the month is what the fuel claim is paid on, and it should
never be quietly short by a day somebody forgot to end.

Photos: the onboarding form opens with a photo tile, a rider's page has the
same tile, and so do the shift card and the Profile tab — tap for Camera or
Gallery. Neither needs a runtime permission
(the app never declares CAMERA, so `ACTION_IMAGE_CAPTURE` just works; the
picture picker hands back one image). `PhotoRepository` turns the camera's
4–6 MB into ~200 kB (1 280 px, JPEG 80, EXIF rotation applied) before
`POST /persons/{id}/documents` with `doc_type=photo` — a recruiter is usually
on the edge of a signal. On the form the upload happens after the rider is
created, since the photo hangs off their person id; if it fails the rider is
still saved and the note says to add it from their page.

EV actions: the EVs tab has "New unit" at its foot (a vehicle that arrives for
the fleet joins as a spare), and tapping a unit opens what can be done with it
in its state — in use: take back as a spare, return to the provider, send for
repair; spare or returned: give it to a rider (search), send for repair; in
maintenance: back in service. A rider's page has the same from the other side:
"Give an EV" lists the free units — or, on its "New unit" tab, creates the
vehicle and hands it over in the same call, for the one that arrived with the
rider standing next to it. A held one can be taken back either way. The rules stay on the server (one open assignment per person, rent stops
on the return date, the deposit close-out is an admin's job) — the app asks
and reports the answer in a sentence.

Location ("Option 1"): each time the app comes to the foreground it takes one
fix, reverse-geocodes the area on the phone and posts it to `/app/location`;
the server keeps at most one row per 30 minutes. Writes also carry
`X-Client-Location` so the activity log knows where an action happened.
Nothing runs in the background.

Session: sign in once with email or phone; the app keeps a 30-day rotating
refresh token in encrypted storage and never asks again unless the server
revokes it (password changed, signed out everywhere, deactivated) — then the
sign-in screen shows the server's reason. Accounts are made by an admin who
hands over the first password; "Forgot password?" on the sign-in screen emails
a six-digit code (`/auth/forgot-password` → `/auth/reset-password`), good for
ten minutes.

Icon and splash: the Qwikserve mark (red winged Q) on white — adaptive
foreground in `mipmap-*/ic_launcher_foreground.png`, legacy icons composited
on white, `drawable-xxxhdpi/splash_logo.png` for the cold-start window and
`qwik_logo.png` above the sign-in wordmark. All generated from
`frontend/public/icon-512.png` with the black ground keyed out.
