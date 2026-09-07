package com.qwikserve.recruiter.data.location

import android.location.Location
import java.util.Locale
import javax.inject.Inject
import javax.inject.Singleton

/**
 * The last fix this process took. Kept apart from [AppOpenLocation] so the
 * OkHttp interceptor can read it without a dependency cycle (the API client
 * needs the interceptor; AppOpenLocation needs the API client).
 */
@Singleton
class LocationHolder @Inject constructor() {
    @Volatile var lastFix: Location? = null

    /** `lat,lng[,accuracy_m]` for the X-Client-Location header, or null. */
    fun headerValue(): String? = lastFix?.let { f ->
        val acc = if (f.hasAccuracy()) ",%.0f".format(Locale.US, f.accuracy) else ""
        "%.6f,%.6f%s".format(Locale.US, f.latitude, f.longitude, acc)
    }
}
