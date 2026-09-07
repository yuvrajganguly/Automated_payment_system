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
  data/db/              Room: riders cache (with recruited_by and zone for the filters)
  data/location/        AppOpenLocation (one fix per foreground, ≥30 min apart), header interceptor
  data/repo/            RiderRepository — read cached, write online; AppRepository — bootstrap
  ui/                   AppRoot (nav), SessionViewModel, home/ (tab shell), today/, riders/, evs/,
                        requests/, stats/, person/, login/, common/ (the kit), theme/
```

Look: "Modernist" from the saved Claude Design canvas (`Qwikserve Recruiter.html`
in this folder) — off-white ground, ink, one red accent, square corners, 2 px
rules, Archivo (bundled as static 400/600/800 TTFs in `res/font`). One theme,
no dark mode, by design.

Navigation: no drawer. Five tabs across the top — **Today** (things that need a
visit, grouped by store, for the recruiter's zone: COD to collect, EV holders
with dues, EVs to pick up from inactive riders), **Riders** (All riders with a
North/South zone filter, or My riders), **EVs** (All fleet by zone and state,
or My fleet with In use / Maintenance / Dues / Inactive), **Requests** (mine —
Money, and EVs asked for from the fleet desk), **My numbers** (today / week /
month / all-time onboardings, by company).

Start-up and diagnostics: the launcher is `LaunchActivity`, a plain Activity
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
phone pushes as a route.

Requests → EVs: "Ask for EVs" files `POST /ev-requests` with a count (chips,
1–10), the store and a one-line why. The zone is filled in server-side from
the store, else from the recruiter. An open request can be withdrawn; the
office fulfils or rejects it from the web Requests page.

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
