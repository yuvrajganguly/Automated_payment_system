package com.qwikserve.recruiter.data.api

import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.Field
import retrofit2.http.FormUrlEncoded
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

/** The recruiter-facing slice of the payout server (docs/RECRUITER_API.md). */
interface PayoutApi {

    @FormUrlEncoded
    @POST("auth/login")
    suspend fun login(
        @Field("username") username: String,
        @Field("password") password: String,
        @Field("device") device: String,
    ): TokenOut

    @POST("auth/refresh")
    suspend fun refresh(@Body body: RefreshIn): TokenOut

    @POST("auth/logout")
    suspend fun logout(@Body body: LogoutIn): Response<Unit>

    @GET("auth/me")
    suspend fun me(): UserOut

    @GET("app/bootstrap")
    suspend fun bootstrap(): Bootstrap

    @GET("app/todo")
    suspend fun todo(@Query("zone") zone: String? = null): Todo

    @GET("app/my-recruiting")
    suspend fun myRecruiting(): MyRecruiting

    @POST("app/location")
    suspend fun location(@Body body: LocationIn): LocationAck

    @GET("riders")
    suspend fun riders(
        @Query("q") q: String? = null,
        @Query("company") company: String? = null,
        @Query("active") active: Boolean? = null,
        @Query("limit") limit: Int? = null,
        @Query("offset") offset: Int? = null,
    ): Response<List<RiderOut>>

    @GET("persons/{id}")
    suspend fun person(@Path("id") personId: Long): PersonOut

    @GET("evs")
    suspend fun evs(
        @Query("status") status: String? = null,
        @Query("zone") zone: String? = null,
        @Query("mine") mine: Boolean? = null,
    ): List<EvUnitOut>

    @GET("requests")
    suspend fun requests(@Query("status") status: String? = null, @Query("limit") limit: Int? = null): List<MoneyRequest>

    @GET("activity")
    suspend fun activity(@Query("since") since: String? = null, @Query("limit") limit: Int? = null): List<ActivityRow>
}
