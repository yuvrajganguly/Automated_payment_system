package com.qwikserve.recruiter.ui.common

import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import coil.compose.AsyncImage
import coil.compose.SubcomposeAsyncImage
import com.qwikserve.recruiter.ui.theme.Qwik
import java.io.File

/**
 * Taking a rider's photo. Two ways in — the camera, or the phone's picture
 * picker — and neither needs a runtime permission: the camera runs through
 * `ACTION_IMAGE_CAPTURE` (the app never declares CAMERA, so the system does
 * not ask), and the picker hands back one image the user chose without
 * granting access to the rest.
 */
@Immutable
class PhotoPicker(val takePhoto: () -> Unit, val chooseFromGallery: () -> Unit)

@Composable
fun rememberPhotoPicker(onPicked: (Uri) -> Unit): PhotoPicker {
    val context = LocalContext.current
    var pending by remember { mutableStateOf<Uri?>(null) }
    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { saved ->
        if (saved) pending?.let(onPicked)
    }
    val gallery = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        uri?.let(onPicked)
    }
    return remember {
        PhotoPicker(
            takePhoto = {
                val uri = cameraTarget(context)
                pending = uri
                runCatching { camera.launch(uri) }
            },
            chooseFromGallery = {
                runCatching {
                    gallery.launch(
                        PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly),
                    )
                }
            },
        )
    }
}

/** A file in our own cache the camera app may write into, shared by FileProvider. */
private fun cameraTarget(context: Context): Uri {
    val dir = File(context.cacheDir, "photos").apply { mkdirs() }
    val file = File(dir, "rider-${System.currentTimeMillis()}.jpg")
    return FileProvider.getUriForFile(context, context.packageName + ".fileprovider", file)
}

/**
 * The square photo tile used on the onboarding form, a rider's page, the
 * odometer card and the Profile tab: the picture when there is one, otherwise
 * a prompt. Tapping it offers the camera or the gallery.
 *
 * Three ways to show what is already there — a [picked] file the recruiter
 * just chose, a rider's own [personId] thumbnail, or any [url] on the server
 * (a dash photo, a recruiter's face). The first one given wins.
 */
@Composable
fun PhotoTile(
    picked: Uri?,
    personId: Long? = null,
    url: String? = null,
    name: String? = null,
    version: Int = 0,
    size: Dp = 96.dp,
    busy: Boolean = false,
    label: String? = null,
    onPicked: (Uri) -> Unit,
) {
    val picker = rememberPhotoPicker(onPicked)
    var asking by remember { mutableStateOf(false) }
    Column {
        Box(
            Modifier.size(size).background(Qwik.N200).border(1.dp, Qwik.N400)
                .clickable { asking = !asking },
            contentAlignment = Alignment.Center,
        ) {
            when {
                picked != null -> AsyncImage(
                    model = picked,
                    contentDescription = name,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.size(size),
                )
                personId != null -> Avatar(personId, name, size = size, thumb = false, version = version)
                url != null -> SubcomposeAsyncImage(
                    model = if (version > 0) "$url${if (url.contains('?')) "&" else "?"}v=$version" else url,
                    contentDescription = name,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.size(size),
                    loading = { Prompt(label) },
                    error = { Prompt(label) },
                )
                else -> Prompt(label)
            }
        }
        Spacer(Modifier.height(6.dp))
        if (busy) {
            Text("Uploading…", style = MaterialTheme.typography.bodySmall, color = Qwik.N700)
        } else if (asking) {
            Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                GhostAction("Camera", onClick = { asking = false; picker.takePhoto() })
                GhostAction("Gallery", onClick = { asking = false; picker.chooseFromGallery() })
            }
        } else {
            Text(
                if (picked != null || url != null) "Tap to change" else "Tap to add",
                style = MaterialTheme.typography.bodySmall,
                color = Qwik.N600,
                modifier = Modifier.clickable { asking = true }.padding(end = 8.dp).width(size),
            )
        }
    }
}

@Composable
private fun Prompt(label: String?) {
    Text(
        label ?: "Photo",
        style = MaterialTheme.typography.bodySmall,
        color = Qwik.N700,
        textAlign = TextAlign.Center,
        modifier = Modifier.padding(horizontal = 6.dp),
    )
}
