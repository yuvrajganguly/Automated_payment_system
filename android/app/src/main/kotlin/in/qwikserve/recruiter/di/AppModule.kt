package `in`.qwikserve.recruiter.di

import android.content.Context
import androidx.room.Room
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import `in`.qwikserve.recruiter.BuildConfig
import `in`.qwikserve.recruiter.data.api.PayoutApi
import `in`.qwikserve.recruiter.data.auth.AuthInterceptor
import `in`.qwikserve.recruiter.data.auth.TokenAuthenticator
import `in`.qwikserve.recruiter.data.auth.TokenStore
import `in`.qwikserve.recruiter.data.db.AppDatabase
import `in`.qwikserve.recruiter.data.db.RiderDao
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object AppModule {

    @Provides @Singleton
    fun json(): Json = Json {
        ignoreUnknownKeys = true   // the server may add fields; the app must not break
        explicitNulls = false
        coerceInputValues = true
    }

    @Provides @Singleton
    fun authenticator(store: TokenStore, json: Json): TokenAuthenticator =
        TokenAuthenticator(store, json, BuildConfig.API_BASE_URL)

    @Provides @Singleton
    fun okHttp(auth: AuthInterceptor, authenticator: TokenAuthenticator): OkHttpClient =
        OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .addInterceptor(auth)
            .authenticator(authenticator)
            .apply {
                if (BuildConfig.DEBUG) {
                    addInterceptor(HttpLoggingInterceptor().apply { level = HttpLoggingInterceptor.Level.BASIC })
                }
            }
            .build()

    @Provides @Singleton
    fun retrofit(client: OkHttpClient, json: Json): Retrofit =
        Retrofit.Builder()
            .baseUrl(BuildConfig.API_BASE_URL)
            .client(client)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()

    @Provides @Singleton
    fun api(retrofit: Retrofit): PayoutApi = retrofit.create(PayoutApi::class.java)

    @Provides @Singleton
    fun database(@ApplicationContext context: Context): AppDatabase =
        Room.databaseBuilder(context, AppDatabase::class.java, "qwik.db")
            .fallbackToDestructiveMigration() // it is a cache; the server is the truth
            .build()

    @Provides
    fun riderDao(db: AppDatabase): RiderDao = db.riderDao()
}
