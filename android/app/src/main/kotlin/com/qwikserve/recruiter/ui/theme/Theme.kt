package com.qwikserve.recruiter.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontLoadingStrategy
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.qwikserve.recruiter.R

/**
 * "Modernist" — the red/white look from the saved Claude Design canvas
 * (android/Qwikserve Recruiter.html): off-white ground, ink text, one red
 * accent, square corners, 2 px ink rules, Archivo 800 for headings and
 * uppercase tracked labels. One theme; no dark mode (the design has none).
 */
object Qwik {
    val Bg = Color(0xFFF3F2F2)
    val Surface = Color(0xFFEAE9E9)
    val Ink = Color(0xFF201E1D)
    val Accent = Color(0xFFEC3013)
    val Accent100 = Color(0xFFFFF2EF)
    val Accent200 = Color(0xFFFFE0D9)
    val Accent700 = Color(0xFFAE1800)
    val Accent800 = Color(0xFF7C1405)
    val N100 = Color(0xFFF8F4F4)
    val N200 = Color(0xFFEAE7E7)
    val N300 = Color(0xFFD7D3D3)
    val N400 = Color(0xFFBAB6B6)
    val N500 = Color(0xFF9B9797)
    val N600 = Color(0xFF7D7979)
    val N700 = Color(0xFF605D5D)
    val N800 = Color(0xFF444141)
    val N900 = Color(0xFF2D2B2B)
    val Divider = Color(0x66201E1D) // ink at 40 %
}

/**
 * Archivo, bundled. `OptionalLocal` matters: if a phone's font parser refuses
 * one of these files, Compose quietly falls back to the system face instead of
 * throwing at first layout — a plainer screen beats no screen.
 */
val Archivo = FontFamily(
    Font(R.font.archivo_regular, FontWeight.Normal, loadingStrategy = FontLoadingStrategy.OptionalLocal),
    Font(R.font.archivo_semibold, FontWeight.SemiBold, loadingStrategy = FontLoadingStrategy.OptionalLocal),
    Font(R.font.archivo_extrabold, FontWeight.ExtraBold, loadingStrategy = FontLoadingStrategy.OptionalLocal),
)

private val Scheme = lightColorScheme(
    primary = Qwik.Accent,
    onPrimary = Color.White,
    primaryContainer = Qwik.Accent100,
    onPrimaryContainer = Qwik.Accent800,
    background = Qwik.Bg,
    onBackground = Qwik.Ink,
    surface = Qwik.Bg,
    onSurface = Qwik.Ink,
    surfaceVariant = Qwik.Surface,
    onSurfaceVariant = Qwik.N700,
    // Menus and sheets take their ground from these, so a dropdown stays
    // off-white instead of falling back to Material's own neutral.
    surfaceContainer = Qwik.Bg,
    surfaceContainerHigh = Qwik.Bg,
    surfaceContainerHighest = Qwik.Surface,
    surfaceContainerLow = Qwik.Bg,
    surfaceContainerLowest = Qwik.Bg,
    error = Qwik.Accent700,
    outline = Qwik.Divider,
    outlineVariant = Qwik.N300,
)

private val Type = Typography(
    // Display: screen titles ("Today", a rider's name)
    headlineLarge = TextStyle(
        fontFamily = Archivo, fontWeight = FontWeight.ExtraBold,
        fontSize = 34.sp, lineHeight = 34.sp, letterSpacing = (-0.85).sp,
    ),
    headlineMedium = TextStyle(
        fontFamily = Archivo, fontWeight = FontWeight.ExtraBold,
        fontSize = 28.sp, lineHeight = 28.sp, letterSpacing = (-0.5).sp,
    ),
    headlineSmall = TextStyle(
        fontFamily = Archivo, fontWeight = FontWeight.ExtraBold,
        fontSize = 22.sp, lineHeight = 24.sp, letterSpacing = (-0.3).sp,
    ),
    titleLarge = TextStyle(
        fontFamily = Archivo, fontWeight = FontWeight.SemiBold, fontSize = 17.sp, lineHeight = 22.sp,
    ),
    titleMedium = TextStyle(
        fontFamily = Archivo, fontWeight = FontWeight.SemiBold, fontSize = 16.sp, lineHeight = 21.sp,
    ),
    bodyLarge = TextStyle(fontFamily = Archivo, fontSize = 16.sp, lineHeight = 22.sp),
    bodyMedium = TextStyle(fontFamily = Archivo, fontSize = 14.sp, lineHeight = 19.sp),
    bodySmall = TextStyle(fontFamily = Archivo, fontSize = 13.sp, lineHeight = 18.sp),
    // Uppercase tracked labels ("RIDERS", "MY REQUESTS") — apply uppercase in the text.
    labelLarge = TextStyle(
        fontFamily = Archivo, fontWeight = FontWeight.ExtraBold, fontSize = 14.sp, lineHeight = 18.sp,
    ),
    labelMedium = TextStyle(
        fontFamily = Archivo, fontWeight = FontWeight.SemiBold, fontSize = 12.sp,
        lineHeight = 16.sp, letterSpacing = 1.0.sp,
    ),
    labelSmall = TextStyle(
        fontFamily = Archivo, fontWeight = FontWeight.SemiBold, fontSize = 11.sp,
        lineHeight = 14.sp, letterSpacing = 0.9.sp,
    ),
)

/** Square everything — the design has radius 0 throughout. */
private val Square = Shapes(
    extraSmall = RoundedCornerShape(0.dp),
    small = RoundedCornerShape(0.dp),
    medium = RoundedCornerShape(0.dp),
    large = RoundedCornerShape(0.dp),
    extraLarge = RoundedCornerShape(0.dp),
)

@Composable
fun QwikTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = Scheme, typography = Type, shapes = Square, content = content)
}
