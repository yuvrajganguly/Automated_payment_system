package com.qwikserve.recruiter.ui.home

import android.Manifest
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qwikserve.recruiter.ui.common.GhostAction
import com.qwikserve.recruiter.ui.common.Rule
import com.qwikserve.recruiter.ui.evs.EvsScreen
import com.qwikserve.recruiter.ui.requests.RequestsScreen
import com.qwikserve.recruiter.ui.riders.RidersScreen
import com.qwikserve.recruiter.ui.stats.StatsScreen
import com.qwikserve.recruiter.ui.theme.Qwik
import com.qwikserve.recruiter.ui.today.TodayScreen

/** The five tabs across the top of the page. Order is the order of a recruiter's day. */
enum class Tab(val label: String) { TODAY("Today"), RIDERS("Riders"), EVS("EVs"), REQUESTS("Requests"), STATS("My numbers") }

/**
 * The signed-in shell: a slim brand line with Sign out, the tab strip, and
 * the current tab underneath. No drawer — everything is one tap away.
 */
@Composable
fun HomeScreen(
    onOpenPerson: (Long) -> Unit,
    onSignOut: () -> Unit,
    vm: HomeViewModel = hiltViewModel(),
) {
    var tab by rememberSaveable { mutableIntStateOf(Tab.TODAY.ordinal) }
    val boot by vm.bootstrap.collectAsStateWithLifecycle()

    // Location: ask once; the fix itself is taken by AppOpenLocation on every foreground.
    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { vm.onLocationPermission() }
    LaunchedEffect(Unit) {
        if (!vm.hasLocationPermission()) {
            ask.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
        } else {
            vm.onLocationPermission()
        }
    }

    Surface(Modifier.fillMaxSize(), color = Qwik.Bg) {
        Column(Modifier.fillMaxSize().statusBarsPadding()) {
            Row(
                Modifier.fillMaxWidth().padding(start = 20.dp, end = 14.dp, top = 10.dp, bottom = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("Qwikserve", style = MaterialTheme.typography.headlineSmall, color = Qwik.Ink)
                Spacer(Modifier.width(8.dp))
                Text(
                    listOfNotNull(boot?.me?.email?.substringBefore('@'), boot?.me?.zone?.let { "$it zone" })
                        .joinToString(" · ").uppercase(),
                    style = MaterialTheme.typography.labelSmall,
                    color = Qwik.N700,
                    modifier = Modifier.weight(1f).padding(top = 3.dp),
                    maxLines = 1,
                )
                GhostAction("Sign out", onClick = onSignOut)
            }
            TabStrip(selected = tab, onSelect = { tab = it })
            Box(Modifier.weight(1f)) {
                when (Tab.entries[tab]) {
                    Tab.TODAY -> TodayScreen(onOpenPerson = onOpenPerson, onGoTab = { tab = it.ordinal })
                    Tab.RIDERS -> RidersScreen(onOpenPerson = onOpenPerson)
                    Tab.EVS -> EvsScreen(onOpenPerson = onOpenPerson)
                    Tab.REQUESTS -> RequestsScreen(onOpenPerson = onOpenPerson)
                    Tab.STATS -> StatsScreen(onOpenPerson = onOpenPerson)
                }
            }
        }
    }
}

@Composable
private fun TabStrip(selected: Int, onSelect: (Int) -> Unit) {
    Column {
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp)) {
            Tab.entries.forEachIndexed { i, t ->
                val on = i == selected
                Column(
                    Modifier.clickable { onSelect(i) }.padding(horizontal = 8.dp),
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
        Rule()
    }
}
