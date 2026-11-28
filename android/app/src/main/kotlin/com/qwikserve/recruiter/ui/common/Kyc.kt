package com.qwikserve.recruiter.ui.common

import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import coil.compose.SubcomposeAsyncImage
import com.qwikserve.recruiter.BuildConfig
import com.qwikserve.recruiter.ui.theme.Qwik

/**
 * One identity or bank document — Aadhaar, PAN, passbook — on the onboarding
 * form. The number and the photo are both taken, not one or the other: type
 * what can be typed, and photograph the card as the proof. Either may be left
 * for later.
 *
 * The photo is not drawn on the form: a line says whether one is attached,
 * with Camera / Gallery / Remove beside it. Somebody's Aadhaar should not sit
 * on a recruiter's screen any longer than it takes to photograph it.
 */
@Composable
fun KycField(
    label: String,
    photo: Uri?,
    onPhoto: (Uri?) -> Unit,
    number: @Composable () -> Unit,
) {
    val picker = rememberPhotoPicker { onPhoto(it) }
    Column(Modifier.fillMaxWidth()) {
        number()
        Row(
            Modifier.fillMaxWidth().padding(top = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text(
                if (photo != null) "✓ Photo attached" else "$label photo",
                style = MaterialTheme.typography.bodySmall,
                color = if (photo != null) Qwik.Ink else Qwik.N700,
                modifier = Modifier.weight(1f),
            )
            GhostAction(if (photo != null) "Retake" else "Camera", onClick = picker.takePhoto)
            GhostAction("Gallery", onClick = picker.chooseFromGallery)
            if (photo != null) GhostAction("Remove", onClick = { onPhoto(null) }, color = Qwik.N700)
        }
    }
}

/**
 * A stored document on a rider's page, as a link rather than a picture: the
 * label, "View" when there is one (opens it full screen, on request), and
 * Camera / Gallery to add or replace it.
 */
@Composable
fun DocumentLink(
    label: String,
    docId: Long?,
    onPicked: (Uri) -> Unit,
    busy: Boolean = false,
) {
    val picker = rememberPhotoPicker(onPicked)
    var viewing by remember { mutableStateOf(false) }
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Column(Modifier.weight(1f)) {
            Text(label, style = MaterialTheme.typography.bodyLarge, color = Qwik.Ink)
            Text(
                when {
                    busy -> "Uploading…"
                    docId != null -> "Photo on file"
                    else -> "No photo yet"
                },
                style = MaterialTheme.typography.bodySmall,
                color = Qwik.N700,
            )
        }
        if (!busy) {
            if (docId != null) GhostAction("View", onClick = { viewing = true })
            GhostAction(if (docId != null) "Retake" else "Camera", onClick = picker.takePhoto)
            GhostAction("Gallery", onClick = picker.chooseFromGallery)
        }
    }
    if (viewing && docId != null) {
        Dialog(onDismissRequest = { viewing = false }) {
            Column(Modifier.background(Qwik.Bg).padding(12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(label, style = MaterialTheme.typography.titleMedium, color = Qwik.Ink, modifier = Modifier.weight(1f))
                    GhostAction("Close", onClick = { viewing = false })
                }
                Spacer(Modifier.height(8.dp))
                Box(Modifier.fillMaxWidth().heightIn(min = 160.dp, max = 520.dp), contentAlignment = Alignment.Center) {
                    SubcomposeAsyncImage(
                        model = BuildConfig.API_BASE_URL + "documents/$docId/download",
                        contentDescription = label,
                        contentScale = ContentScale.Fit,
                        modifier = Modifier.fillMaxWidth(),
                        loading = { Text("Loading…", color = Qwik.N700) },
                        // A PDF uploaded on the web will not draw here; it is still on file.
                        error = { Text("Can't show this file here — open it on the web.", color = Qwik.N700) },
                    )
                }
            }
        }
    }
}
