package `in`.qwikserve.recruiter

import android.app.Application
import coil.ImageLoader
import coil.ImageLoaderFactory
import dagger.hilt.android.HiltAndroidApp
import okhttp3.OkHttpClient
import javax.inject.Inject

@HiltAndroidApp
class QwikApp : Application(), ImageLoaderFactory {
    /** Same client as the API: rider photos need the bearer token too. */
    @Inject lateinit var okHttpClient: OkHttpClient

    override fun newImageLoader(): ImageLoader =
        ImageLoader.Builder(this)
            .okHttpClient { okHttpClient }
            .crossfade(true)
            .build()
}
