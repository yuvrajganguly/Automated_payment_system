package com.qwikserve.recruiter.ui.common

import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import coil.compose.SubcomposeAsyncImage
import com.qwikserve.recruiter.BuildConfig
import com.qwikserve.recruiter.ui.theme.Qwik

/**
 * One identity document — Aadhaar or PAN — entered either way the recruiter
 * finds quicker in the store: type the number, or photograph the card and let
 * the office read it. The two are alternatives, not both required; a photo
 * stands on its own.
 */
@Composable
fun KycField(
    label: String,
    byPhoto: Boolean,
    onModeChange: (Boolean) -> Unit,
    photo: Uri?,
    onPhoto: (Uri) -> Unit,
    prompt: String = "$label card",
    number: @Composable () -> Unit,
) {
    Column(Modifier.fillMaxWidth()) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(label, style = MaterialTheme.typography.titleMedium, color = Qwik.Ink, modifier = Modifier.weight(1f))
            Segmented(
                listOf("Number", "Photo"),
                selected = if (byPhoto) 1 else 0,
                onSelect = { onModeChange(it == 1) },
                modifier = Modifier.width(176.dp),
            )
        }
        Spacer(Modifier.height(8.dp))
        if (byPhoto) {
            DocumentTile(picked = photo, prompt = prompt, onPicked = onPhoto)
        } else {
            number()
        }
    }
}

/**
 * A card-shaped photo slot for a document. Unlike [PhotoTile] the picture is
 * fitted, not cropped — the point is that every digit on the card can be
 * read, edges included. Camera and Gallery sit under it, one tap each.
 *
 * Shows, in order of preference: a [picked] file not yet uploaded, or the
 * stored document [docId] from the server.
 */
@Composable
fun DocumentTile(
    picked: Uri?,
    prompt: String,
    onPicked: (Uri) -> Unit,
    docId: Long? = null,
    busy: Boolean = false,
    modifier: Modifier = Modifier.fillMaxWidth(),
) {
    val picker = rememberPhotoPicker(onPicked)
    Column(modifier) {
        Box(
            Modifier.fillMaxWidth().height(150.dp).background(Qwik.N200).border(1.dp, Qwik.N400)
                .clickable(enabled = !busy) { picker.takePhoto() },
            contentAlignment = Alignment.Center,
        ) {
            when {
                picked != null -> AsyncImage(
                    model = picked,
                    contentDescription = prompt,
                    contentScale = ContentScale.Fit,
                    modifier = Modifier.fillMaxWidth().height(150.dp),
                )
                docId != null -> SubcomposeAsyncImage(
                    model = BuildConfig.API_BASE_URL + "documents/$docId/download",
                    contentDescription = prompt,
                    contentScale = ContentScale.Fit,
                    modifier = Modifier.fillMaxWidth().height(150.dp),
                    loading = { TilePrompt("Loading…") },
                    // A PDF uploaded on the web will not draw here; it is still on file.
                    error = { TilePrompt("On file (open it on the web)") },
                )
                else -> TilePrompt("Tap to photograph\n$prompt")
            }
        }
        Spacer(Modifier.height(6.dp))
        if (busy) {
            Text("Uploading…", style = MaterialTheme.typography.bodySmall, color = Qwik.N700)
        } else {
            Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                GhostAction(if (picked != null || docId != null) "Retake" else "Camera", onClick = picker.takePhoto)
                GhostAction("Gallery", onClick = picker.chooseFromGallery)
            }
        }
    }
}

@Composable
private fun TilePrompt(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.bodySmall,
        color = Qwik.N700,
        textAlign = TextAlign.Center,
        modifier = Modifier.padding(horizontal = 12.dp),
    )
}
