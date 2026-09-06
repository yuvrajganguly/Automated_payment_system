package com.qwikserve.recruiter.data.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/* Wire models — the shapes in docs/RECRUITER_API.md. Money is rupees. */

@Serializable
data class TokenOut(
    @SerialName("access_token") val accessToken: String,
    @SerialName("token_type") val tokenType: String = "bearer",
    val role: String,
    val email: String,
    @SerialName("expires_in") val expiresIn: Int? = null,
    @SerialName("refresh_token") val refreshToken: String? = null,
)

@Serializable
data class RefreshIn(@SerialName("refresh_token") val refreshToken: String)

@Serializable
data class LogoutIn(@SerialName("refresh_token") val refreshToken: String?)

@Serializable
data class UserOut(val email: String, val role: String, val phone: String? = null)

@Serializable
data class CompanyLite(
    @SerialName("company_name") val companyName: String,
    @SerialName("payment_model") val paymentModel: String = "payout_file",
    @SerialName("rider_ids_shared_with") val riderIdsSharedWith: String? = null,
)

@Serializable
data class EvModelLite(
    @SerialName("model_id") val modelId: Long,
    val provider: String,
    @SerialName("model_name") val modelName: String,
)

@Serializable
data class Counts(
    @SerialName("rider_ids_active") val riderIdsActive: Int = 0,
    @SerialName("persons_active") val personsActive: Int = 0,
    val evs: Map<String, Int> = emptyMap(),
)

@Serializable
data class Bootstrap(
    @SerialName("api_version") val apiVersion: Int,
    @SerialName("server_time") val serverTime: String,
    val me: UserOut,
    val companies: List<CompanyLite>,
    val hubs: List<String>,
    @SerialName("ev_models") val evModels: List<EvModelLite> = emptyList(),
    val counts: Counts = Counts(),
)

@Serializable
data class RiderOut(
    @SerialName("rider_id") val riderId: String,
    val company: String,
    @SerialName("person_id") val personId: Long,
    val name: String? = null,
    val hub: String? = null,
    val vehicle: String? = null,
    @SerialName("account_no") val accountNo: String? = null,
    val ifsc: String? = null,
    @SerialName("mob_no") val mobNo: String? = null,
    @SerialName("is_active") val isActive: Boolean = true,
)

@Serializable
data class PersonEv(
    @SerialName("ev_id") val evId: String,
    val provider: String,
    val model: String,
    @SerialName("weekly_rate") val weeklyRate: Double = 0.0,
    @SerialName("handover_date") val handoverDate: String? = null,
    @SerialName("rent_charged_through") val rentChargedThrough: String? = null,
)

@Serializable
data class PersonOut(
    @SerialName("person_id") val personId: Long,
    @SerialName("display_name") val displayName: String,
    @SerialName("aadhaar_no") val aadhaarNo: String? = null,
    @SerialName("pan_no") val panNo: String? = null,
    @SerialName("current_balance") val currentBalance: Double? = null,
    @SerialName("arrears_outstanding") val arrearsOutstanding: Double? = null,
    val riders: List<RiderOut> = emptyList(),
    val ev: PersonEv? = null,
)

@Serializable
data class ApiError(val detail: String? = null)
