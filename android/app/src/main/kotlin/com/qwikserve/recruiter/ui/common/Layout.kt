package com.qwikserve.recruiter.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.qwikserve.recruiter.ui.theme.Qwik

/**
 * One phone app, three widths.
 *
 * A recruiter's phone is 360–430 dp: everything is full width, tabs across
 * the top, one screen at a time. A tablet held upright (≈ 800 dp) gets the
 * same screens, but a line of text 800 dp wide is unreadable — so the page is
 * centred in a comfortable column. A tablet on its side (≈ 1100 dp and up) has
 * room for two things at once: the tabs move into a rail down the left, the
 * list keeps a phone-ish width, and the rider you tap opens beside it instead
 * of covering it.
 *
 * The breakpoints are the Material window-size classes (600 / 840), nudged to
 * 900 for the two-pane split so a 9-inch tablet in landscape doesn't end up
 * with two cramped halves.
 */
@Immutable
data class Layout(
    val width: Dp,
    /** Tabs live in a rail down the left instead of a strip across the top. */
    val rail: Boolean,
    /** List on the left, the tapped rider on the right — no navigation. */
    val twoPane: Boolean,
    /** How wide a single column of content is allowed to get. */
    val contentMax: Dp,
) {
    val listPane: Dp get() = if (width >= 1200.dp) 440.dp else 400.dp
}

@Composable
fun rememberLayout(): Layout {
    val w = LocalConfiguration.current.screenWidthDp.dp
    return remember(w) {
        Layout(
            width = w,
            rail = w >= 900.dp,
            twoPane = w >= 900.dp,
            contentMax = if (w >= 600.dp) 720.dp else w,
        )
    }
}

/** Content in a centred column no wider than it should be. On a phone this is
 *  the whole screen, so it costs nothing there. */
@Composable
fun PageBox(max: Dp, modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.TopCenter) {
        Box(Modifier.widthIn(max = max).fillMaxSize()) { content() }
    }
}

/** A form is narrower than a page — 520 dp is about as wide as a text field
 *  should ever be. Full width on a phone, capped on anything bigger; put it on
 *  a child of a Column that centres its children. */
fun Modifier.formWidth(max: Dp = 520.dp): Modifier = this.widthIn(max = max).fillMaxWidth()

/** The 1 px hairline between two panes. */
@Composable
fun VDivider(modifier: Modifier = Modifier) {
    Box(modifier.width(1.dp).fillMaxHeight().background(Qwik.N400))
}
