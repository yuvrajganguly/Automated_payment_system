package com.qwikserve.recruiter

import android.app.Application
import android.content.Context
import coil.ImageLoader
import coil.ImageLoaderFactory
import com.qwikserve.recruiter.data.CrashLog
import com.qwikserve.recruiter.data.location.AppOpenLocation
import dagger.hilt.android.HiltAndroidApp
import okhttp3.OkHttpClient
import javax.inject.Inject

@HiltAndroidApp
class QwikApp : Application(), ImageLoaderFactory {
    /** Same client as the API: rider photos need the bearer token too. */
    @Inject lateinit var okHttpClient: OkHttpClient
    @Inject lateinit var appOpenLocation: AppOpenLocation

    /** Earliest point we own: from here on every startup step is written down,
     *  and anything that kills the process is reported on the next launch. */
    override fun attachBaseContext(base: Context) {
        super.attachBaseContext(base)
        CrashLog.rotateTrail(this)
        CrashLog.install(this)
        CrashLog.breadcrumb(this, "app.attach")
    }

    override fun onCreate() {
        CrashLog.breadcrumb(this, "app.create")
        // super.onCreate() is where Hilt builds the graph and injects this
        // class. If that fails the app is crippled, but a crippled app that
        // can still show the reason beats a process that vanishes.
        try {
            super.onCreate()
            CrashLog.breadcrumb(this, "app.inject")
        } catch (t: Throwable) {
            CrashLog.record(this, t, thread = "app.inject")
        }
        // Nothing below is worth a dead app: a phone that refuses the keystore,
        // a ROM that guards location — the recruiter still gets their screens.
        runCatching { appOpenLocation.install() } // one fix per foreground, ≥30 min apart; nothing in the background
            .onFailure { CrashLog.record(this, it, thread = "app.location(non-fatal)") }
        CrashLog.breadcrumb(this, "app.ready")
    }

    override fun newImageLoader(): ImageLoader {
        val builder = ImageLoader.Builder(this).crossfade(true)
        if (::okHttpClient.isInitialized) {
            val client = okHttpClient
            builder.okHttpClient { client }
        }
        return builder.build()
    }
}
