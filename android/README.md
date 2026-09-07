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
or My fleet with In use / Maintenance / Dues / Inactive), **Requests** (mine),
**My numbers** (today / week / month / all-time onboardings, by company).

Location ("Option 1"): each time the app comes to the foreground it takes one
fix, reverse-geocodes the area on the phone and posts it to `/app/location`;
the server keeps at most one row per 30 minutes. Writes also carry
`X-Client-Location` so the activity log knows where an action happened.
Nothing runs in the background.

Session: sign in once with email or phone; the app keeps a 30-day rotating
refresh token in encrypted storage and never asks again unless the server
revokes it (password changed, signed out everywhere, deactivated) — then the
sign-in screen shows the server's reason.
