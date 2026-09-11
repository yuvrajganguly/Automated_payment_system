package com.qwikserve.recruiter.ui.home

import android.Manifest
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qwikserve.recruiter.ui.common.BarButton
import com.qwikserve.recruiter.ui.common.GhostAction
import com.qwikserve.recruiter.ui.common.Layout
import com.qwikserve.recruiter.ui.common.MeAvatar
import com.qwikserve.recruiter.ui.common.PageBox
import com.qwikserve.recruiter.ui.common.Rule
import com.qwikserve.recruiter.ui.common.VDivider
import com.qwikserve.recruiter.ui.common.rememberLayout
import com.qwikserve.recruiter.ui.evs.EvsScreen
import com.qwikserve.recruiter.ui.person.PersonScreen
import com.qwikserve.recruiter.ui.profile.ProfileScreen
import com.qwikserve.recruiter.ui.requests.RequestsScreen
import com.qwikserve.recruiter.ui.riders.RidersScreen
import com.qwikserve.recruiter.ui.stats.StatsScreen
import com.qwikserve.recruiter.ui.stats.ZoneScreen
import com.qwikserve.recruiter.ui.theme.Qwik
import com.qwikserve.recruiter.ui.today.TodayScreen

/**
 * The tabs. Order is the order of a recruiter's day.
 *
 * PROFILE is deliberately **not** in the strip. It was once the sixth tab, and
 * on a phone the strip scrolls, so it sat just past the right edge with nothing
 * to say it was there — in practice it did not exist. It is reached instead by
 * tapping your own face in the top right corner, which is where every app on
 * the phone keeps your account, and the five that remain fit without scrolling.
 */
enum class Tab(
    val label: String,
    val inStrip: Boolean = true,
    /** Only drawn for a head recruiter. The route behind it 403s for anyone
     *  else, so offering the tab would be offering a dead end. */
    val headOnly: Boolean = false,
) {
    TODAY("Today"), RIDERS("Riders"), EVS("EVs"), REQUESTS("Requests"),
    STATS("My numbers"), ZONE("My zone", headOnly = true),
    PROFILE("Profile", inStrip = false),
}

/**
 * The signed-in shell. On a phone: the brand and your face, the tab strip, the
 * current tab underneath. On a tablet held upright: the same, with
 * the page centred so lines stay readable. On a wide screen: the tabs become a
 * rail down the left and a tapped rider opens in a second pane beside the
 * list, which is what the extra width is for.
 */
@Composable
fun HomeScreen(
    onOpenPerson: (Long) -> Unit,
    onNewRider: () -> Unit,
    onAddCompany: (Long, String) -> Unit,
    onSignOut: () -> Unit,
    vm: HomeViewModel = hiltViewModel(),
) {
    val layout = rememberLayout()
    var tab by rememberSaveable { mutableIntStateOf(Tab.TODAY.ordinal) }
    var picked by rememberSaveable { mutableStateOf<Long?>(null) }
    val boot by vm.bootstrap.collectAsStateWithLifecycle()
    // Their name, not their login. The email is a credential; printing it as
    // a name gives you "YUVRAJ.GANGULY.DS26" across the top of every screen.
    val myName = boot?.me?.name?.takeIf { it.isNotBlank() }
        ?: boot?.me?.email?.substringBefore('@')
    // Not shown anywhere — it only keys the avatar's cache, per account.
    val myEmail = boot?.me?.email
    // Head recruiter for their zone: draws the supervision tab. A flag, not a
    // role — boot.me.role is still "recruiter".
    val isHead = boot?.me?.isHead == true
    val who = listOfNotNull(myName, boot?.me?.zone?.let { "$it zone" })
        .joinToString(" · ").uppercase()

    // Location: ask once; the fix itself is taken by AppOpenLocation on every foreground.
    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { vm.onLocationPermission() }
    LaunchedEffect(Unit) {
        if (!vm.hasLocationPermission()) {
            ask.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
        } else {
            vm.onLocationPermission()
        }
    }

    // Beside a detail pane, opening a rider is a selection; otherwise it is a screen.
    val open: (Long) -> Unit = { id -> if (layout.twoPane) picked = id else onOpenPerson(id) }
    val body: @Composable () -> Unit = {
        when (Tab.entries[tab]) {
            Tab.TODAY -> TodayScreen(onOpenPerson = open, onGoTab = { tab = it.ordinal }, onNewRider = onNewRider)
            Tab.RIDERS -> RidersScreen(onOpenPerson = open, onNewRider = onNewRider)
            Tab.EVS -> EvsScreen(onOpenPerson = open)
            Tab.REQUESTS -> RequestsScreen(onOpenPerson = open)
            Tab.STATS -> StatsScreen(onOpenPerson = open)
            Tab.ZONE -> ZoneScreen()
            Tab.PROFILE -> ProfileScreen(onSignOut = onSignOut)
        }
    }

    // The second pane is for tabs that are lists of riders. Profile is nobody
    // else's page, so on a wide screen it simply takes the whole width.
    val splitPane = layout.twoPane && Tab.entries[tab] != Tab.PROFILE

    Surface(Modifier.fillMaxSize(), color = Qwik.Bg) {
        if (layout.rail) {
            Row(Modifier.fillMaxSize().statusBarsPadding()) {
                Rail(
                    who = who,
                    name = myName,
                    email = myEmail,
                    isHead = isHead,
                    selected = tab,
                    onSelect = { tab = it },
                    onNewRider = onNewRider,
                )
                VDivider()
                Box(
                    if (splitPane) Modifier.width(layout.listPane).fillMaxHeight()
                    else Modifier.weight(1f).fillMaxHeight(),
                ) { if (splitPane) body() else PageBox(layout.contentMax) { body() } }
                if (splitPane) {
                    VDivider()
                    Box(Modifier.weight(1f).fillMaxHeight()) {
                        DetailPane(picked, onClose = { picked = null }, onNewRider = onNewRider, onAddCompany = onAddCompany)
                    }
                }
            }
        } else {
            Column(Modifier.fillMaxSize().statusBarsPadding()) {
                // Brand on the left, your face on the right, and a gap between
                // them. It used to be brand + name-chip + Sign out crammed into
                // one line, which left your own account wedged between a
                // wordmark and a destructive action — the worst seat in the
                // app. Sign out moved to the foot of Profile, where the rest of
                // your account already lives.
                Row(
                    Modifier.fillMaxWidth().padding(start = 20.dp, end = 16.dp, top = 12.dp, bottom = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        "Qwikserve",
                        style = MaterialTheme.typography.headlineSmall,
                        color = Qwik.Ink,
                        modifier = Modifier.weight(1f),
                    )
                    Spacer(Modifier.width(12.dp))
                    MeButton(
                        name = myName,
                        email = myEmail,
                        selected = Tab.entries[tab] == Tab.PROFILE,
                        onClick = { tab = Tab.PROFILE.ordinal },
                    )
                }
                TabStrip(selected = tab, onSelect = { tab = it }, layout = layout, isHead = isHead)
                Box(Modifier.weight(1f)) {
                    PageBox(layout.contentMax) { body() }
                }
            }
        }
    }
}

/**
 * Your own face, top right — and the way to your profile.
 *
 * Profile carries the picture, the account and bank details, the Aadhaar and
 * PAN, the password, sign out, and the odometer with its day-by-day record. It
 * used to be the sixth tab in a strip that scrolls, which on a phone put it
 * just past the right edge; the first attempt at fixing that put a name chip in
 * the middle of the app bar, which only moved the problem. A face in the top
 * right corner is where every app on the phone keeps your account, so no label
 * is needed to explain it. It takes a red ring while you are on Profile.
 */
@Composable
private fun MeButton(name: String?, email: String?, selected: Boolean, onClick: () -> Unit) {
    Box(
        Modifier.clickable(onClick = onClick)
            .then(if (selected) Modifier.background(Qwik.Accent) else Modifier)
            .padding(if (selected) 3.dp else 0.dp),
    ) {
        MeAvatar(name = name, email = email, size = 36.dp)
    }
}

/** Wide screens: the tabs stand in a column down the left, with the brand
 *  above them and the two whole-app actions at the foot. */
@Composable
private fun Rail(
    who: String,
    name: String?,
    email: String?,
    isHead: Boolean,
    selected: Int,
    onSelect: (Int) -> Unit,
    onNewRider: () -> Unit,
) {
    Column(Modifier.width(232.dp).fillMaxHeight().padding(bottom = 16.dp)) {
        Column(Modifier.padding(start = 20.dp, end = 16.dp, top = 16.dp, bottom = 18.dp)) {
            Text("Qwikserve", style = MaterialTheme.typography.headlineSmall, color = Qwik.Ink)
            Spacer(Modifier.height(12.dp))
            // Same rule as the phone header: your own face is the way to your
            // own profile, so the rail does not list it as a tab either. There
            // is room for your name here, so it keeps it.
            Row(
                Modifier.clickable { onSelect(Tab.PROFILE.ordinal) },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                MeButton(
                    name = name,
                    email = email,
                    selected = Tab.entries[selected] == Tab.PROFILE,
                    onClick = { onSelect(Tab.PROFILE.ordinal) },
                )
                Spacer(Modifier.width(10.dp))
                Text(
                    who,
                    style = MaterialTheme.typography.labelSmall,
                    color = if (Tab.entries[selected] == Tab.PROFILE) Qwik.Accent else Qwik.N700,
                    maxLines = 2,
                )
            }
        }
        Tab.entries.filter { it.inStrip && (!it.headOnly || isHead) }.forEach { t ->
            val on = t.ordinal == selected
            Row(
                Modifier.fillMaxWidth().clickable { onSelect(t.ordinal) }.padding(vertical = 11.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(Modifier.width(4.dp).height(22.dp).background(if (on) Qwik.Accent else Qwik.Bg))
                Spacer(Modifier.width(16.dp))
                Text(
                    t.label,
                    style = MaterialTheme.typography.titleMedium.copy(fontWeight = if (on) FontWeight.ExtraBold else FontWeight.SemiBold),
                    color = if (on) Qwik.Ink else Qwik.N700,
                    maxLines = 1,
                )
            }
        }
        Spacer(Modifier.weight(1f))
        // navigationBarsPadding for the same reason the phone bottom bars have
        // it: the rail runs to the foot of an edge-to-edge window, and without
        // it the button's lower edge is under the system bar.
        Column(Modifier.padding(horizontal = 20.dp).navigationBarsPadding()) {
            BarButton("New rider", onClick = onNewRider, modifier = Modifier.fillMaxWidth(), height = 72.dp)
        }
    }
}

/** The right-hand pane: the rider you picked, or an invitation to pick one. */
@Composable
private fun DetailPane(
    personId: Long?,
    onClose: () -> Unit,
    onNewRider: () -> Unit,
    onAddCompany: (Long, String) -> Unit,
) {
    if (personId == null) {
        Column(
            Modifier.fillMaxSize().padding(40.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("Nobody picked", style = MaterialTheme.typography.headlineSmall, color = Qwik.Ink)
            Spacer(Modifier.height(8.dp))
            Text(
                "Tap a rider on the left and their profile opens here — standing, EV, rider ids, phone.",
                style = MaterialTheme.typography.bodyMedium,
                color = Qwik.N700,
            )
            Spacer(Modifier.height(18.dp))
            GhostAction("Onboard a new rider", onClick = onNewRider)
        }
    } else {
        PersonScreen(personId = personId, onBack = onClose, embedded = true, onAddCompany = onAddCompany)
    }
}

@Composable
private fun TabStrip(selected: Int, onSelect: (Int) -> Unit, layout: Layout, isHead: Boolean) {
    Column {
        Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.TopCenter) {
            Row(
                Modifier.widthIn(max = layout.contentMax)
                    .horizontalScroll(rememberScrollState())
                    .padding(horizontal = 12.dp),
            ) {
                Tab.entries.filter { it.inStrip && (!it.headOnly || isHead) }.forEach { t ->
                    val on = t.ordinal == selected
                    Column(
                        Modifier.clickable { onSelect(t.ordinal) }.padding(horizontal = 8.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Text(
                            t.label,
                            style = MaterialTheme.typography.titleMedium.copy(fontWeight = if (on) FontWeight.ExtraBold else FontWeight.SemiBold),
                            color = if (on) Qwik.Ink else Qwik.N600,
                            modifier = Modifier.padding(top = 10.dp, bottom = 8.dp),
                            maxLines = 1,
                        )
                        Box(Modifier.fillMaxWidth().height(3.dp).background(if (on) Qwik.Accent else Qwik.Bg))
                    }
                }
            }
        }
        Rule()
    }
}
