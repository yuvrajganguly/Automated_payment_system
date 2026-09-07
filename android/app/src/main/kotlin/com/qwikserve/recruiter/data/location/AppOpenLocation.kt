package com.qwikserve.recruiter.data.location

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.location.Geocoder
import android.location.Location
import android.location.LocationManager
import android.os.Build
import android.os.Looper
import androidx.core.content.ContextCompat
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import com.qwikserve.recruiter.data.api.LocationIn
import com.qwikserve.recruiter.data.api.PayoutApi
import com.qwikserve.recruiter.data.auth.TokenStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import java.util.Locale
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.coroutines.resume

/**
 * "Option 1" tracking, as agreed: no background work at all. Each time the
 * app comes to the foreground (and the recruiter is signed in and has granted
 * location) it takes ONE fix, reverse-geocodes the area name on the phone and
 * posts it to `POST /app/location`. At most one post per 30 minutes — the
 * server enforces the same gap, this is only to save the request.
 *
 * The last fix is also kept in memory so that writes (onboard a rider, hand
 * over an EV) can carry `X-Client-Location` — the Level-1 stamp on the
 * activity log.
 */
@Singleton
class AppOpenLocation @Inject constructor(
    @ApplicationContext private val context: Context,
    private val api: PayoutApi,
    private val store: TokenStore,
    private val holder: LocationHolder,
) : DefaultLifecycleObserver {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val prefs = context.getSharedPreferences("location", Context.MODE_PRIVATE)

    fun install() {
        ProcessLifecycleOwner.get().lifecycle.addObserver(this)
    }

    override fun onStart(owner: LifecycleOwner) {
        recordNow(reason = "app_open")
    }

    /** Called from the UI right after permission is granted so the first open still counts. */
    fun recordNow(reason: String = "app_open") {
        if (!hasPermission() || store.accessToken == null) return
        scope.launch {
            val fix = currentLocation() ?: return@launch
            holder.lastFix = fix
            val last = prefs.getLong("last_post", 0L)
            val now = System.currentTimeMillis()
            if (now - last < MIN_GAP_MS) return@launch
            val area = areaName(fix)
            runCatching {
                val ack = api.location(
                    LocationIn(
                        lat = fix.latitude,
                        lng = fix.longitude,
                        accuracyM = if (fix.hasAccuracy()) fix.accuracy else null,
                        area = area,
                        source = reason,
                    ),
                )
                // Whether or not the server kept it, we are inside its gap now.
                prefs.edit().putLong("last_post", now).apply()
                ack
            }
        }
    }

    fun hasPermission(): Boolean =
        ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
            ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED

    /** One fresh fix (GPS or network), falling back to the last known one; null if nothing within 15 s. */
    @SuppressLint("MissingPermission")
    private suspend fun currentLocation(): Location? {
        val lm = context.getSystemService(Context.LOCATION_SERVICE) as? LocationManager ?: return null
        val providers = listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)
            .filter { runCatching { lm.isProviderEnabled(it) }.getOrDefault(false) }
        for (p in providers) {
            val fix = withTimeoutOrNull(15_000) {
                suspendCancellableCoroutine<Location?> { cont ->
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                        lm.getCurrentLocation(p, null, ContextCompat.getMainExecutor(context)) { loc ->
                            if (cont.isActive) cont.resume(loc)
                        }
                    } else {
                        @Suppress("DEPRECATION")
                        lm.requestSingleUpdate(
                            p,
                            { loc -> if (cont.isActive) cont.resume(loc) },
                            Looper.getMainLooper(),
                        )
                    }
                }
            }
            if (fix != null) return fix
        }
        return providers.firstNotNullOfOrNull { runCatching { lm.getLastKnownLocation(it) }.getOrNull() }
    }

    /** "Salt Lake, Kolkata" — best effort; null when the geocoder has nothing or no network. */
    private fun areaName(fix: Location): String? = runCatching {
        if (!Geocoder.isPresent()) return null
        @Suppress("DEPRECATION")
        val a = Geocoder(context, Locale("en", "IN")).getFromLocation(fix.latitude, fix.longitude, 1)
            ?.firstOrNull() ?: return null
        listOfNotNull(a.subLocality ?: a.thoroughfare, a.locality ?: a.subAdminArea)
            .filter { it.isNotBlank() }.distinct().joinToString(", ").ifBlank { null }
    }.getOrNull()

    companion object {
        const val MIN_GAP_MS = 30L * 60 * 1000
    }
}
