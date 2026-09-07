package com.qwikserve.recruiter.data.api

import okhttp3.MultipartBody
import okhttp3.RequestBody
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.Field
import retrofit2.http.FormUrlEncoded
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.PATCH
import retrofit2.http.Part
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

    /** Email a 6-digit reset code. Accepts an email or a phone number; the code
     *  always goes to the account's email address. */
    @POST("auth/forgot-password")
    suspend fun forgotPassword(@Body body: ForgotPasswordIn): OkOut

    @POST("auth/reset-password")
    suspend fun resetPassword(@Body body: ResetPasswordIn): OkOut

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

    @POST("riders")
    suspend fun createRider(@Body body: RiderIn): RiderOut

    /** A rider's photo (doc_type=photo). The server shrinks and keeps the newest. */
    @Multipart
    @POST("persons/{id}/documents")
    suspend fun uploadDocument(
        @Path("id") personId: Long,
        @Part file: MultipartBody.Part,
        @Part("doc_type") docType: RequestBody,
    ): DocumentOut

    @GET("evs")
    suspend fun evs(
        @Query("status") status: String? = null,
        @Query("zone") zone: String? = null,
        @Query("mine") mine: Boolean? = null,
    ): List<EvUnitOut>

    /** Add a unit the fleet has never seen. With a person_id it is handed over
     *  in the same call. */
    @POST("evs")
    suspend fun createEv(@Body body: EvUnitIn): EvUnitOut

    @POST("evs/assign")
    suspend fun assignEv(@Body body: EvAssignIn): EvActionOut

    /** Retire the unit: off the rider, back to the provider. */
    @POST("evs/return")
    suspend fun returnEv(@Body body: EvReturnIn): EvActionOut

    /** Take it back but keep it — available for the next rider. */
    @POST("evs/to-spare")
    suspend fun evToSpare(@Body body: EvReturnIn): EvActionOut

    @GET("evs/maintenance")
    suspend fun maintenance(@Query("ev_id") evId: String? = null): List<MaintenanceOut>

    @POST("evs/maintenance")
    suspend fun openMaintenance(@Body body: MaintenanceIn): MaintenanceOut

    @PATCH("evs/maintenance/{id}")
    suspend fun closeMaintenance(@Path("id") id: Long, @Body body: MaintenanceClose): MaintenanceOut

    @GET("requests")
    suspend fun requests(@Query("status") status: String? = null, @Query("limit") limit: Int? = null): List<MoneyRequest>

    @GET("ev-requests")
    suspend fun evRequests(@Query("status") status: String? = null, @Query("limit") limit: Int? = null): List<EvRequest>

    @POST("ev-requests")
    suspend fun createEvRequest(@Body body: EvRequestIn): EvRequest

    @POST("ev-requests/{id}/cancel")
    suspend fun cancelEvRequest(@Path("id") id: Long): EvRequest

    @GET("activity")
    suspend fun activity(@Query("since") since: String? = null, @Query("limit") limit: Int? = null): List<ActivityRow>
}
