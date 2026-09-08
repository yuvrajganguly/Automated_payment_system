package com.qwikserve.recruiter.ui.evs

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qwikserve.recruiter.data.api.ApiError
import com.qwikserve.recruiter.data.api.CloseoutReport
import com.qwikserve.recruiter.data.api.CloseoutReportIn
import com.qwikserve.recruiter.data.api.CloseoutRow
import com.qwikserve.recruiter.data.api.PayoutApi
import com.qwikserve.recruiter.ui.common.BarButton
import com.qwikserve.recruiter.ui.common.GhostAction
import com.qwikserve.recruiter.ui.common.Hairline
import com.qwikserve.recruiter.ui.common.Kicker
import com.qwikserve.recruiter.ui.common.Segmented
import com.qwikserve.recruiter.ui.common.Tag
import com.qwikserve.recruiter.ui.common.rupees
import com.qwikserve.recruiter.ui.common.shortDate
import com.qwikserve.recruiter.ui.login.fieldColors
import com.qwikserve.recruiter.ui.theme.Qwik
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import retrofit2.HttpException
import java.io.IOException
import javax.inject.Inject

/**
 * The security deposit, answered by the person who is holding the vehicle.
 *
 * Every EV rider pays a deposit. The moment the vehicle comes back there is
 * exactly one question worth asking, and only one person in the country can
 * answer it: did the money go back to the rider in cash, and if it did not,
 * what was wrong with the vehicle. That person is the recruiter standing in
 * the hub — not the office, which sees the assignment a day later and a city
 * away.
 *
 * So this is a **report, not a charge**. Nothing here moves a rupee: the
 * office's close-out is still the only thing that settles the deposit against
 * arrears and dues, and this only fills its form in for them. The two rules
 * that matter stay on the server and are surfaced, not re-implemented — a
 * deposit that went back whole cannot also have damage owed against it (the
 * app hides the damage fields rather than sending the pair), and once the
 * office has settled, the answer is fixed and the server says so.
 */
@HiltViewModel
class CloseoutsViewModel @Inject constructor(
    private val api: PayoutApi,
    private val json: Json,
) : ViewModel() {
    var rows by mutableStateOf<List<CloseoutRow>>(emptyList())
        private set

    /** True once a load has come back, so "nothing waiting" is a fact rather
     *  than the gap before the first request finishes. */
    var loaded by mutableStateOf(false)
        private set
    var loading by mutableStateOf(false)
        private set
    var loadError by mutableStateOf<String?>(null)
        private set
    var saving by mutableStateOf(false)
        private set

    /** The server's own sentence about the last attempt, shown by the field it
     *  is about. Never swallowed, never rewritten. */
    var saveError by mutableStateOf<String?>(null)
        private set

    init { load() }

    fun load() {
        if (loading) return
        loading = true
        viewModelScope.launch {
            try {
                rows = api.myCloseouts(limit = 50)
                loaded = true
                loadError = null
            } catch (e: IOException) {
                if (!loaded) loadError = "No signal — the deposits you owe an answer on will be here when there is one."
            } catch (e: Exception) {
                loadError = e.readable("Could not load the deposits waiting on you")
            } finally {
                loading = false
            }
        }
    }

    fun clearSaveError() { saveError = null }

    /**
     * File the answer. [charges] is rupees, as the wire wants it, and is
     * always zero when the deposit went back — the server refuses the pair,
     * and sending it to be told so would be a round trip spent on nothing.
     */
    fun save(
        assignmentId: Long,
        sdReturned: Boolean,
        charges: Double,
        note: String,
        onSaved: (String) -> Unit,
    ) {
        if (saving) return
        saving = true; saveError = null
        viewModelScope.launch {
            try {
                val out = api.reportCloseout(
                    assignmentId,
                    CloseoutReportIn(
                        sdReturned = sdReturned,
                        damageCharges = if (sdReturned) 0.0 else charges,
                        damageNote = if (sdReturned) null else note.trim().ifBlank { null },
                    ),
                )
                onSaved(
                    if (out.sdReturned) "Deposit returned — reported. The office settles it."
                    else "Deposit kept" +
                        (out.damageCharges.takeIf { it > 0 }?.let { ", damage " + rupees(it) } ?: ", no damage") +
                        " — reported. The office settles it.",
                )
                load()
            } catch (e: HttpException) {
                saveError = e.readable("The server answered ${e.code()} — the report was not saved.")
            } catch (e: IOException) {
                saveError = "No signal — the report was not saved. The vehicle stays on this list."
            } catch (e: Exception) {
                saveError = e.message ?: "Could not save the report"
            } finally {
                saving = false
            }
        }
    }

    /** The server's `detail` verbatim when there is one — its sentences are
     *  written for the person reading them. */
    private fun Throwable.readable(fallback: String): String = when (this) {
        is HttpException -> runCatching {
            json.decodeFromString(ApiError.serializer(), response()?.errorBody()?.string().orEmpty()).detail
        }.getOrNull() ?: fallback
        is IOException -> "No signal — this one needs the server."
        else -> message ?: fallback
    }
}

/* ── The card: vehicles taken back, deposits not yet answered ─────────────── */

/**
 * At the top of the EVs tab, because that is where the vehicle was taken back
 * and so where somebody will be when they remember. It stays on screen when
 * it is empty: a section that only appears when there is a problem is a
 * section nobody trusts to have been checked.
 */
@Composable
fun CloseoutsCard(vm: CloseoutsViewModel, onAnswer: (CloseoutRow) -> Unit) {
    val waiting = vm.rows.count { it.report == null }

    Column(
        Modifier.fillMaxWidth().background(Qwik.Surface).padding(horizontal = 20.dp, vertical = 14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Kicker("Deposits to report", Modifier.weight(1f))
            if (waiting > 0) {
                Text(
                    waiting.toString(),
                    style = MaterialTheme.typography.headlineSmall,
                    color = Qwik.Accent,
                )
            }
        }
        Spacer(Modifier.height(10.dp))

        // Rows first: a list already on the phone is worth more than a fresh
        // complaint about the network, so a failed refresh becomes a line
        // under what is there rather than replacing it.
        when {
            vm.rows.isNotEmpty() -> Column(Modifier.fillMaxWidth()) {
                Text(
                    "You took these back. The office settles the money; it needs your answer first.",
                    style = MaterialTheme.typography.bodySmall,
                    color = Qwik.N700,
                )
                Spacer(Modifier.height(6.dp))
                vm.rows.forEach { row ->
                    CloseoutListRow(row, onAnswer = { onAnswer(row) })
                }
            }
            vm.loadError != null -> Column(Modifier.fillMaxWidth()) {
                Text(vm.loadError!!, style = MaterialTheme.typography.bodyMedium, color = Qwik.Accent700)
                GhostAction("Try again", onClick = vm::load)
            }
            !vm.loaded -> Text(
                "Looking for vehicles you took back…",
                style = MaterialTheme.typography.bodyMedium,
                color = Qwik.N700,
            )
            else -> Text(
                "Nothing waiting — every EV you took back has its deposit answered.",
                style = MaterialTheme.typography.bodyMedium,
                color = Qwik.N700,
            )
        }
        if (vm.rows.isNotEmpty() && vm.loadError != null) {
            Spacer(Modifier.height(8.dp))
            Text(vm.loadError!!, style = MaterialTheme.typography.bodySmall, color = Qwik.Accent700)
        }
    }
}

@Composable
private fun CloseoutListRow(row: CloseoutRow, onAnswer: () -> Unit) {
    val report = row.report
    Column(Modifier.fillMaxWidth().clickable(onClick = onAnswer).padding(vertical = 10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    row.name ?: ("Person " + row.personId),
                    style = MaterialTheme.typography.titleLarge,
                    color = Qwik.Ink,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    evLine(row),
                    style = MaterialTheme.typography.bodyMedium,
                    color = Qwik.N700,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Spacer(Modifier.width(10.dp))
            if (report == null) {
                GhostAction("Answer", onClick = onAnswer)
            } else {
                Tag(if (report.sdReturned) "returned" else "kept", accent = !report.sdReturned)
            }
        }
        if (report != null) {
            Spacer(Modifier.height(2.dp))
            Text(
                answerLine(report) + " · tap to correct",
                style = MaterialTheme.typography.bodySmall,
                color = Qwik.N800,
            )
        }
        Spacer(Modifier.height(10.dp))
        Hairline()
    }
}

/** "CBICEVD0244 · Zypp Ather · back 4 Sep" */
private fun evLine(row: CloseoutRow): String = listOfNotNull(
    row.evId,
    listOfNotNull(row.provider, row.model).joinToString(" ").ifBlank { null },
    row.returnedDate?.let { "back " + shortDate(it) },
).joinToString(" · ")

/** What was said last time, in the words the recruiter would use. */
private fun answerLine(report: CloseoutReport): String = if (report.sdReturned) {
    "Deposit went back to the rider"
} else {
    listOfNotNull(
        "Deposit kept",
        report.damageCharges.takeIf { it > 0 }?.let { "damage " + rupees(it) } ?: "no damage",
        report.damageNote?.takeIf { it.isNotBlank() },
    ).joinToString(" · ")
}

/* ── The sheet and the question itself ───────────────────────────────────── */

/** The same question the return raises, asked again later from the card. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CloseoutSheet(
    row: CloseoutRow,
    onDone: (String) -> Unit,
    onDismiss: () -> Unit,
    vm: CloseoutsViewModel = hiltViewModel(),
) {
    val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    LaunchedEffect(row.assignmentId) { vm.clearSaveError() }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheet, containerColor = Qwik.Bg) {
        Column(Modifier.fillMaxWidth().imePadding().padding(horizontal = 20.dp).padding(bottom = 24.dp)) {
            CloseoutForm(
                row = row,
                busy = vm.saving,
                error = vm.saveError,
                skipLabel = if (row.report == null) "Later" else "Leave it as it is",
                onSkip = onDismiss,
                onSubmit = { sdReturned, charges, damageNote ->
                    vm.save(row.assignmentId, sdReturned, charges, damageNote, onDone)
                },
            )
        }
    }
}

/**
 * Two questions and a way out.
 *
 * Nothing is selected until somebody selects it — a Yes that was there when
 * the sheet opened is a default masquerading as an answer, and this one is
 * about money. "Later" is a first-class button, not a dismissal: a recruiter
 * with a rider waiting must be able to leave, and the vehicle simply stays on
 * the list until somebody has a minute.
 */
@Composable
fun CloseoutForm(
    row: CloseoutRow,
    busy: Boolean,
    error: String?,
    skipLabel: String,
    onSkip: () -> Unit,
    onSubmit: (Boolean, Double, String) -> Unit,
) {
    val existing = row.report
    // null until it is answered — Segmented shows nothing selected at -1.
    var returned by remember(row.assignmentId) { mutableStateOf(existing?.sdReturned) }
    var charges by remember(row.assignmentId) {
        mutableStateOf(existing?.damageCharges?.takeIf { it > 0 }?.let { Math.round(it).toString() } ?: "")
    }
    var damageNote by remember(row.assignmentId) { mutableStateOf(existing?.damageNote.orEmpty()) }

    Column(Modifier.fillMaxWidth()) {
        Text("Security deposit", style = MaterialTheme.typography.headlineLarge, color = Qwik.Ink)
        Spacer(Modifier.height(6.dp))
        Kicker(listOfNotNull(row.name, evLine(row)).joinToString(" · "))
        Spacer(Modifier.height(16.dp))

        Text(
            "Did the deposit go back to the rider?",
            style = MaterialTheme.typography.titleLarge,
            color = Qwik.Ink,
        )
        Spacer(Modifier.height(8.dp))
        Segmented(
            listOf("Yes", "No"),
            selected = when (returned) {
                true -> 0
                false -> 1
                else -> -1 // unanswered: Segmented highlights nothing
            },
            onSelect = { returned = it == 0 },
            modifier = Modifier.fillMaxWidth(),
        )

        // Hidden, not merely ignored, when the deposit went back: the server
        // refuses that pair outright, so there is nothing to type here.
        if (returned == false) {
            Spacer(Modifier.height(16.dp))
            Kicker("Damage charged against it")
            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("₹", style = MaterialTheme.typography.headlineSmall, color = Qwik.N700)
                Spacer(Modifier.width(10.dp))
                OutlinedTextField(
                    value = charges,
                    onValueChange = { text -> charges = text.filter { c -> c.isDigit() }.take(6) },
                    placeholder = { Text("0", color = Qwik.N600, maxLines = 1) },
                    singleLine = true,
                    // Whole rupees, number pad, and non-digits dropped as they
                    // are typed — the same rule the odometer field uses.
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    colors = fieldColors(),
                    modifier = Modifier.weight(1f),
                )
            }
            Spacer(Modifier.height(4.dp))
            Text(
                "Nothing broken? Leave it at 0.",
                style = MaterialTheme.typography.bodySmall,
                color = Qwik.N700,
            )
            Spacer(Modifier.height(14.dp))
            Kicker("What was wrong with it?")
            Spacer(Modifier.height(6.dp))
            OutlinedTextField(
                value = damageNote,
                onValueChange = { damageNote = it.take(200) },
                placeholder = { Text("e.g. cracked front panel", color = Qwik.N600, maxLines = 1) },
                singleLine = true,
                colors = fieldColors(),
                modifier = Modifier.fillMaxWidth(),
            )
        }

        // The server's answer, verbatim, under the fields it is about.
        if (error != null) {
            Spacer(Modifier.height(10.dp))
            Text(error, style = MaterialTheme.typography.bodySmall, color = Qwik.Accent700)
        }

        Spacer(Modifier.height(14.dp))
        Text(
            "This is a report, not a charge — the office settles the deposit.",
            style = MaterialTheme.typography.bodySmall,
            color = Qwik.N700,
        )
        Spacer(Modifier.height(10.dp))
        BarButton(
            when {
                busy -> "Saving…"
                existing != null -> "Correct the report"
                else -> "Save the report"
            },
            onClick = {
                // Yes means the deposit went back whole: no charge, no note.
                returned?.let { answered ->
                    if (answered) onSubmit(true, 0.0, "")
                    else onSubmit(false, charges.toDoubleOrNull() ?: 0.0, damageNote)
                }
            },
            enabled = !busy && returned != null,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(4.dp))
        GhostAction(skipLabel, onClick = onSkip, enabled = !busy)
    }
}
