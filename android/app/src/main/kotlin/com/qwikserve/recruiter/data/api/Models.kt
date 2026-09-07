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
data class UserOut(val email: String, val role: String, val phone: String? = null, val zone: String? = null)

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
    @SerialName("hub_zones") val hubZones: Map<String, String?> = emptyMap(),
    val zones: List<String> = listOf("North", "South"),
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
    @SerialName("recruited_by") val recruitedBy: String? = null,
    val zone: String? = null,
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
data class EvUnitOut(
    @SerialName("ev_id") val evId: String,
    val provider: String,
    val model: String,
    @SerialName("weekly_rate") val weeklyRate: Double = 0.0,
    val status: String,
    val notes: String? = null,
    @SerialName("current_rider_id") val currentRiderId: String? = null,
    @SerialName("current_person_id") val currentPersonId: Long? = null,
    @SerialName("current_rider_name") val currentRiderName: String? = null,
    val hub: String? = null,
    val zone: String? = null,
    @SerialName("recruited_by") val recruitedBy: String? = null,
    @SerialName("holder_active") val holderActive: Boolean? = null,
    @SerialName("total_dues") val totalDues: Double? = null,
    @SerialName("handover_date") val handoverDate: String? = null,
    @SerialName("rent_charged_through") val rentChargedThrough: String? = null,
)

@Serializable
data class MoneyRequest(
    val id: Long,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("created_by") val createdBy: String? = null,
    @SerialName("person_id") val personId: Long,
    @SerialName("person_name") val personName: String? = null,
    val direction: String, // credit | debit
    val amount: Double = 0.0,
    val reason: String = "",
    val status: String = "open", // open | approved | rejected
    @SerialName("resolved_by") val resolvedBy: String? = null,
    @SerialName("resolved_at") val resolvedAt: String? = null,
    @SerialName("resolution_note") val resolutionNote: String? = null,
    @SerialName("applied_amount") val appliedAmount: Double? = null,
)

/* ── Today: things to do, grouped by store ── */

@Serializable
data class TodoItem(
    val kind: String, // cod | ev_dues | inactive_ev
    val title: String,
    @SerialName("person_id") val personId: Long,
    val name: String,
    val hub: String = "",
    val companies: List<String> = emptyList(),
    @SerialName("mob_no") val mobNo: String? = null,
    @SerialName("ev_id") val evId: String? = null,
    @SerialName("ev_model") val evModel: String? = null,
    @SerialName("cod_outstanding") val codOutstanding: Double? = null,
    val outstanding: Double? = null,
    @SerialName("dues_outstanding") val duesOutstanding: Double? = null,
    @SerialName("total_dues") val totalDues: Double? = null,
    @SerialName("handover_date") val handoverDate: String? = null,
)

@Serializable
data class TodoStore(val hub: String, val zone: String? = null, val items: List<TodoItem> = emptyList())

@Serializable
data class TodoCounts(
    @SerialName("cod_items") val cod: Int = 0,
    @SerialName("ev_dues_items") val evDues: Int = 0,
    @SerialName("inactive_ev_items") val inactiveEv: Int = 0,
    val total: Int = 0,
    val stores: Int = 0,
)

@Serializable
data class Todo(
    val zone: String,
    @SerialName("my_zone") val myZone: String? = null,
    @SerialName("as_of") val asOf: String,
    val counts: TodoCounts = TodoCounts(),
    val stores: List<TodoStore> = emptyList(),
)

/* ── Recruiting numbers ── */

@Serializable
data class RecruitingCounts(
    val today: Int = 0,
    val week: Int = 0,
    val month: Int = 0,
    @SerialName("all_time") val allTime: Int = 0,
    val persons: Int = 0,
    val active: Int = 0,
    @SerialName("ev_holders") val evHolders: Int = 0,
)

@Serializable
data class RecruitingCompany(@SerialName("company_name") val companyName: String, val riders: Int, val active: Int = 0)

@Serializable
data class RecruitingRecent(
    @SerialName("rider_id") val riderId: String,
    @SerialName("company_name") val companyName: String,
    val name: String? = null,
    @SerialName("person_id") val personId: Long,
    val hub: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("is_active") val isActive: Boolean = true,
)

@Serializable
data class MyRecruiting(
    val email: String,
    @SerialName("as_of") val asOf: String,
    val counts: RecruitingCounts = RecruitingCounts(),
    @SerialName("by_company") val byCompany: List<RecruitingCompany> = emptyList(),
    val recent: List<RecruitingRecent> = emptyList(),
)

/* ── Activity (the "Logged today" feed) ── */

@Serializable
data class ActivityRow(
    val id: Long,
    val at: String? = null,
    val action: String,
    @SerialName("action_label") val actionLabel: String? = null,
    @SerialName("entity_type") val entityType: String? = null,
    @SerialName("entity_id") val entityId: String? = null,
    @SerialName("entity_label") val entityLabel: String? = null,
    @SerialName("person_id") val personId: Long? = null,
)

/* ── Location on app open ── */

@Serializable
data class LocationIn(
    val lat: Double,
    val lng: Double,
    @SerialName("accuracy_m") val accuracyM: Float? = null,
    val area: String? = null,
    val source: String = "app_open",
)

@Serializable
data class LocationAck(
    val recorded: Boolean,
    @SerialName("last_at") val lastAt: String? = null,
    @SerialName("next_after") val nextAfter: String? = null,
)

@Serializable
data class ApiError(val detail: String? = null)
