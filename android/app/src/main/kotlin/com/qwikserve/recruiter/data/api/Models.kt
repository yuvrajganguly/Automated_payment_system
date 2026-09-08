package com.qwikserve.recruiter.data.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

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
data class UserOut(
    val email: String,
    val role: String,
    val phone: String? = null,
    val zone: String? = null,
    /** What to call them on screen. The bootstrap fills this in from their
     *  profile; endpoints that do not send it fall back to the email. */
    val name: String? = null,
)

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
data class CompanyHub(val company: String, val hub: String, val zone: String? = null)

@Serializable
data class Bootstrap(
    @SerialName("api_version") val apiVersion: Int,
    @SerialName("server_time") val serverTime: String,
    val me: UserOut,
    val companies: List<CompanyLite>,
    val hubs: List<String>,
    @SerialName("hub_zones") val hubZones: Map<String, String?> = emptyMap(),
    @SerialName("company_hubs") val companyHubs: List<CompanyHub> = emptyList(),
    val zones: List<String> = listOf("North", "South", "Misc"),
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
    /** A paysheet company paid them for a cycle ending in the last 12 days. */
    val working: Boolean? = null,
    /** End date of the last cycle a company paid them for; null if never. */
    @SerialName("last_worked_on") val lastWorkedOn: String? = null,
    @SerialName("referred_by") val referredBy: String? = null, // only on the create response
    @SerialName("copied_from") val copiedFrom: CopiedFrom? = null,
)

@Serializable
data class CopiedFrom(val from: String, val fields: List<String> = emptyList())

/** Onboarding body for POST /riders. Blank strings are sent as null. */
@Serializable
data class RiderIn(
    val company: String,
    val name: String,
    @SerialName("rider_id") val riderId: String? = null,
    val hub: String? = null,
    @SerialName("mob_no") val mobNo: String? = null,
    @SerialName("account_no") val accountNo: String? = null,
    val ifsc: String? = null,
    @SerialName("aadhaar_no") val aadhaarNo: String? = null,
    @SerialName("pan_no") val panNo: String? = null,
    @SerialName("person_id") val personId: Long? = null,
    @SerialName("allow_duplicate_name") val allowDuplicateName: Boolean = false,
    @SerialName("referred_by_person_id") val referredByPersonId: Long? = null,
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

@Serializable
data class DocumentOut(
    val id: Long,
    @SerialName("person_id") val personId: Long,
    @SerialName("doc_type") val docType: String = "",
    val filename: String = "",
    @SerialName("size_bytes") val sizeBytes: Long = 0,
)

/* ── EV actions: hand one over, take it back, park it, fix it ── */

@Serializable
data class EvAssignIn(
    @SerialName("ev_id") val evId: String,
    @SerialName("person_id") val personId: Long? = null,
    @SerialName("handover_date") val handoverDate: String? = null, // null = today
)

@Serializable
data class EvReturnIn(
    @SerialName("ev_id") val evId: String? = null,
    @SerialName("rider_id") val riderId: String? = null,
    val company: String? = null,
    @SerialName("returned_date") val returnedDate: String? = null, // null = today
)

/** A unit that is not in the system yet. With [personId] the server creates it
 *  and hands it over in the same call — which is what happens in a store when
 *  a new vehicle arrives with the rider standing next to it. */
@Serializable
data class EvUnitIn(
    @SerialName("ev_id") val evId: String,
    val provider: String,
    val model: String,
    val notes: String? = null,
    @SerialName("person_id") val personId: Long? = null,
    @SerialName("handover_date") val handoverDate: String? = null,
)

/** The server answers each action with a small object; the app only needs to
 *  know it worked and, for a return, that the office still owes a close-out.
 *  [closeout] is the assignment that just closed — present only when the
 *  vehicle came back off a rider, which is the only case there is a deposit
 *  to ask about. */
@Serializable
data class EvActionOut(
    @SerialName("ev_id") val evId: String? = null,
    @SerialName("person_id") val personId: Long? = null,
    val assigned: Boolean = false,
    val returned: Boolean = false,
    val spare: Boolean = false,
    @SerialName("handover_date") val handoverDate: String? = null,
    @SerialName("returned_date") val returnedDate: String? = null,
    val closeout: CloseoutRow? = null,
)

/* ── The security deposit, from the hub's side ──
 * Every EV rider pays a deposit. When the vehicle comes back somebody has to
 * say whether it went back to them in cash and, if it did not, what the
 * damage was. The recruiter is the one standing there holding the vehicle, so
 * they answer it; the office still settles the money afterwards, on a form
 * this report pre-fills. Nothing here moves a rupee. Money is rupees. */

@Serializable
data class CloseoutReport(
    @SerialName("assignment_id") val assignmentId: Long,
    @SerialName("ev_id") val evId: String? = null,
    @SerialName("person_id") val personId: Long? = null,
    /** The deposit was handed back in cash. Then damage must be zero — the
     *  server refuses the two together. */
    @SerialName("sd_returned") val sdReturned: Boolean = false,
    @SerialName("damage_charges") val damageCharges: Double = 0.0,
    @SerialName("damage_note") val damageNote: String? = null,
    @SerialName("has_photo") val hasPhoto: Boolean = false,
    @SerialName("reported_by") val reportedBy: String? = null,
    @SerialName("reported_at") val reportedAt: String? = null,
)

/** A row of GET /evs/closeouts/mine: an assignment this recruiter took back
 *  that still needs the deposit answer, with whatever they have already said
 *  about it. The same shape comes back on a return as [EvActionOut.closeout]. */
@Serializable
data class CloseoutRow(
    @SerialName("assignment_id") val assignmentId: Long,
    @SerialName("ev_id") val evId: String,
    @SerialName("person_id") val personId: Long,
    val name: String? = null,
    val model: String? = null,
    val provider: String? = null,
    @SerialName("handover_date") val handoverDate: String? = null,
    @SerialName("returned_date") val returnedDate: String? = null,
    val report: CloseoutReport? = null,
)

/** POST /evs/closeouts/{assignment_id}/report. Re-posting corrects the last
 *  answer; once the office has settled the deposit it is refused. */
@Serializable
data class CloseoutReportIn(
    @SerialName("sd_returned") val sdReturned: Boolean,
    @SerialName("damage_charges") val damageCharges: Double = 0.0,
    @SerialName("damage_note") val damageNote: String? = null,
)

@Serializable
data class MaintenanceIn(
    @SerialName("ev_id") val evId: String,
    @SerialName("from_date") val fromDate: String,
    @SerialName("to_date") val toDate: String? = null, // open-ended
    val reason: String? = null,
)

@Serializable
data class MaintenanceClose(@SerialName("to_date") val toDate: String? = null)

@Serializable
data class MaintenanceOut(
    val id: Long,
    @SerialName("ev_id") val evId: String,
    @SerialName("from_date") val fromDate: String,
    @SerialName("to_date") val toDate: String? = null,
    val reason: String? = null,
)

/* ── EV requests: "I need 3 EVs at Belur" ── */

@Serializable
data class EvRequest(
    val id: Long,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("created_by") val createdBy: String? = null,
    val quantity: Int = 1,
    val hub: String? = null,
    val company: String? = null,
    val zone: String? = null,
    val note: String? = null,
    val status: String = "open", // open | fulfilled | rejected | cancelled
    @SerialName("fulfilled_quantity") val fulfilledQuantity: Int? = null,
    @SerialName("resolved_by") val resolvedBy: String? = null,
    @SerialName("resolved_at") val resolvedAt: String? = null,
    @SerialName("resolution_note") val resolutionNote: String? = null,
)

@Serializable
data class EvRequestIn(
    val quantity: Int,
    val hub: String? = null,
    val company: String? = null,
    val note: String? = null,
)

/* ── Password reset by emailed code ── */

@Serializable
data class ForgotPasswordIn(val email: String)

@Serializable
data class ResetPasswordIn(
    val email: String,
    val otp: String,
    @SerialName("new_password") val newPassword: String,
)

@Serializable
data class OkOut(val ok: Boolean = true, val message: String? = null)

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
    /** Still on the roster — the switch, not the 12-day worked rule. */
    @SerialName("on_roster") val onRoster: Int = 0,
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

/* ── One rider's timeline (GET /app/person/{id}/timeline) ──
 * The same activity log the console reads, scoped to a person rather than to
 * an operator, so it shows every hand that touched them — not only this
 * recruiter's own rows. [actionLabel] arrives as a finished English phrase
 * ("Assigned EV"); [details] is free-form JSON the app only ever displays. */

@Serializable
data class TimelineEvent(
    val id: Long,
    val at: String? = null,
    val email: String? = null,
    val role: String? = null,
    val action: String,
    @SerialName("entity_type") val entityType: String? = null,
    @SerialName("entity_id") val entityId: String? = null,
    @SerialName("entity_label") val entityLabel: String? = null,
    val details: JsonElement? = null,
    val lat: Double? = null,
    val lng: Double? = null,
    @SerialName("action_label") val actionLabel: String? = null,
)

/* ── Week-by-week and month-by-month (GET /recruiters/me/series) ──
 * [stillWorking] is a cohort figure: of the riders signed up in that bucket,
 * how many are working now — not how many were working then. */

@Serializable
data class SeriesBucket(
    val bucket: String,
    val onboarded: Int = 0,
    @SerialName("still_working") val stillWorking: Int = 0,
    @SerialName("evs_deployed") val evsDeployed: Int = 0,
    val km: Int = 0,
)

@Serializable
data class SeriesTotals(
    val onboarded: Int = 0,
    @SerialName("still_working") val stillWorking: Int = 0,
    @SerialName("evs_deployed") val evsDeployed: Int = 0,
    val km: Int = 0,
)

@Serializable
data class RecruiterSeries(
    val email: String = "",
    val grain: String = "week",
    @SerialName("active_within_days") val activeWithinDays: Int = 12,
    val series: List<SeriesBucket> = emptyList(),
    val totals: SeriesTotals = SeriesTotals(),
)

/** A row of GET /recruiters/me/riders — the drilldown behind a count tile. */
@Serializable
data class RecruiterRider(
    @SerialName("rider_id") val riderId: String,
    @SerialName("company_name") val companyName: String,
    val name: String? = null,
    @SerialName("person_id") val personId: Long,
    val hub: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("on_roster") val onRoster: Boolean = true,
    val working: Boolean = false,
    @SerialName("last_worked_on") val lastWorkedOn: String? = null,
    /** The EV this rider is holding right now, or null. */
    @SerialName("ev_id") val evId: String? = null,
)

/* ── The odometer at the start and end of a shift ──
 * The number is the claim and the photo is the evidence, so the reading is
 * saved first and the picture hangs off it. Whole kilometres throughout. */

@Serializable
data class ShiftOut(
    val id: Long? = null,
    val email: String = "",
    val day: String = "",
    @SerialName("start_km") val startKm: Int? = null,
    @SerialName("end_km") val endKm: Int? = null,
    @SerialName("distance_km") val distanceKm: Int? = null,
    @SerialName("start_at") val startAt: String? = null,
    @SerialName("end_at") val endAt: String? = null,
    @SerialName("has_start_photo") val hasStartPhoto: Boolean = false,
    @SerialName("has_end_photo") val hasEndPhoto: Boolean = false,
    val note: String? = null,
    val complete: Boolean = false,
    /** Only on the save response — the server's soft doubts, never blocking. */
    val warnings: List<String> = emptyList(),
)

@Serializable
data class ShiftIn(
    val kind: String, // start | end
    val km: Int,
    val day: String? = null, // null = today
    val note: String? = null,
)

@Serializable
data class ShiftDays(
    val email: String = "",
    val since: String? = null,
    val days: List<ShiftOut> = emptyList(),
    @SerialName("total_km") val totalKm: Int = 0,
    @SerialName("days_recorded") val daysRecorded: Int = 0,
    @SerialName("average_km") val averageKm: Double? = null,
    val incomplete: List<String> = emptyList(),
)

/** A month of the fuel claim. [daysOpen] is days somebody never closed — they
 *  contribute nothing to [km], so the total is never quietly short. */
@Serializable
data class ShiftMonth(
    val month: String,
    val km: Int = 0,
    @SerialName("days_recorded") val daysRecorded: Int = 0,
    @SerialName("days_open") val daysOpen: Int = 0,
)

@Serializable
data class ShiftMonths(val email: String = "", val months: List<ShiftMonth> = emptyList())

/* ── The recruiter's own record (GET/PATCH /recruiters/me/profile) ── */

@Serializable
data class RecruiterProfile(
    val email: String = "",
    @SerialName("full_name") val fullName: String? = null,
    @SerialName("display_name") val displayName: String? = null,
    val phone: String? = null,
    val address: String? = null,
    @SerialName("account_name") val accountName: String? = null,
    @SerialName("account_no") val accountNo: String? = null,
    val ifsc: String? = null,
    @SerialName("bank_name") val bankName: String? = null,
    @SerialName("aadhaar_no") val aadhaarNo: String? = null,
    @SerialName("pan_no") val panNo: String? = null,
    val role: String? = null,
    val zone: String? = null,
    @SerialName("is_active") val isActive: Boolean = true,
    @SerialName("has_photo") val hasPhoto: Boolean = false,
    @SerialName("updated_at") val updatedAt: String? = null,
    /** True when the numbers came back masked — never on one's own profile. */
    val masked: Boolean = false,
)

/** Only the fields sent are written, so the app saves one section at a time:
 *  a weak signal costs a recruiter one section, not the whole form. Nulls are
 *  dropped by the Json config; an empty string clears the field server-side. */
@Serializable
data class ProfilePatch(
    @SerialName("full_name") val fullName: String? = null,
    val phone: String? = null,
    val address: String? = null,
    @SerialName("account_name") val accountName: String? = null,
    @SerialName("account_no") val accountNo: String? = null,
    val ifsc: String? = null,
    @SerialName("bank_name") val bankName: String? = null,
    @SerialName("aadhaar_no") val aadhaarNo: String? = null,
    @SerialName("pan_no") val panNo: String? = null,
)

@Serializable
data class ChangePasswordIn(
    @SerialName("current_password") val currentPassword: String,
    @SerialName("new_password") val newPassword: String,
)
