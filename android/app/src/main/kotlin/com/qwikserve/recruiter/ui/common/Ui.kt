package com.qwikserve.recruiter.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Search
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.SubcomposeAsyncImage
import com.qwikserve.recruiter.BuildConfig
import com.qwikserve.recruiter.ui.theme.Qwik
import java.text.NumberFormat
import java.util.Locale

/* ── formatting ─────────────────────────────────────────────────────────── */

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

private val MONTHS = listOf("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

/** "2026-09-04" / "2026-09-04 11:20:00" → "4 Sep" */
fun shortDate(iso: String?): String {
    val s = iso ?: return ""
    val m = Regex("""(\d{4})-(\d{2})-(\d{2})""").find(s) ?: return s
    return m.groupValues[3].trimStart('0') + " " + MONTHS[m.groupValues[2].toInt() - 1]
}

/** "2026-09-04 11:20:00" → "4 Sep · 11:20" — a timeline row's left column. */
fun shortStamp(iso: String?): String {
    val s = iso ?: return ""
    val clock = Regex("""\d{2}:\d{2}""").find(s)?.value
    val day = shortDate(s)
    return listOfNotNull(day.ifBlank { null }, clock).joinToString(" · ").ifBlank { s }
}

/** "2026-09" → "Sep 2026"; anything else comes back as it arrived. */
fun monthName(bucket: String?): String {
    val m = Regex("""^(\d{4})-(\d{2})$""").find(bucket.orEmpty()) ?: return bucket.orEmpty()
    return MONTHS[m.groupValues[2].toInt() - 1] + " " + m.groupValues[1]
}

/** Whole kilometres with Indian grouping: 1,25,000 km */
fun km(n: Int?): String = NumberFormat.getIntegerInstance(Locale("en", "IN")).format(n ?: 0) + " km"

/* ── the Modernist kit ──────────────────────────────────────────────────── */

/** 2 px ink rule — the design's section divider. */
@Composable
fun Rule(modifier: Modifier = Modifier, color: Color = Qwik.Ink, thickness: Dp = 2.dp) {
    Box(modifier.fillMaxWidth().height(thickness).background(color))
}

/** Hairline between rows. */
@Composable
fun Hairline(modifier: Modifier = Modifier) = Rule(modifier, Qwik.N300, 1.dp)

/** Uppercase tracked section label: "RIDER IDS". */
@Composable
fun Kicker(text: String, modifier: Modifier = Modifier, color: Color = Qwik.N700) {
    Text(
        text.uppercase(),
        style = MaterialTheme.typography.labelMedium,
        color = color,
        modifier = modifier,
    )
}

/** Screen title block: big Archivo title with a small uppercase line under it. */
@Composable
fun Masthead(title: String, sub: String? = null, trailing: (@Composable () -> Unit)? = null) {
    Column {
        Row(
            Modifier.fillMaxWidth().padding(start = 20.dp, end = 12.dp, top = 14.dp, bottom = 12.dp),
            verticalAlignment = Alignment.Bottom,
        ) {
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.headlineLarge, color = Qwik.Ink)
                if (!sub.isNullOrBlank()) {
                    Spacer(Modifier.height(6.dp))
                    Kicker(sub)
                }
            }
            trailing?.invoke()
        }
        Rule()
    }
}

/** Small square tag: company, state. */
@Composable
fun Tag(text: String, accent: Boolean = false, outline: Boolean = false) {
    val bg = when {
        outline -> Color.Transparent
        accent -> Qwik.Accent100
        else -> Qwik.N100
    }
    val fg = when {
        outline -> Qwik.Accent
        accent -> Qwik.Accent800
        else -> Qwik.N800
    }
    Box(
        Modifier.background(bg)
            .then(if (outline) Modifier.border(1.dp, Qwik.Accent) else Modifier)
            .padding(horizontal = 9.dp, vertical = 3.dp),
    ) {
        Text(text, style = MaterialTheme.typography.bodySmall, color = fg, maxLines = 1)
    }
}

/** Ghost text button in the design's uppercase red style: "SNOOZE", "OPEN EV". */
@Composable
fun GhostAction(text: String, onClick: () -> Unit, color: Color = Qwik.Accent, enabled: Boolean = true) {
    Text(
        text.uppercase(),
        style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.ExtraBold),
        color = if (enabled) color else Qwik.N500,
        modifier = Modifier.clickable(enabled = enabled, onClick = onClick).padding(vertical = 8.dp, horizontal = 2.dp),
    )
}

/** Full-width 62 dp bar button at the foot of a screen; primary = red, secondary = outlined. */
@Composable
fun BarButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, primary: Boolean = true, enabled: Boolean = true) {
    val bg = if (primary) (if (enabled) Qwik.Accent else Qwik.N400) else Color.Transparent
    val fg = if (primary) Qwik.Bg else if (enabled) Qwik.Ink else Qwik.N500
    Box(
        modifier.height(62.dp).background(bg).clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(text, style = MaterialTheme.typography.labelLarge.copy(fontSize = 16.sp), color = fg)
    }
}

/** One of the three-up number tiles on Today: big figure, uppercase label. */
@Composable
fun NumberTile(value: String, label: String, modifier: Modifier = Modifier, accent: Boolean = false, onClick: (() -> Unit)? = null) {
    Column(
        modifier.then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 14.dp, vertical = 16.dp),
    ) {
        Text(value, style = MaterialTheme.typography.headlineMedium, color = if (accent) Qwik.Accent else Qwik.Ink)
        Spacer(Modifier.height(6.dp))
        Kicker(label)
    }
}

/** Segmented control in the design's ink-on-bg style. */
@Composable
fun Segmented(options: List<String>, selected: Int, onSelect: (Int) -> Unit, modifier: Modifier = Modifier, counts: List<Int?>? = null) {
    Row(modifier.height(IntrinsicSize.Min).border(1.dp, Qwik.Divider)) {
        options.forEachIndexed { i, label ->
            val on = i == selected
            Row(
                Modifier.weight(1f)
                    .background(if (on) Qwik.Ink else Color.Transparent)
                    .clickable { onSelect(i) }
                    .padding(vertical = 9.dp),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    label,
                    style = MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.SemiBold),
                    color = if (on) Qwik.Bg else Qwik.N800,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                val n = counts?.getOrNull(i)
                if (n != null) {
                    Spacer(Modifier.width(5.dp))
                    Text(n.toString(), style = MaterialTheme.typography.bodySmall, color = if (on) Qwik.N400 else Qwik.N600)
                }
            }
            if (i < options.lastIndex) Box(Modifier.width(1.dp).fillMaxHeight().background(Qwik.Divider))
        }
    }
}

/** Filter chips row (zone: North / South / All). Square, ink when on. */
@Composable
fun Chips(options: List<String>, selected: String, onSelect: (String) -> Unit, modifier: Modifier = Modifier) {
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        options.forEach { o ->
            val on = o == selected
            Text(
                o,
                style = MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.SemiBold),
                color = if (on) Qwik.Bg else Qwik.Ink,
                modifier = Modifier
                    .background(if (on) Qwik.Accent else Color.Transparent)
                    .border(1.dp, if (on) Qwik.Accent else Qwik.Divider)
                    .clickable { onSelect(o) }
                    .padding(horizontal = 12.dp, vertical = 6.dp),
            )
        }
    }
}

/**
 * A one-of-many picker that starts empty: the field shows the placeholder
 * until something is chosen, and the list drops below it. Used where a chip
 * row would auto-select whatever happened to be first — a company on the
 * onboarding form has to be a deliberate choice, not a default.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Dropdown(
    options: List<String>,
    selected: String,
    onSelect: (String) -> Unit,
    placeholder: String,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    var open by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(
        expanded = open && enabled && options.isNotEmpty(),
        onExpandedChange = { if (enabled && options.isNotEmpty()) open = it },
        modifier = modifier,
    ) {
        OutlinedTextField(
            value = selected,
            onValueChange = {},
            readOnly = true,
            singleLine = true,
            placeholder = { Text(placeholder, color = Qwik.N600, maxLines = 1) },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = open) },
            colors = OutlinedTextFieldDefaults.colors(
                focusedContainerColor = Qwik.Surface,
                unfocusedContainerColor = Qwik.Surface,
                focusedBorderColor = Qwik.Accent,
                unfocusedBorderColor = Qwik.Divider,
                cursorColor = Qwik.Accent,
                focusedTextColor = Qwik.Ink,
                unfocusedTextColor = Qwik.Ink,
            ),
            modifier = Modifier
                .menuAnchor(MenuAnchorType.PrimaryNotEditable, enabled)
                .fillMaxWidth(),
        )
        // The menu's ground is the theme's surfaceContainer, set to the
        // design's off-white in Theme.kt so this stays on palette.
        ExposedDropdownMenu(
            expanded = open && enabled && options.isNotEmpty(),
            onDismissRequest = { open = false },
        ) {
            options.forEach { o ->
                DropdownMenuItem(
                    text = {
                        Text(
                            o,
                            style = MaterialTheme.typography.bodyLarge,
                            color = if (o == selected) Qwik.Accent else Qwik.Ink,
                            maxLines = 1,
                        )
                    },
                    onClick = { onSelect(o); open = false },
                )
            }
        }
    }
}

/** A member of staff's picture (the recruiter themselves is `me`), initials
 *  while it loads or when there is none. Square, like the rider's. */
@Composable
fun StaffAvatar(email: String, name: String?, size: Dp = 96.dp, version: Int = 0) {
    val url = BuildConfig.API_BASE_URL + "recruiters/" + email + "/photo" +
        (if (version > 0) "?v=$version" else "")
    Box(
        modifier = Modifier.size(size).background(Qwik.N200).border(1.dp, Qwik.N400),
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

/** The design's search field: surface fill, 1 px divider border, no rounding. */
@Composable
fun SearchField(value: String, onChange: (String) -> Unit, placeholder: String, modifier: Modifier = Modifier) {
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        placeholder = { Text(placeholder, color = Qwik.N600) },
        leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null, tint = Qwik.N600) },
        trailingIcon = {
            if (value.isNotEmpty()) IconButton(onClick = { onChange("") }) {
                Icon(Icons.Filled.Close, contentDescription = "Clear", tint = Qwik.N700)
            }
        },
        singleLine = true,
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
        colors = OutlinedTextFieldDefaults.colors(
            focusedContainerColor = Qwik.Surface,
            unfocusedContainerColor = Qwik.Surface,
            focusedBorderColor = Qwik.Accent,
            unfocusedBorderColor = Qwik.Divider,
            cursorColor = Qwik.Accent,
        ),
        modifier = modifier.fillMaxWidth(),
    )
}

/** A list row: title / sub on the left, trailing tags on the right, hairline under. */
@Composable
fun ListRow(
    title: String,
    sub: String?,
    onClick: () -> Unit,
    leading: (@Composable () -> Unit)? = null,
    trailing: (@Composable () -> Unit)? = null,
) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 20.dp, vertical = 13.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (leading != null) {
            leading(); Spacer(Modifier.width(12.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleLarge, color = Qwik.Ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (!sub.isNullOrBlank()) {
                Text(sub, style = MaterialTheme.typography.bodyMedium, color = Qwik.N700, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
        }
        if (trailing != null) {
            Spacer(Modifier.width(10.dp)); trailing()
        }
    }
    Hairline()
}

/** Rider photo tile: the server thumbnail if there is one, initials otherwise.
 *  Square. [version] busts the image cache after a new photo is uploaded. */
@Composable
fun Avatar(personId: Long, name: String?, size: Dp = 44.dp, thumb: Boolean = true, version: Int = 0) {
    val url = BuildConfig.API_BASE_URL + "persons/$personId/photo" +
        (if (thumb) "?size=thumb" else "?full=1") + (if (version > 0) "&v=$version" else "")
    Box(
        modifier = Modifier.size(size).background(Qwik.N200).border(1.dp, Qwik.N400),
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

/** The signed-in recruiter's own face, for the header chip that opens their
 *  profile. Same fallback as [Avatar]: their initials until they upload one.
 *  [version] busts the cache after they change the picture. */
@Composable
fun MeAvatar(name: String?, size: Dp = 28.dp, version: Int = 0) {
    val url = BuildConfig.API_BASE_URL + "recruiters/me/photo" +
        (if (version > 0) "?v=$version" else "")
    Box(
        modifier = Modifier.size(size).background(Qwik.N200).border(1.dp, Qwik.N400),
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
            color = Qwik.N700,
        )
    }
}

/** Grey block that stands in for text while it loads. */
@Composable
fun Skeleton(width: Dp, height: Dp = 14.dp) {
    Box(Modifier.size(width, height).background(Qwik.N300))
}

/** Centre-aligned quiet sentence for empty lists and errors. */
@Composable
fun Note(text: String, modifier: Modifier = Modifier, color: Color = Qwik.N700) {
    Text(text, style = MaterialTheme.typography.bodyLarge, color = color, modifier = modifier.padding(horizontal = 20.dp, vertical = 22.dp))
}

@Composable
fun FullWidthSpacer() = Box(Modifier.fillMaxWidth())

@Composable
fun Fill(modifier: Modifier = Modifier) = Box(modifier.fillMaxSize())
