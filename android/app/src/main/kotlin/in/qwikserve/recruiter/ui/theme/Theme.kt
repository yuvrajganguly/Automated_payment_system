package `in`.qwikserve.recruiter.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/** The console's palette: near-black ground, violet brand, emerald / amber / rose for state. */
object QwikColors {
    val Brand = Color(0xFF8B5CF6)
    val BrandDeep = Color(0xFF6D28D9)
    val Ground = Color(0xFF08070E)
    val Panel = Color(0xFF121120)
    val PanelRaised = Color(0xFF1A1929)
    val Ink = Color(0xFFE8E6F0)
    val InkMuted = Color(0xFF9A98AB)
    val Emerald = Color(0xFF34D399)
    val Amber = Color(0xFFFBBF24)
    val Rose = Color(0xFFFB7185)
    val LightGround = Color(0xFFF7F6FB)
    val LightPanel = Color(0xFFFFFFFF)
    val LightInk = Color(0xFF17162A)
}

private val Dark = darkColorScheme(
    primary = QwikColors.Brand,
    onPrimary = Color.White,
    primaryContainer = QwikColors.BrandDeep,
    onPrimaryContainer = Color.White,
    background = QwikColors.Ground,
    onBackground = QwikColors.Ink,
    surface = QwikColors.Panel,
    onSurface = QwikColors.Ink,
    surfaceVariant = QwikColors.PanelRaised,
    onSurfaceVariant = QwikColors.InkMuted,
    error = QwikColors.Rose,
    outline = Color(0xFF2A2940),
)

private val Light = lightColorScheme(
    primary = QwikColors.BrandDeep,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFEDE9FE),
    onPrimaryContainer = QwikColors.BrandDeep,
    background = QwikColors.LightGround,
    onBackground = QwikColors.LightInk,
    surface = QwikColors.LightPanel,
    onSurface = QwikColors.LightInk,
    surfaceVariant = Color(0xFFEFEDF6),
    onSurfaceVariant = Color(0xFF5B5970),
    error = Color(0xFFE11D48),
    outline = Color(0xFFD9D6E6),
)

private val QwikTypography = Typography(
    headlineMedium = TextStyle(fontSize = 26.sp, fontWeight = FontWeight.Bold, lineHeight = 32.sp),
    titleLarge = TextStyle(fontSize = 20.sp, fontWeight = FontWeight.SemiBold, lineHeight = 26.sp),
    titleMedium = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.SemiBold, lineHeight = 22.sp),
    bodyLarge = TextStyle(fontSize = 16.sp, lineHeight = 22.sp),
    bodyMedium = TextStyle(fontSize = 14.sp, lineHeight = 20.sp),
    labelMedium = TextStyle(fontSize = 12.sp, fontWeight = FontWeight.Medium, lineHeight = 16.sp),
    labelSmall = TextStyle(fontSize = 11.sp, fontWeight = FontWeight.Medium, lineHeight = 14.sp),
)

@Composable
fun QwikTheme(darkTheme: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (darkTheme) Dark else Light,
        typography = QwikTypography,
        content = content,
    )
}
