package com.qwikserve.recruiter.data.location

import okhttp3.Interceptor
import okhttp3.Response
import javax.inject.Inject
import javax.inject.Singleton

/** Adds `X-Client-Location` to writes only (Level 1: stamp actions, never track). */
@Singleton
class LocationHeaderInterceptor @Inject constructor(private val location: LocationHolder) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val req = chain.request()
        if (req.method == "GET") return chain.proceed(req)
        val v = location.headerValue() ?: return chain.proceed(req)
        return chain.proceed(req.newBuilder().header("X-Client-Location", v).build())
    }
}
