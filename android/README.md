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

## Layout

```
app/src/main/kotlin/in/qwikserve/recruiter/
  QwikApp.kt            Hilt application; Coil uses the API's OkHttp client (photos need the token)
  MainActivity.kt       splash → edge-to-edge → AppRoot
  di/AppModule.kt       Json, OkHttp (auth interceptor + refresh authenticator), Retrofit, Room
  data/api/             wire models (kotlinx.serialization) + Retrofit interface
  data/auth/            TokenStore (EncryptedSharedPreferences), AuthInterceptor, TokenAuthenticator
  data/db/              Room: riders cache
  data/repo/            RiderRepository — read cached, write online
  ui/                   AppRoot (nav), SessionViewModel, login/, riders/, person/, common/, theme/
```

Session: sign in once with email or phone; the app keeps a 30-day rotating
refresh token in encrypted storage and never asks again unless the server
revokes it (password changed, signed out everywhere, deactivated) — then the
sign-in screen shows the server's reason.
