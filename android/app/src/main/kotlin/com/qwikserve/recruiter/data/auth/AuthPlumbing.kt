package com.qwikserve.recruiter.data.auth

import com.qwikserve.recruiter.data.api.ApiError
import com.qwikserve.recruiter.data.api.RefreshIn
import com.qwikserve.recruiter.data.api.TokenOut
import kotlinx.serialization.json.Json
import okhttp3.Authenticator
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.Route
import javax.inject.Inject

/** Adds `Authorization: Bearer` to every call that has a token. */
class AuthInterceptor @Inject constructor(private val store: TokenStore) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val token = store.accessToken
        val req = chain.request()
        if (token == null || req.header("Authorization") != null || req.url.encodedPath.endsWith("/auth/login")) {
            return chain.proceed(req)
        }
        return chain.proceed(req.newBuilder().header("Authorization", "Bearer $token").build())
    }
}

/**
 * On a 401, trade the refresh token for a new pair once and retry the call.
 * A failed refresh clears the session — the UI sees it through TokenStore
 * and shows the sign-in screen with the server's reason.
 *
 * The refresh call uses a bare OkHttp client (no interceptors, no
 * authenticator) so it can never recurse.
 */
class TokenAuthenticator(
    private val store: TokenStore,
    private val json: Json,
    private val baseUrl: String,
) : Authenticator {
    private val bare = OkHttpClient()

    @Volatile var lastFailureReason: String? = null
        private set

    override fun authenticate(route: Route?, response: Response): Request? {
        val path = response.request.url.encodedPath
        if (path.endsWith("/auth/login") || path.endsWith("/auth/refresh")) return null
        if (responseCount(response) >= 2) return null
        val current = store.refreshToken ?: return null

        synchronized(this) {
            // Another call may have refreshed while we waited for the lock.
            val fresh = store.accessToken
            val sent = response.request.header("Authorization")?.removePrefix("Bearer ")
            if (fresh != null && fresh != sent) {
                return response.request.newBuilder().header("Authorization", "Bearer $fresh").build()
            }
            val body = json.encodeToString(RefreshIn.serializer(), RefreshIn(current))
                .toRequestBody("application/json".toMediaType())
            val req = Request.Builder().url(baseUrl + "auth/refresh").post(body).build()
            val res = runCatching { bare.newCall(req).execute() }.getOrNull() ?: return null
            res.use {
                val text = it.body?.string().orEmpty()
                if (!it.isSuccessful) {
                    if (it.code == 401) {
                        lastFailureReason = runCatching {
                            json.decodeFromString(ApiError.serializer(), text).detail
                        }.getOrNull()
                        store.clear()
                    }
                    return null
                }
                val tok = json.decodeFromString(TokenOut.serializer(), text)
                store.save(tok.accessToken, tok.refreshToken, tok.email, tok.role)
                return response.request.newBuilder()
                    .header("Authorization", "Bearer ${tok.accessToken}")
                    .build()
            }
        }
    }

    private fun responseCount(response: Response): Int {
        var n = 1
        var prior = response.priorResponse
        while (prior != null) { n++; prior = prior.priorResponse }
        return n
    }
}
