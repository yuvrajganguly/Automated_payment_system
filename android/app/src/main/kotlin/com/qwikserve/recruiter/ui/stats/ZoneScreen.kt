package com.qwikserve.recruiter.ui.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qwikserve.recruiter.data.api.PayoutApi
import com.qwikserve.recruiter.data.api.ZoneBoard
import com.qwikserve.recruiter.data.api.ZoneRecruiter
import com.qwikserve.recruiter.ui.common.GhostAction
import com.qwikserve.recruiter.ui.common.Hairline
import com.qwikserve.recruiter.ui.common.Kicker
import com.qwikserve.recruiter.ui.common.NumberTile
import com.qwikserve.recruiter.ui.common.Rule
import com.qwikserve.recruiter.ui.common.StaffAvatar
import com.qwikserve.recruiter.ui.common.Tag
import com.qwikserve.recruiter.ui.theme.Qwik
import dagger.hilt.android.lifecycle.HiltViewModel
import java.io.IOException
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * The head recruiter's tab: their zone's field staff, side by side.
 *
 * The numbers are the same ones each recruiter sees on their own "My numbers"
 * tab, computed by the same server code, so a head's view of somebody cannot
 * disagree with that person's own screen. Every figure is people rather than
 * rider ids — somebody with an id at two companies is one recruit.
 *
 * Read-only by design. Everything a head can *change* they could already
 * change as a recruiter in their zone; the flag grants sight of colleagues'
 * work, and nothing here writes.
 */
@HiltViewModel
class ZoneViewModel @Inject constructor(private val api: PayoutApi) : ViewModel() {
    var board by mutableStateOf<ZoneBoard?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    init { refresh() }

    fun refresh() {
        if (loading) return
        loading = true
        viewModelScope.launch {
            runCatching { api.zoneRecruiting() }
                .onSuccess { board = it; error = null }
                .onFailure {
                    error = if (it is IOException) {
                        "No signal — your zone's numbers come from the server."
                    } else {
                        "Could not load your zone right now."
                    }
                }
            loading = false
        }
    }
}

@Composable
fun ZoneScreen(vm: ZoneViewModel = hiltViewModel()) {
    val b = vm.board
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        Kicker(
            (b?.zone?.uppercase() ?: "YOUR") + " ZONE",
            Modifier.padding(start = 20.dp, top = 16.dp, bottom = 6.dp),
        )
        Text(
            "What the recruiters in your zone have done. The same numbers each of " +
                "them sees on their own tab.",
            style = MaterialTheme.typography.bodyMedium,
            color = Qwik.N700,
            modifier = Modifier.padding(horizontal = 20.dp).padding(bottom = 12.dp),
        )
        Rule()

        val t = b?.totals
        Row(Modifier.fillMaxWidth()) {
            NumberTile((t?.month ?: 0).toString(), "This month", Modifier.weight(1f))
            Box(Modifier.width(1.dp).height(78.dp).background(Qwik.N400))
            NumberTile((t?.allTime ?: 0).toString(), "All time", Modifier.weight(1f))
            Box(Modifier.width(1.dp).height(78.dp).background(Qwik.N400))
            NumberTile((t?.active ?: 0).toString(), "Still active", Modifier.weight(1f))
            Box(Modifier.width(1.dp).height(78.dp).background(Qwik.N400))
            NumberTile((t?.evHolders ?: 0).toString(), "On an EV", Modifier.weight(1f))
        }
        Rule()

        vm.error?.let {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    it,
                    style = MaterialTheme.typography.bodyMedium,
                    color = Qwik.Accent700,
                    modifier = Modifier.weight(1f),
                )
                GhostAction("Retry", onClick = vm::refresh)
            }
            Hairline()
        }

        val rows = b?.recruiters.orEmpty()
        if (rows.isEmpty() && vm.error == null) {
            Text(
                if (vm.loading) "Loading…" else "Nobody is assigned to your zone yet.",
                style = MaterialTheme.typography.bodyMedium,
                color = Qwik.N700,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 18.dp),
            )
        }
        rows.forEach { r -> RecruiterRow(r) }
        Spacer(Modifier.height(24.dp))
    }
}

/**
 * One recruiter. Collapsed it answers "how are they doing this month"; opened
 * it carries the rest, because four numbers in a row on a phone is three too
 * many to read at a glance.
 */
@Composable
private fun RecruiterRow(r: ZoneRecruiter) {
    var open by remember { mutableStateOf(false) }
    Hairline()
    Column(
        Modifier.fillMaxWidth().clickable { open = !open }
            .padding(horizontal = 20.dp, vertical = 12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            StaffAvatar(r.email, r.name, size = 40.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    r.name ?: r.email.substringBefore('@'),
                    style = MaterialTheme.typography.titleMedium,
                    color = Qwik.Ink,
                )
                Text(
                    "${r.month} this month · ${r.allTime} all time",
                    style = MaterialTheme.typography.bodySmall,
                    color = Qwik.N700,
                )
            }
            if (!r.isActive) {
                Tag("inactive")
                Spacer(Modifier.width(6.dp))
            }
            Text(
                r.active.toString(),
                style = MaterialTheme.typography.headlineSmall,
                color = if (r.active == 0 && r.allTime > 0) Qwik.Accent else Qwik.Ink,
            )
            Spacer(Modifier.width(4.dp))
            Text("active", style = MaterialTheme.typography.bodySmall, color = Qwik.N600)
        }
        if (open) {
            Spacer(Modifier.height(10.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                Figure("Today", r.today)
                Figure("This week", r.week)
                Figure("On the roster", r.onRoster)
            }
            Spacer(Modifier.height(8.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                Figure("EVs handed over", r.evsDeployed)
                Figure("Holding one now", r.evHolders)
            }
            Spacer(Modifier.height(6.dp))
            Text(
                // Worth saying on the supervision screen specifically: a head
                // reading a zero here should know what it is and is not.
                "\"Active\" means they were in their company's last payout. Riders " +
                    "onboarded since that payout ran are not counted against anyone.",
                style = MaterialTheme.typography.bodySmall,
                color = Qwik.N600,
            )
        }
    }
}

@Composable
private fun Figure(label: String, value: Int) {
    Column {
        Text(value.toString(), style = MaterialTheme.typography.titleLarge, color = Qwik.Ink)
        Text(label, style = MaterialTheme.typography.bodySmall, color = Qwik.N600)
    }
}
