package com.qwikserve.recruiter.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import coil.compose.SubcomposeAsyncImage
import com.qwikserve.recruiter.BuildConfig
import com.qwikserve.recruiter.ui.theme.QwikColors
import java.text.NumberFormat
import java.util.Locale

/** ₹ with Indian grouping, no paise: ₹1,25,000 */
fun rupees(n: Double?): String {
    val v = n ?: 0.0
    val f = NumberFormat.getIntegerInstance(Locale("en", "IN"))
    return "₹" + f.format(Math.round(v))
}

fun initials(name: String?): String =
    name.orEmpty().trim().split(Regex("\\s+")).filter { it.isNotBlank() }
        .take(2).joinToString("") { it.first().uppercaseChar().toString() }
        .ifBlank { "?" }

/** Rider photo tile: the server thumbnail if there is one, initials otherwise. */
@Composable
fun Avatar(personId: Long, name: String?, size: Dp = 44.dp, thumb: Boolean = true) {
    val url = BuildConfig.API_BASE_URL + "persons/$personId/photo" + if (thumb) "?size=thumb" else ""
    Box(
        modifier = Modifier.size(size).clip(CircleShape).background(MaterialTheme.colorScheme.surfaceVariant),
        contentAlignment = Alignment.Center,
    ) {
        SubcomposeAsyncImage(
            model = url,
            contentDescription = name,
            contentScale = ContentScale.Crop,
            modifier = Modifier.size(size),
            loading = { Initials(name, size) },
            error = { Initials(name, size) },
        )
    }
}

@Composable
private fun Initials(name: String?, size: Dp) {
    Box(Modifier.size(size), contentAlignment = Alignment.Center) {
        Text(
            initials(name),
            style = if (size > 60.dp) MaterialTheme.typography.headlineMedium else MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            fontWeight = FontWeight.Bold,
        )
    }
}

/** Small coloured label: company, status, EV. */
@Composable
fun Pill(text: String, tone: Color = MaterialTheme.colorScheme.primary) {
    Surface(color = tone.copy(alpha = 0.16f), shape = RoundedCornerShape(999.dp)) {
        Text(
            text,
            style = MaterialTheme.typography.labelSmall,
            color = tone,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
        )
    }
}

/** One stat tile: label above value; tone for money that needs attention. */
@Composable
fun StatTile(label: String, value: String, modifier: Modifier = Modifier, tone: Color? = null) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(14.dp),
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 1.dp,
    ) {
        Column(Modifier.padding(12.dp)) {
            Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(
                value,
                style = MaterialTheme.typography.titleLarge,
                color = tone ?: MaterialTheme.colorScheme.onSurface,
                fontWeight = FontWeight.Bold,
            )
        }
    }
}

/** Grey block that stands in for text while it loads. */
@Composable
fun Skeleton(width: Dp, height: Dp = 14.dp) {
    Box(
        Modifier.size(width, height).clip(RoundedCornerShape(6.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant),
    )
}

val Amber = QwikColors.Amber
val Emerald = QwikColors.Emerald
val Rose = QwikColors.Rose

@Composable
fun FullWidthSpacer() = Box(Modifier.fillMaxWidth())
