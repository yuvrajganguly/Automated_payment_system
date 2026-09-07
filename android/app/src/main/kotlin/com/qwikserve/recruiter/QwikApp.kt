package com.qwikserve.recruiter

import android.app.Application
import coil.ImageLoader
import coil.ImageLoaderFactory
import com.qwikserve.recruiter.data.location.AppOpenLocation
import dagger.hilt.android.HiltAndroidApp
import okhttp3.OkHttpClient
import javax.inject.Inject

@HiltAndroidApp
class QwikApp : Application(), ImageLoaderFactory {
    /** Same client as the API: rider photos need the bearer token too. */
    @Inject lateinit var okHttpClient: OkHttpClient
    @Inject lateinit var appOpenLocation: AppOpenLocation

    override fun onCreate() {
        super.onCreate()
        appOpenLocation.install() // one fix per foreground, ≥30 min apart; nothing in the background
    }

    override fun newImageLoader(): ImageLoader =
        ImageLoader.Builder(this)
            .okHttpClient { okHttpClient }
            .crossfade(true)
            .build()
}
