package com.qwikserve.recruiter.ui.today

import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qwikserve.recruiter.BuildConfig
import com.qwikserve.recruiter.data.api.ApiError
import com.qwikserve.recruiter.data.api.PayoutApi
import com.qwikserve.recruiter.data.api.ShiftIn
import com.qwikserve.recruiter.data.api.ShiftOut
import com.qwikserve.recruiter.data.repo.PhotoRepository
import com.qwikserve.recruiter.ui.common.BarButton
import com.qwikserve.recruiter.ui.common.GhostAction
import com.qwikserve.recruiter.ui.common.Kicker
import com.qwikserve.recruiter.ui.common.PhotoTile
import com.qwikserve.recruiter.ui.common.km
import com.qwikserve.recruiter.ui.login.fieldColors
import com.qwikserve.recruiter.ui.theme.Qwik
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import retrofit2.HttpException
import java.io.IOException
import javax.inject.Inject

/**
 * The odometer at the two ends of a day.
 *
 * The order is deliberate and it is the same one the onboarding form uses:
 * **the reading is saved first, the photo goes up after**. The number is the
 * claim, the picture is only the evidence for it, and a recruiter standing
 * outside a store on one bar of signal must never lose the number because an
 * upload timed out. A failed upload keeps the file and offers a retry; the
 * reading is already on the server by then.
 *
 * The server's own doubts come back in `warnings` — an opening below
 * yesterday's close, an improbable day — and they are shown as a notice, never
 * as a refusal. Vehicles get swapped, and a recruiter who cannot record their
 * day is a recruiter who stops recording days.
 */
@HiltViewModel
class ShiftViewModel @Inject constructor(
    private val api: PayoutApi,
    private val photos: PhotoRepository,
    private val json: Json,
) : ViewModel() {
    var shift by mutableStateOf<ShiftOut?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var warnings by mutableStateOf<List<String>>(emptyList())
        private set
    var busy by mutableStateOf(false)
        private set

    /** What is typed into each field. Digits only — kilometres are whole. */
    var startReading by mutableStateOf("")
        private set
    var endReading by mutableStateOf("")
        private set

    /** A picture chosen but not yet on the server, per half of the day. */
    var startPhoto by mutableStateOf<Uri?>(null)
        private set
    var endPhoto by mutableStateOf<Uri?>(null)
        private set
    var photoError by mutableStateOf<String?>(null)
        private set
    var uploading by mutableStateOf(false)
        private set
    /** Bumped after an upload lands so the tile re-fetches the server's copy. */
    var photoVersion by mutableStateOf(0)
        private set

    init { load() }

    fun load() {
        if (loading) return
        loading = true
        viewModelScope.launch {
            try {
                shift = api.shiftToday()
                error = null
            } catch (e: IOException) {
                if (shift == null) error = "Can't reach the server — your reading needs it."
            } catch (e: Exception) {
                error = e.message ?: "Could not load today's odometer"
            } finally {
                loading = false
            }
        }
    }

    fun onReading(kind: String, text: String) {
        val digits = text.filter { it.isDigit() }.take(7)
        if (kind == "start") startReading = digits else endReading = digits
    }

    fun pickPhoto(kind: String, uri: Uri) {
        if (kind == "start") startPhoto = uri else endPhoto = uri
        photoError = null
        // If that half's reading is already saved the photo can go now;
        // otherwise it waits for the reading, and rides along with it.
        val s = shift
        val saved = if (kind == "start") s?.startKm != null else s?.endKm != null
        if (saved && s != null) upload(kind, uri, s.day)
    }

    /** Save one end of the shift. */
    fun save(kind: String) {
        if (busy) return
        val typed = if (kind == "start") startReading else endReading
        val value = typed.toIntOrNull()
        if (value == null) {
            error = "Type the reading in whole kilometres — digits only."
            return
        }
        busy = true; error = null; warnings = emptyList()
        viewModelScope.launch {
            try {
                val out = api.saveShift(ShiftIn(kind = kind, km = value))
                shift = out
                warnings = out.warnings
                if (kind == "start") startReading = "" else endReading = ""
                val pending = if (kind == "start") startPhoto else endPhoto
                if (pending != null) upload(kind, pending, out.day)
            } catch (e: HttpException) {
                error = detail(e) ?: "The server answered ${e.code()}."
            } catch (e: IOException) {
                error = "No signal — the reading has not been saved. Try again in a moment."
            } catch (e: Exception) {
                error = e.message ?: "Could not save the reading"
            } finally {
                busy = false
            }
        }
    }

    /** Retry after a failed upload — the reading is already saved, so this
     *  never asks anyone to type a number twice. */
    fun retryPhoto(kind: String) {
        val s = shift ?: return
        val uri = (if (kind == "start") startPhoto else endPhoto) ?: return
        upload(kind, uri, s.day)
    }

    private fun upload(kind: String, uri: Uri, day: String) {
        if (uploading) return
        uploading = true; photoError = null
        viewModelScope.launch {
            runCatching { photos.uploadShiftPhoto(kind, day, uri) }
                .onSuccess {
                    photoVersion++
                    if (kind == "start") startPhoto = null else endPhoto = null
                    runCatching { shift = api.shiftToday() }
                }
                .onFailure {
                    photoError = "The reading is saved, but the photo did not upload."
                }
            uploading = false
        }
    }

    private fun detail(e: HttpException): String? = runCatching {
        json.decodeFromString(ApiError.serializer(), e.response()?.errorBody()?.string().orEmpty()).detail
    }.getOrNull()
}

/**
 * Today's odometer, at the top of the Today tab because it is the first and
 * last thing a recruiter does with the app each day: start the shift, end the
 * shift, see the distance.
 */
@Composable
fun ShiftCard(vm: ShiftViewModel = hiltViewModel()) {
    val s = vm.shift
    val day = s?.day ?: ""
    Column(Modifier.fillMaxWidth().background(Qwik.Surface).padding(horizontal = 20.dp, vertical = 14.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Kicker("Odometer", Modifier.weight(1f))
            if (s != null && s.complete) {
                Text(km(s.distanceKm), style = MaterialTheme.typography.headlineSmall, color = Qwik.Accent)
            }
        }
        Spacer(Modifier.height(10.dp))

        when {
            s == null && vm.loading -> Text(
                "Loading today's reading…",
                style = MaterialTheme.typography.bodyMedium, color = Qwik.N700,
            )
            s == null -> Text(
                vm.error ?: "Today's odometer is not available right now.",
                style = MaterialTheme.typography.bodyMedium, color = Qwik.Accent700,
            )
            s.startKm == null -> ReadingForm(
                title = "Start your shift",
                hint = "The reading on the dash before you set off.",
                value = vm.startReading,
                onValue = { vm.onReading("start", it) },
                action = if (vm.busy) "Saving…" else "Save opening reading",
                onAction = { vm.save("start") },
                busy = vm.busy,
                photo = vm.startPhoto,
                uploading = vm.uploading,
                version = vm.photoVersion,
                onPhoto = { vm.pickPhoto("start", it) },
            )
            s.endKm == null -> Column {
                Recorded(
                    label = "Opened at",
                    value = s.startKm,
                    at = s.startAt,
                    hasPhoto = s.hasStartPhoto,
                    day = day,
                    kind = "start",
                    version = vm.photoVersion,
                    onPicked = { vm.pickPhoto("start", it) },
                )
                Spacer(Modifier.height(14.dp))
                ReadingForm(
                    title = "End your shift",
                    hint = "The reading when you park for the day.",
                    value = vm.endReading,
                    onValue = { vm.onReading("end", it) },
                    action = if (vm.busy) "Saving…" else "Save closing reading",
                    onAction = { vm.save("end") },
                    busy = vm.busy,
                    photo = vm.endPhoto,
                    uploading = vm.uploading,
                    version = vm.photoVersion,
                    onPhoto = { vm.pickPhoto("end", it) },
                )
            }
            else -> Column {
                Text(
                    "${s.startKm} → ${s.endKm} km",
                    style = MaterialTheme.typography.titleLarge, color = Qwik.Ink,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    "The day is closed. The month's total is what the fuel claim is paid on.",
                    style = MaterialTheme.typography.bodySmall, color = Qwik.N700,
                )
                Spacer(Modifier.height(12.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    ShiftPhoto("Start", day, "start", s.hasStartPhoto, vm.photoVersion) { vm.pickPhoto("start", it) }
                    ShiftPhoto("End", day, "end", s.hasEndPhoto, vm.photoVersion) { vm.pickPhoto("end", it) }
                }
            }
        }

        // The server's soft doubts: shown, never blocking.
        vm.warnings.forEach { w ->
            Spacer(Modifier.height(10.dp))
            Row(Modifier.fillMaxWidth()) {
                Box(Modifier.width(3.dp).height(34.dp).background(Qwik.Accent))
                Spacer(Modifier.width(10.dp))
                Text(w, style = MaterialTheme.typography.bodySmall, color = Qwik.N800)
            }
        }
        if (s != null && vm.error != null) {
            Spacer(Modifier.height(8.dp))
            Text(vm.error!!, style = MaterialTheme.typography.bodySmall, color = Qwik.Accent700)
        }
        if (vm.photoError != null) {
            Spacer(Modifier.height(8.dp))
            Text(vm.photoError!!, style = MaterialTheme.typography.bodySmall, color = Qwik.Accent700)
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                if (vm.startPhoto != null) GhostAction("Retry opening photo", onClick = { vm.retryPhoto("start") })
                if (vm.endPhoto != null) GhostAction("Retry closing photo", onClick = { vm.retryPhoto("end") })
            }
        }
    }
}

/** One end of the day: a number field, a photo tile and one button. */
@Composable
private fun ReadingForm(
    title: String,
    hint: String,
    value: String,
    onValue: (String) -> Unit,
    action: String,
    onAction: () -> Unit,
    busy: Boolean,
    photo: Uri?,
    uploading: Boolean,
    version: Int,
    onPhoto: (Uri) -> Unit,
) {
    Column(Modifier.fillMaxWidth()) {
        Text(title, style = MaterialTheme.typography.titleLarge, color = Qwik.Ink)
        Spacer(Modifier.height(2.dp))
        Text(hint, style = MaterialTheme.typography.bodySmall, color = Qwik.N700)
        Spacer(Modifier.height(10.dp))
        Row(verticalAlignment = Alignment.Top) {
            PhotoTile(
                picked = photo,
                size = 76.dp,
                busy = uploading,
                version = version,
                label = "Dash photo",
                onPicked = onPhoto,
            )
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(
                        value = value,
                        onValueChange = onValue,
                        placeholder = { Text("e.g. 12340", color = Qwik.N600, maxLines = 1) },
                        singleLine = true,
                        // Whole kilometres: a number pad, and onValue keeps
                        // only the digits whatever the keyboard sends.
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        colors = fieldColors(),
                        modifier = Modifier.weight(1f),
                    )
                    Spacer(Modifier.width(8.dp))
                    Text("km", style = MaterialTheme.typography.bodyLarge, color = Qwik.N700)
                }
            }
        }
        Spacer(Modifier.height(12.dp))
        BarButton(action, onClick = onAction, enabled = !busy && value.isNotBlank(), modifier = Modifier.fillMaxWidth())
    }
}

/** A reading that is already on the server, with its dash photo beside it —
 *  still tappable, because a picture can be added or replaced afterwards. */
@Composable
private fun Recorded(
    label: String,
    value: Int?,
    at: String?,
    hasPhoto: Boolean,
    day: String,
    kind: String,
    version: Int,
    onPicked: (Uri) -> Unit,
) {
    Row(verticalAlignment = Alignment.Top) {
        Column(Modifier.weight(1f).padding(top = 2.dp)) {
            Kicker(label)
            Spacer(Modifier.height(3.dp))
            Text(km(value), style = MaterialTheme.typography.titleLarge, color = Qwik.Ink)
            Text(
                listOfNotNull(
                    at?.let { Regex("""\d{2}:\d{2}""").find(it)?.value },
                    if (hasPhoto) "photo saved" else "no photo yet",
                ).joinToString(" · "),
                style = MaterialTheme.typography.bodySmall,
                color = if (hasPhoto) Qwik.N700 else Qwik.Accent700,
            )
        }
        Spacer(Modifier.width(12.dp))
        PhotoTile(
            picked = null,
            url = if (hasPhoto) shiftPhotoUrl(day, kind) else null,
            size = 60.dp,
            version = version,
            label = "Dash",
            onPicked = onPicked,
        )
    }
}

@Composable
private fun ShiftPhoto(
    label: String,
    day: String,
    kind: String,
    hasPhoto: Boolean,
    version: Int,
    onPicked: (Uri) -> Unit,
) {
    Column {
        Kicker(label)
        Spacer(Modifier.height(6.dp))
        PhotoTile(
            picked = null,
            url = if (hasPhoto) shiftPhotoUrl(day, kind) else null,
            size = 72.dp,
            version = version,
            label = "Dash photo",
            onPicked = onPicked,
        )
    }
}

private fun shiftPhotoUrl(day: String, kind: String): String =
    BuildConfig.API_BASE_URL + "recruiters/me/shift/photo?kind=" + kind + "&day=" + day
