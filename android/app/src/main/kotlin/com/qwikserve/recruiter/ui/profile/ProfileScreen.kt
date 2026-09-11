package com.qwikserve.recruiter.ui.profile

import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qwikserve.recruiter.BuildConfig
import com.qwikserve.recruiter.data.api.ApiError
import com.qwikserve.recruiter.data.api.ChangePasswordIn
import com.qwikserve.recruiter.data.api.PayoutApi
import com.qwikserve.recruiter.data.api.ProfilePatch
import com.qwikserve.recruiter.data.api.RecruiterProfile
import com.qwikserve.recruiter.data.api.ShiftDays
import com.qwikserve.recruiter.data.api.ShiftMonths
import com.qwikserve.recruiter.data.repo.PhotoRepository
import com.qwikserve.recruiter.ui.common.BarButton
import com.qwikserve.recruiter.ui.common.GhostAction
import com.qwikserve.recruiter.ui.common.Hairline
import com.qwikserve.recruiter.ui.common.Kicker
import com.qwikserve.recruiter.ui.common.Masthead
import com.qwikserve.recruiter.ui.common.Note
import com.qwikserve.recruiter.ui.common.NumberTile
import com.qwikserve.recruiter.ui.common.PhotoTile
import com.qwikserve.recruiter.ui.common.Rule
import com.qwikserve.recruiter.ui.common.Segmented
import com.qwikserve.recruiter.ui.common.km
import com.qwikserve.recruiter.ui.common.monthName
import com.qwikserve.recruiter.ui.common.shortDate
import com.qwikserve.recruiter.ui.login.Field
import com.qwikserve.recruiter.ui.login.fieldColors
import com.qwikserve.recruiter.ui.theme.Qwik
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import retrofit2.HttpException
import java.io.IOException
import java.time.LocalDate
import javax.inject.Inject

/** The three halves of a profile, saved one at a time. */
enum class Section(val key: String, val title: String, val note: String) {
    PERSONAL("personal", "Personal", "Your name as the office knows it, and how to reach you."),
    BANK(
        "bank",
        "Bank",
        "Where your own money is paid. Saved on its own, so a bad signal never costs "
            + "you the rest of the page.",
    ),
    IDENTITY("identity", "Identity", "Only you and an admin ever see these numbers in full."),
}

/**
 * The recruiter's own record: their face, their details, their password and
 * their odometer history.
 *
 * Saving is **per section**, not per form, because `PATCH /recruiters/me/
 * profile` writes only the fields it is sent. A recruiter filling this in on a
 * store's edge of a signal should lose one section to a failed request, not
 * nine fields. The server validates Aadhaar, PAN, IFSC and the account number
 * and answers 400 with a plain sentence; that sentence is shown against the
 * field it is about rather than at the top of the screen where nobody reads it.
 */
@HiltViewModel
class ProfileViewModel @Inject constructor(
    private val api: PayoutApi,
    private val photos: PhotoRepository,
    private val json: Json,
) : ViewModel() {
    var profile by mutableStateOf<RecruiterProfile?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    /* Personal */
    var fullName by mutableStateOf("")
    var phone by mutableStateOf("")
    var address by mutableStateOf("")

    /* Bank */
    var accountName by mutableStateOf("")
    var accountNo by mutableStateOf("")
    var ifsc by mutableStateOf("")
    var bankName by mutableStateOf("")

    /* Identity */
    var aadhaar by mutableStateOf("")
    var pan by mutableStateOf("")

    /** Which section is in flight, so only its button says "Saving…". */
    var saving by mutableStateOf<Section?>(null)
        private set
    /** field key → the server's own sentence about it. */
    var fieldErrors by mutableStateOf<Map<String, String>>(emptyMap())
        private set
    /** section key → an error that belongs to no single field. */
    var sectionErrors by mutableStateOf<Map<String, String>>(emptyMap())
        private set
    var savedSection by mutableStateOf<String?>(null)
        private set

    /* Photo */
    var photoBusy by mutableStateOf(false)
        private set
    var photoError by mutableStateOf<String?>(null)
        private set
    var photoVersion by mutableStateOf(0)
        private set
    private var pendingPhoto: Uri? = null

    /* Password */
    var currentPassword by mutableStateOf("")
    var newPassword by mutableStateOf("")
    var confirmPassword by mutableStateOf("")
    var passwordBusy by mutableStateOf(false)
        private set
    var passwordError by mutableStateOf<String?>(null)
        private set
    var passwordDone by mutableStateOf(false)
        private set

    /* Odometer history */
    var shifts by mutableStateOf<ShiftDays?>(null)
        private set
    var months by mutableStateOf<ShiftMonths?>(null)
        private set
    var historyError by mutableStateOf<String?>(null)
        private set

    init { load(); loadHistory() }

    fun load() {
        if (loading) return
        loading = true
        viewModelScope.launch {
            try {
                val p = api.myProfile()
                profile = p
                // Only overwrite what has not been typed into yet, so a reload
                // behind a half-filled form does not eat somebody's typing.
                if (fullName.isBlank()) fullName = p.fullName.orEmpty()
                if (phone.isBlank()) phone = p.phone.orEmpty()
                if (address.isBlank()) address = p.address.orEmpty()
                if (accountName.isBlank()) accountName = p.accountName.orEmpty()
                if (accountNo.isBlank()) accountNo = p.accountNo.orEmpty()
                if (ifsc.isBlank()) ifsc = p.ifsc.orEmpty()
                if (bankName.isBlank()) bankName = p.bankName.orEmpty()
                if (aadhaar.isBlank()) aadhaar = p.aadhaarNo.orEmpty()
                if (pan.isBlank()) pan = p.panNo.orEmpty()
                error = null
            } catch (e: IOException) {
                if (profile == null) error = "Can't reach the server — your details are on it."
            } catch (e: Exception) {
                error = e.message ?: "Could not load your profile"
            } finally {
                loading = false
            }
        }
    }

    fun loadHistory() {
        viewModelScope.launch {
            try {
                shifts = api.myShifts(days = 30)
                months = api.myShiftMonths(months = 12)
                historyError = null
            } catch (e: IOException) {
                if (shifts == null) historyError = "Offline — your odometer history needs the server."
            } catch (e: Exception) {
                historyError = e.message ?: "Could not load your odometer history"
            }
        }
    }

    /** Send one section. Only its fields travel, so a failure costs one card. */
    fun save(section: Section) {
        if (saving != null) return
        saving = section
        savedSection = null
        fieldErrors = fieldErrors - section.fields()
        sectionErrors = sectionErrors - section.key
        val patch = when (section) {
            Section.PERSONAL -> ProfilePatch(
                fullName = fullName.trim(),
                phone = phone.trim(),
                address = address.trim(),
            )
            Section.BANK -> ProfilePatch(
                accountName = accountName.trim(),
                accountNo = accountNo.filter { it.isDigit() },
                ifsc = ifsc.trim().uppercase(),
                bankName = bankName.trim(),
            )
            Section.IDENTITY -> ProfilePatch(
                aadhaarNo = aadhaar.filter { it.isDigit() },
                panNo = pan.trim().uppercase(),
            )
        }
        viewModelScope.launch {
            try {
                profile = api.updateMyProfile(patch)
                savedSection = section.key
            } catch (e: HttpException) {
                val message = detail(e) ?: "The server answered ${e.code()}."
                val field = fieldFor(message)
                if (field != null) fieldErrors = fieldErrors + (field to message)
                else sectionErrors = sectionErrors + (section.key to message)
            } catch (e: IOException) {
                sectionErrors = sectionErrors + (section.key to "No signal — this section was not saved. The others still are.")
            } catch (e: Exception) {
                sectionErrors = sectionErrors + (section.key to (e.message ?: "That did not save"))
            } finally {
                saving = null
            }
        }
    }

    /** The server's messages name the field they are about, so this reads it
     *  out of the sentence rather than inventing a parallel error code. */
    private fun fieldFor(message: String): String? = when {
        message.contains("aadhaar", ignoreCase = true) -> "aadhaar_no"
        message.contains("pan", ignoreCase = true) -> "pan_no"
        message.contains("ifsc", ignoreCase = true) -> "ifsc"
        message.contains("account number", ignoreCase = true) -> "account_no"
        else -> null
    }

    fun setPhoto(uri: Uri) {
        pendingPhoto = uri
        upload()
    }

    fun retryPhoto() { if (pendingPhoto != null) upload() }

    private fun upload() {
        val uri = pendingPhoto ?: return
        if (photoBusy) return
        photoBusy = true; photoError = null
        viewModelScope.launch {
            runCatching { photos.uploadMyPhoto(uri) }
                .onSuccess { pendingPhoto = null; photoVersion++ }
                .onFailure { photoError = "The picture did not upload. Try again when the signal is better." }
            photoBusy = false
        }
    }

    fun changePassword() {
        if (passwordBusy) return
        passwordDone = false
        passwordError = when {
            currentPassword.isBlank() -> "Type your current password."
            newPassword.length < 8 -> "The new password needs at least 8 characters."
            newPassword != confirmPassword -> "The two new passwords are different."
            else -> null
        }
        if (passwordError != null) return
        passwordBusy = true
        viewModelScope.launch {
            try {
                api.changePassword(ChangePasswordIn(currentPassword, newPassword))
                currentPassword = ""; newPassword = ""; confirmPassword = ""
                passwordDone = true
            } catch (e: HttpException) {
                passwordError = detail(e) ?: when (e.code()) {
                    401 -> "That is not your current password."
                    else -> "The server answered ${e.code()}."
                }
            } catch (e: IOException) {
                passwordError = "No signal — a password change needs the server."
            } catch (e: Exception) {
                passwordError = e.message ?: "Could not change the password"
            } finally {
                passwordBusy = false
            }
        }
    }

    private fun detail(e: HttpException): String? = runCatching {
        json.decodeFromString(ApiError.serializer(), e.response()?.errorBody()?.string().orEmpty()).detail
    }.getOrNull()

    private fun Section.fields(): Set<String> = when (this) {
        Section.PERSONAL -> setOf("full_name", "phone", "address")
        Section.BANK -> setOf("account_name", "account_no", "ifsc", "bank_name")
        Section.IDENTITY -> setOf("aadhaar_no", "pan_no")
    }
}

/**
 * The Profile tab. A recruiter's own page: who they are, where the money goes,
 * what identity is on file, a password they can change themselves, and the
 * odometer history the fuel claim is paid on.
 */
/**
 * The recruiter's own screen, laid out the way the rest of the app is laid
 * out: a masthead, number tiles, a segmented control, list rows on the flat
 * ground with hairlines between them.
 *
 * The order is the order of use. The odometer is twice a day, every day, so it
 * is first — it used to sit at the bottom, under a password form, which is a
 * strange place to put the only thing on the page anybody opens daily. The
 * account details are filled in once and then almost never touched, so they
 * are four quiet rows that open one at a time rather than four forms standing
 * open forever with four Save buttons between you and the bottom of the page.
 */
@Composable
fun ProfileScreen(
    onSignOut: () -> Unit,
    vm: ProfileViewModel = hiltViewModel(),
    shift: ShiftViewModel = hiltViewModel(),
) {
    val p = vm.profile
    // Which detail row is open, if any. One at a time: the rows are a list
    // until you ask one of them a question.
    var open by rememberSaveable { mutableStateOf<String?>(null) }
    val toggle: (String) -> Unit = { key -> open = if (open == key) null else key }

    Column(Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState())) {
        Masthead(
            title = p?.fullName?.takeIf { it.isNotBlank() }
                ?: p?.displayName?.takeIf { it.isNotBlank() }
                ?: p?.email?.substringBefore('@')
                ?: "You",
            sub = listOfNotNull(p?.role, p?.zone?.let { "$it zone" }).joinToString(" · "),
            trailing = {
                PhotoTile(
                    picked = null,
                    // ?u= keys Coil's cache per account — see MeAvatar.
                    url = BuildConfig.API_BASE_URL + "recruiters/me/photo" +
                        "?u=" + (p?.email?.lowercase()?.hashCode() ?: 0),
                    name = p?.fullName,
                    version = vm.photoVersion,
                    size = 84.dp,
                    busy = vm.photoBusy,
                    onPicked = vm::setPhoto,
                )
            },
            trailingAlign = Alignment.CenterVertically,
        )
        if (vm.photoError != null) {
            Column(Modifier.padding(horizontal = 20.dp, vertical = 8.dp)) {
                Text(vm.photoError!!, style = MaterialTheme.typography.bodySmall, color = Qwik.Accent700)
                GhostAction("Retry photo", onClick = vm::retryPhoto)
            }
            Hairline()
        }
        if (vm.error != null) {
            Column(Modifier.padding(horizontal = 20.dp, vertical = 12.dp)) {
                Text(vm.error!!, style = MaterialTheme.typography.bodyMedium, color = Qwik.Accent700)
                GhostAction("Try again", onClick = vm::load)
            }
            Hairline()
        }

        OdometerPanel(vm, shift)

        Kicker("Your details", Modifier.padding(start = 20.dp, top = 22.dp, bottom = 10.dp))
        Hairline()
        Section.entries.forEach { section ->
            DetailRow(
                title = section.title,
                sub = section.summary(vm, p),
                open = open == section.key,
                onToggle = { toggle(section.key) },
            ) { SectionFields(section, vm) }
        }
        DetailRow(
            title = "Password",
            sub = "Changing it signs out every other session",
            open = open == "password",
            onToggle = { toggle("password") },
        ) { PasswordFields(vm) }

        // Sign out lives here, at the foot of your own page, rather than in the
        // app bar. It is the least frequent thing anybody does and it was
        // sitting one mis-tap from the brand at the top of every screen.
        Spacer(Modifier.height(28.dp))
        BarButton(
            "Sign out",
            onClick = onSignOut,
            primary = false,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp),
        )
        Spacer(Modifier.height(36.dp))
    }
}

/** What a closed detail row says about itself, so the list is readable shut. */
private fun Section.summary(vm: ProfileViewModel, p: RecruiterProfile?): String = when (this) {
    Section.PERSONAL -> listOfNotNull(
        vm.fullName.takeIf { it.isNotBlank() },
        vm.phone.takeIf { it.isNotBlank() },
    ).joinToString(" · ").ifBlank { "Not filled in yet" }
    Section.BANK -> listOfNotNull(
        vm.bankName.takeIf { it.isNotBlank() },
        p?.accountNo?.takeIf { it.isNotBlank() },
    ).joinToString(" · ").ifBlank { "Where your own money is paid" }
    Section.IDENTITY -> listOfNotNull(
        if (vm.aadhaar.isNotBlank()) "Aadhaar saved" else null,
        if (vm.pan.isNotBlank()) "PAN saved" else null,
    ).joinToString(" · ").ifBlank { "Aadhaar and PAN" }
}

/**
 * The odometer, first on the page: the two figures that matter, then today's
 * readings, then the record.
 *
 * [ShiftViewModel] is shared with the one-line nudge on Today — both sit under
 * the same navigation entry — so saving a reading here changes that line
 * without a reload.
 */
@Composable
private fun OdometerPanel(vm: ProfileViewModel, shift: ShiftViewModel) {
    val s = shift.shift
    val thisMonth = remember { LocalDate.now().toString().take(7) }
    val monthKm = vm.months?.months?.firstOrNull { it.month == thisMonth }?.km
    var grain by rememberSaveable { mutableIntStateOf(0) } // 0 = day by day, 1 = by month

    Kicker("Odometer", Modifier.padding(start = 20.dp, top = 18.dp, bottom = 10.dp))
    Row(Modifier.fillMaxWidth()) {
        NumberTile(
            when {
                s == null -> "—"
                s.complete -> km(s.distanceKm)
                s.startKm != null -> "open"
                else -> "—"
            },
            "Today",
            Modifier.weight(1f),
            // Red only while the day is genuinely unfinished — not while it is
            // still loading, when nobody knows yet.
            accent = s != null && !s.complete,
        )
        Box(Modifier.width(1.dp).height(78.dp).background(Qwik.N400))
        NumberTile(if (monthKm != null) km(monthKm) else "—", "This month", Modifier.weight(1f))
        Box(Modifier.width(1.dp).height(78.dp).background(Qwik.N400))
        NumberTile(km(vm.shifts?.totalKm), "Last 30 days", Modifier.weight(1f))
    }
    Rule()
    ShiftCard()
    Rule()
    Segmented(
        listOf("Day by day", "By month"),
        selected = grain,
        onSelect = { grain = it },
        modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 14.dp),
    )
    when {
        vm.historyError != null -> Column(Modifier.padding(horizontal = 20.dp, vertical = 4.dp)) {
            Text(vm.historyError!!, style = MaterialTheme.typography.bodyMedium, color = Qwik.Accent700)
            GhostAction("Try again", onClick = vm::loadHistory)
        }
        grain == 0 -> DayList(vm)
        else -> MonthList(vm)
    }
}

/** One row per day: the date, what was read, the distance. */
@Composable
private fun DayList(vm: ProfileViewModel) {
    val s = vm.shifts
    when {
        s == null -> Note("Loading…")
        s.days.isEmpty() -> Note(
            "No readings yet. Open and close a shift above and the days collect here.",
        )
        else -> {
            Hairline()
            s.days.forEach { d ->
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 11.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        shortDate(d.day),
                        style = MaterialTheme.typography.titleMedium,
                        color = Qwik.Ink,
                        modifier = Modifier.width(70.dp),
                    )
                    Column(Modifier.weight(1f)) {
                        Text(
                            when {
                                d.complete -> "${d.startKm} → ${d.endKm}"
                                d.startKm != null -> "opened at ${d.startKm} — not closed"
                                else -> "no opening reading"
                            },
                            style = MaterialTheme.typography.bodyMedium,
                            color = if (d.complete) Qwik.N800 else Qwik.Accent700,
                        )
                        val photos = listOfNotNull(
                            if (d.hasStartPhoto) "start photo" else null,
                            if (d.hasEndPhoto) "end photo" else null,
                        ).joinToString(" · ")
                        if (photos.isNotBlank()) {
                            Text(photos, style = MaterialTheme.typography.bodySmall, color = Qwik.N600)
                        }
                    }
                    Text(
                        if (d.complete) km(d.distanceKm) else "open",
                        style = MaterialTheme.typography.titleMedium,
                        color = if (d.complete) Qwik.Ink else Qwik.Accent,
                    )
                }
                Hairline()
            }
            Text(
                listOfNotNull(
                    "${s.daysRecorded} day" + if (s.daysRecorded == 1) "" else "s",
                    s.averageKm?.let { "avg ${it.toInt()} km" },
                ).joinToString(" · "),
                style = MaterialTheme.typography.bodySmall,
                color = Qwik.N600,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 10.dp),
            )
        }
    }
}

/** The months, with a bar each. This is the figure the fuel claim is paid on. */
@Composable
private fun MonthList(vm: ProfileViewModel) {
    val m = vm.months
    when {
        m == null -> Note("Loading…")
        m.months.isEmpty() -> Note("No month has a closed day yet.")
        else -> {
            Hairline()
            val max = m.months.maxOf { it.km }.coerceAtLeast(1)
            m.months.forEach { row ->
                Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 11.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            monthName(row.month),
                            style = MaterialTheme.typography.titleMedium,
                            color = Qwik.Ink,
                            modifier = Modifier.weight(1f),
                        )
                        Text(km(row.km), style = MaterialTheme.typography.titleMedium, color = Qwik.Ink)
                    }
                    Spacer(Modifier.height(6.dp))
                    Box(Modifier.fillMaxWidth().height(6.dp).background(Qwik.N200)) {
                        Box(Modifier.fillMaxWidth(row.km / max.toFloat()).height(6.dp).background(Qwik.Accent))
                    }
                    Spacer(Modifier.height(5.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(
                            "${row.daysRecorded} day" + if (row.daysRecorded == 1) "" else "s",
                            style = MaterialTheme.typography.bodySmall, color = Qwik.N600,
                        )
                        if (row.daysOpen > 0) {
                            Text(
                                "${row.daysOpen} still open",
                                style = MaterialTheme.typography.bodySmall, color = Qwik.Accent700,
                            )
                        }
                    }
                }
                Hairline()
            }
            Text(
                "Only days with both readings count. A day nobody closed is flagged rather " +
                    "than quietly leaving a month short.",
                style = MaterialTheme.typography.bodySmall,
                color = Qwik.N600,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 10.dp),
            )
        }
    }
}

/** A list row that opens. Shut, it reads like every other row in the app. */
@Composable
private fun DetailRow(
    title: String,
    sub: String,
    open: Boolean,
    onToggle: () -> Unit,
    content: @Composable () -> Unit,
) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onToggle).padding(horizontal = 20.dp, vertical = 13.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleLarge, color = Qwik.Ink, maxLines = 1)
            Text(sub, style = MaterialTheme.typography.bodyMedium, color = Qwik.N700, maxLines = 1)
        }
        Spacer(Modifier.width(10.dp))
        Text(
            if (open) "CLOSE" else "EDIT",
            style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.ExtraBold),
            color = Qwik.Accent,
        )
    }
    if (open) {
        Column(Modifier.fillMaxWidth().background(Qwik.N100).padding(horizontal = 20.dp, vertical = 16.dp)) {
            content()
        }
    }
    Hairline()
}

/** The fields of one section, with its own note, its own error and its own
 *  button — PATCH writes only what it is sent, so a bad signal costs one
 *  section rather than the whole page. */
@Composable
private fun SectionFields(section: Section, vm: ProfileViewModel) {
    Text(section.note, style = MaterialTheme.typography.bodySmall, color = Qwik.N700)
    Spacer(Modifier.height(12.dp))
    when (section) {
        Section.PERSONAL -> {
            Field("Full name") {
                Input(vm.fullName, { vm.fullName = it }, "Name as on the Aadhaar", cap = KeyboardCapitalization.Words)
            }
            ErrorLine(vm.fieldErrors["full_name"])
            Field("Phone") {
                Input(vm.phone, { vm.phone = it }, "98765 43210", keyboard = KeyboardType.Phone)
            }
            ErrorLine(vm.fieldErrors["phone"])
            Field("Address") {
                Input(vm.address, { vm.address = it }, "Where post reaches you", cap = KeyboardCapitalization.Sentences, lines = 3)
            }
            ErrorLine(vm.fieldErrors["address"])
        }
        Section.BANK -> {
            Field("Account holder") {
                Input(vm.accountName, { vm.accountName = it }, "Name on the passbook", cap = KeyboardCapitalization.Words)
            }
            ErrorLine(vm.fieldErrors["account_name"])
            Field("Account number") {
                Input(vm.accountNo, { vm.accountNo = it }, "Digits only", keyboard = KeyboardType.Number)
            }
            ErrorLine(vm.fieldErrors["account_no"])
            Field("IFSC") {
                Input(vm.ifsc, { vm.ifsc = it }, "HDFC0000123", cap = KeyboardCapitalization.Characters)
            }
            ErrorLine(vm.fieldErrors["ifsc"])
            Field("Bank") {
                Input(vm.bankName, { vm.bankName = it }, "HDFC Bank", cap = KeyboardCapitalization.Words)
            }
            ErrorLine(vm.fieldErrors["bank_name"])
        }
        Section.IDENTITY -> {
            Field("Aadhaar") {
                Input(vm.aadhaar, { vm.aadhaar = it }, "Twelve digits", keyboard = KeyboardType.Number)
            }
            ErrorLine(vm.fieldErrors["aadhaar_no"])
            Field("PAN") {
                Input(vm.pan, { vm.pan = it }, "ABCDE1234F", cap = KeyboardCapitalization.Characters)
            }
            ErrorLine(vm.fieldErrors["pan_no"])
        }
    }
    vm.sectionErrors[section.key]?.let {
        Spacer(Modifier.height(4.dp))
        Text(it, style = MaterialTheme.typography.bodySmall, color = Qwik.Accent700)
    }
    if (vm.savedSection == section.key) {
        Spacer(Modifier.height(4.dp))
        Text("Saved.", style = MaterialTheme.typography.bodySmall, color = Qwik.N700)
    }
    Spacer(Modifier.height(14.dp))
    BarButton(
        if (vm.saving == section) "Saving…" else "Save ${section.title.lowercase()}",
        onClick = { vm.save(section) },
        enabled = vm.saving == null,
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun PasswordFields(vm: ProfileViewModel) {
    Text(
        "At least eight characters. Changing it signs out every other session — any other " +
            "phone you are signed in on will ask for the new password, and so will this one " +
            "the next time it renews.",
        style = MaterialTheme.typography.bodySmall, color = Qwik.N700,
    )
    Spacer(Modifier.height(12.dp))
    Field("Current password") { Secret(vm.currentPassword) { vm.currentPassword = it } }
    Spacer(Modifier.height(10.dp))
    Field("New password") { Secret(vm.newPassword) { vm.newPassword = it } }
    Spacer(Modifier.height(10.dp))
    Field("New password again") { Secret(vm.confirmPassword) { vm.confirmPassword = it } }
    if (vm.passwordError != null) {
        Spacer(Modifier.height(8.dp))
        Text(vm.passwordError!!, style = MaterialTheme.typography.bodySmall, color = Qwik.Accent700)
    }
    if (vm.passwordDone) {
        Spacer(Modifier.height(8.dp))
        Text(
            "Password changed. Every other session has been signed out.",
            style = MaterialTheme.typography.bodySmall, color = Qwik.Accent700,
        )
    }
    Spacer(Modifier.height(14.dp))
    BarButton(
        if (vm.passwordBusy) "Changing…" else "Change password",
        onClick = vm::changePassword,
        enabled = !vm.passwordBusy,
        primary = false,
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun Input(
    value: String,
    onChange: (String) -> Unit,
    placeholder: String,
    keyboard: KeyboardType = KeyboardType.Text,
    cap: KeyboardCapitalization = KeyboardCapitalization.None,
    lines: Int = 1,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        placeholder = { Text(placeholder, color = Qwik.N600, maxLines = 1) },
        singleLine = lines == 1,
        maxLines = lines,
        keyboardOptions = KeyboardOptions(keyboardType = keyboard, capitalization = cap),
        colors = fieldColors(),
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun Secret(value: String, onChange: (String) -> Unit) {
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        singleLine = true,
        visualTransformation = PasswordVisualTransformation(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
        colors = fieldColors(),
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun ErrorLine(text: String?) {
    Text(
        text ?: "",
        style = MaterialTheme.typography.bodySmall,
        color = Qwik.Accent700,
        modifier = Modifier.padding(top = 4.dp, bottom = 8.dp),
    )
}
