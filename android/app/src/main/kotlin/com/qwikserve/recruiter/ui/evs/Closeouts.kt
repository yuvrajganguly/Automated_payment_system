package com.qwikserve.recruiter.ui.evs

import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
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
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import coil.compose.AsyncImage
import com.qwikserve.recruiter.BuildConfig
import com.qwikserve.recruiter.data.api.ApiError
import com.qwikserve.recruiter.data.api.CloseoutReport
import com.qwikserve.recruiter.data.api.CloseoutReportIn
import com.qwikserve.recruiter.data.api.CloseoutRow
import com.qwikserve.recruiter.data.api.PayoutApi
import com.qwikserve.recruiter.data.repo.PhotoRepository
import com.qwikserve.recruiter.ui.common.BarButton
import com.qwikserve.recruiter.ui.common.GhostAction
import com.qwikserve.recruiter.ui.common.Hairline
import com.qwikserve.recruiter.ui.common.Kicker
import com.qwikserve.recruiter.ui.common.PhotoTile
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
 *
 * The damage photo follows the report, never the other way round: the
 * assessment is the claim and the picture is only evidence for it, and the
 * server refuses a photo (404) until a report exists to hang it on. So a
 * picture chosen before the save is **held**, not sent and lost, and goes up
 * the moment the save lands.
 */
@HiltViewModel
class CloseoutsViewModel @Inject constructor(
    private val api: PayoutApi,
    private val photos: PhotoRepository,
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

    /** A damage photo chosen on the phone that is not on the server yet, and
     *  the assignment it belongs to. It survives a "Later": a picture taken of
     *  a vehicle that has already gone back cannot be taken again. */
    var heldPhoto by mutableStateOf<Uri?>(null)
        private set
    var heldPhotoFor by mutableStateOf<Long?>(null)
        private set

    /** True once that picture is on the server. It is kept on screen after it
     *  lands — the row in hand still says `has_photo: false` until the list
     *  reloads, and a tile that empties itself on success reads as a failure. */
    var photoLanded by mutableStateOf(false)
        private set
    var uploading by mutableStateOf(false)
        private set

    /** Why the last upload did not land — the server's sentence when it sent
     *  one (a 415, an over-size file), ours when there was no answer at all. */
    var photoError by mutableStateOf<String?>(null)
        private set

    /** Bumped when a picture lands, so the tiles re-fetch the server's copy
     *  instead of showing the one Coil already has cached for that URL. */
    var photoVersion by mutableStateOf(0)
        private set

    /** Assignments known to carry a report now — they arrived with one, or we
     *  just saved one. Below that, the photo endpoint is a 404. */
    private val reportedIds = mutableSetOf<Long>()

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
                reportedIds += assignmentId
                val said =
                    if (out.sdReturned) "Deposit returned — reported. The office settles it."
                    else "Deposit kept" +
                        (out.damageCharges.takeIf { it > 0 }?.let { ", damage " + rupees(it) } ?: ", no damage") +
                        " — reported. The office settles it."
                // A deposit that went back whole has no damage to photograph,
                // so a picture chosen before the answer changed is dropped
                // rather than quietly filed against nothing.
                if (sdReturned && heldPhotoFor == assignmentId) dropHeldPhoto()
                // The report first, the photo after it — that is the whole
                // ordering. If the picture does not go up, the sheet stays
                // where it is with the reason and a retry: the figure is on
                // the server by now, so nobody types it a second time.
                val held = heldPhoto?.takeIf { heldPhotoFor == assignmentId && !photoLanded }
                if (held != null && !sendPhoto(assignmentId, held)) {
                    load()
                    return@launch
                }
                onSaved(said)
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

    /* ── The damage photo ── */

    /**
     * A picture chosen for [assignmentId]. If the report is already on the
     * server — [reported] from the row in hand, or one we saved a moment ago —
     * it goes up now; otherwise it waits for the save, which sends it. Either
     * way it is held, so nothing a recruiter photographed is thrown away.
     */
    fun pickPhoto(assignmentId: Long, uri: Uri, reported: Boolean) {
        heldPhoto = uri
        heldPhotoFor = assignmentId
        photoLanded = false
        photoError = null
        if (reported || assignmentId in reportedIds) uploadHeld(assignmentId, uri)
    }

    /** Try the picture again after a failed upload. It asks for nothing that
     *  was already typed: the report, and the damage figure in it, are saved. */
    fun retryPhoto() {
        val uri = heldPhoto ?: return
        val id = heldPhotoFor ?: return
        if (photoLanded) return
        uploadHeld(id, uri)
    }

    /** Give up on the held picture — the report keeps whatever it had. */
    fun dropHeldPhoto() {
        heldPhoto = null
        heldPhotoFor = null
        photoLanded = false
        photoError = null
    }

    private fun uploadHeld(assignmentId: Long, uri: Uri) {
        if (uploading || saving) return
        viewModelScope.launch { if (sendPhoto(assignmentId, uri)) load() }
    }

    /** The upload itself. It never throws: a photo that did not go up is a
     *  sentence and a retry, never a report lost on the way. */
    private suspend fun sendPhoto(assignmentId: Long, uri: Uri): Boolean {
        uploading = true
        photoError = null
        return try {
            photos.uploadCloseoutPhoto(assignmentId, uri)
            photoLanded = true
            photoVersion++
            true
        } catch (e: HttpException) {
            // 415 for a file that is not a picture, 413 over 8 MB, 404 for a
            // report that is not there — the server's own words, as sent.
            photoError = e.readable("The report is saved. The photo did not go up — the server answered ${e.code()}.")
            false
        } catch (e: IOException) {
            photoError = "The report is saved. The photo did not go up — no signal."
            false
        } catch (e: Exception) {
            photoError = e.message ?: "The report is saved. The photo did not go up."
            false
        } finally {
            uploading = false
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
                    CloseoutListRow(row, version = vm.photoVersion, onAnswer = { onAnswer(row) })
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
        // A photo that did not go up after the sheet closed. The report is on
        // the server; this is the picture, and it is still on the phone.
        if (vm.photoError != null && vm.heldPhoto != null) {
            Spacer(Modifier.height(8.dp))
            Text(vm.photoError!!, style = MaterialTheme.typography.bodySmall, color = Qwik.Accent700)
            Row(verticalAlignment = Alignment.CenterVertically) {
                GhostAction("Send the photo again", onClick = vm::retryPhoto, enabled = !vm.uploading)
                Spacer(Modifier.width(16.dp))
                GhostAction("Drop it", onClick = vm::dropHeldPhoto, color = Qwik.N700, enabled = !vm.uploading)
            }
        }
    }
}

@Composable
private fun CloseoutListRow(row: CloseoutRow, version: Int, onAnswer: () -> Unit) {
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
            // The damage, when there is a picture of it: small, but there —
            // an answer with evidence behind it should look different from one
            // without, on the list and not only inside the sheet.
            if (report?.hasPhoto == true) {
                DamageThumb(row.assignmentId, version)
                Spacer(Modifier.width(10.dp))
            }
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

/** The quiet line beside the photo tile: what is happening to the picture. */
@Composable
private fun PhotoNote(text: String) {
    Text(text, style = MaterialTheme.typography.bodySmall, color = Qwik.N700)
}

/**
 * The damage photo on a list row. It loads through Coil, which is wired to the
 * API's own OkHttp client in [com.qwikserve.recruiter.QwikApp], so the bearer
 * token rides along; a picture that is not there yet is a grey square, never a
 * broken one. Tapping the row opens the sheet, where it can be replaced.
 */
@Composable
private fun DamageThumb(assignmentId: Long, version: Int) {
    Box(
        Modifier.size(44.dp).background(Qwik.N200).border(1.dp, Qwik.N400),
        contentAlignment = Alignment.Center,
    ) {
        AsyncImage(
            // The ?v= is Coil's cache, not the server's: without it a replaced
            // photo keeps showing the one it fetched an hour ago.
            model = closeoutPhotoUrl(assignmentId) + (if (version > 0) "?v=$version" else ""),
            contentDescription = "Damage photo",
            contentScale = ContentScale.Crop,
            modifier = Modifier.size(44.dp),
        )
    }
}

/** The server's copy of the damage photo. Bare — [PhotoTile] adds its own
 *  cache-busting `v` the way the rider and dash photos have it. */
private fun closeoutPhotoUrl(assignmentId: Long): String =
    BuildConfig.API_BASE_URL + "evs/closeouts/" + assignmentId + "/photo"

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
        if (report.hasPhoto) "photo" else null,
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
                photo = vm.heldPhoto?.takeIf { vm.heldPhotoFor == row.assignmentId },
                photoLanded = vm.photoLanded && vm.heldPhotoFor == row.assignmentId,
                photoUploading = vm.uploading && vm.heldPhotoFor == row.assignmentId,
                photoError = vm.photoError?.takeIf { vm.heldPhotoFor == row.assignmentId },
                photoVersion = vm.photoVersion,
                onPhoto = { uri -> vm.pickPhoto(row.assignmentId, uri, row.report != null) },
                onRetryPhoto = vm::retryPhoto,
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
 *
 * The photo tile appears with the damage fields and for the same reason: a
 * deposit that went back whole has nothing to photograph. It is the last
 * thing here rather than the first because it is the last thing to happen —
 * the report saves, and then the picture follows it up.
 */
@Composable
fun CloseoutForm(
    row: CloseoutRow,
    busy: Boolean,
    error: String?,
    skipLabel: String,
    onSkip: () -> Unit,
    photo: Uri?,
    photoLanded: Boolean,
    photoUploading: Boolean,
    photoError: String?,
    photoVersion: Int,
    onPhoto: (Uri) -> Unit,
    onRetryPhoto: () -> Unit,
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

            Spacer(Modifier.height(14.dp))
            Kicker("Photo of the damage")
            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.Top) {
                PhotoTile(
                    picked = photo,
                    url = if (existing?.hasPhoto == true) closeoutPhotoUrl(row.assignmentId) else null,
                    size = 76.dp,
                    busy = photoUploading,
                    version = photoVersion,
                    label = "Damage photo",
                    onPicked = onPhoto,
                )
                Spacer(Modifier.width(14.dp))
                Column(Modifier.weight(1f).padding(top = 2.dp)) {
                    when {
                        photoUploading -> PhotoNote("Going up now.")
                        // The server's own words when it sent any, and a way
                        // to try again that asks for nothing already typed.
                        photoError != null -> {
                            Text(
                                photoError,
                                style = MaterialTheme.typography.bodySmall,
                                color = Qwik.Accent700,
                            )
                            GhostAction(
                                "Send the photo again",
                                onClick = onRetryPhoto,
                                enabled = !busy,
                            )
                        }
                        photoLanded -> PhotoNote("Saved with the report.")
                        // Held, because there is nothing on the server to hang
                        // it on yet. Saying so is the difference between
                        // waiting and disappearing.
                        photo != null -> PhotoNote("It goes up when you save the report.")
                        existing?.hasPhoto == true -> PhotoNote("A photo is attached. Tap it to replace it.")
                        else -> PhotoNote(
                            "Optional. The office settles the deposit from this report, and a picture is what it has to go on.",
                        )
                    }
                }
            }
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
