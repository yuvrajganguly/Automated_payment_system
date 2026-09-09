package com.qwikserve.recruiter.ui.evs

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
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
import com.qwikserve.recruiter.data.api.CloseoutRow
import com.qwikserve.recruiter.data.api.EvUnitOut
import com.qwikserve.recruiter.data.api.PayoutApi
import com.qwikserve.recruiter.data.auth.TokenStore
import com.qwikserve.recruiter.data.repo.AppRepository
import com.qwikserve.recruiter.ui.common.BarButton
import com.qwikserve.recruiter.ui.common.Chips
import com.qwikserve.recruiter.ui.common.Kicker
import com.qwikserve.recruiter.ui.common.ListRow
import com.qwikserve.recruiter.ui.common.Note
import com.qwikserve.recruiter.ui.common.Rule
import com.qwikserve.recruiter.ui.common.SearchField
import com.qwikserve.recruiter.ui.common.Segmented
import com.qwikserve.recruiter.ui.common.Tag
import com.qwikserve.recruiter.ui.common.rupees
import com.qwikserve.recruiter.ui.common.shortDate
import com.qwikserve.recruiter.ui.theme.Qwik
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import java.io.IOException
import javax.inject.Inject

/**
 * The fleet tab. "All fleet" filters by zone (the holder's store) and by
 * state; "My fleet" is units held by riders I onboarded, with the states the
 * user asked for up front: in maintenance, with dues, with inactive riders.
 */
@HiltViewModel
class EvsViewModel @Inject constructor(
    private val api: PayoutApi,
    private val app: AppRepository,
    private val store: TokenStore,
) : ViewModel() {
    var all by mutableStateOf<List<EvUnitOut>>(emptyList())
        private set
    var mine by mutableStateOf(false)
    var zone by mutableStateOf(app.defaultZone())
    var state by mutableStateOf("in_use")
    var query by mutableStateOf("")
    var refreshing by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    init { refresh() }

    fun refresh() {
        if (refreshing) return
        refreshing = true; error = null
        viewModelScope.launch {
            try {
                all = api.evs()
            } catch (e: IOException) {
                error = if (all.isEmpty()) "Can't reach the server — pull down to try again." else null
            } catch (e: Exception) {
                error = e.message ?: "Could not load the fleet"
            } finally {
                refreshing = false
            }
        }
    }

    private val me get() = store.email.orEmpty()

    /** The zones this recruiter may pick between; empty when the server has
     *  fenced them to one, in which case there is no filter row to draw. */
    fun zoneChoices(): List<String> = app.zoneChoices()

    /** Fenced to a single zone. The server then sends their own zone *plus*
     *  anything nobody has classified, and both belong on screen — filtering
     *  client-side on an exact zone match would throw the unzoned ones away
     *  again, one layer further down. */
    private val fenced get() = app.zoneChoices().isEmpty()

    /** Units in the chosen scope before the state filter (for the state counts). */
    fun scoped(): List<EvUnitOut> = all.filter { u ->
        (if (mine) me.isNotEmpty() && (u.recruitedBy ?: "").split(",").contains(me) else true) &&
            (mine || zone == "All" || u.zone == zone || (fenced && u.zone == null))
    }

    fun shown(): List<EvUnitOut> {
        val q = query.trim().lowercase()
        return scoped().filter { matches(it, state) }
            .filter { u ->
                q.isBlank() || listOfNotNull(u.evId, u.model, u.provider, u.currentRiderName, u.currentRiderId, u.hub)
                    .joinToString(" ").lowercase().contains(q)
            }
    }
}

private val ALL_STATES = listOf("in_use" to "In use", "spare" to "Spare", "maintenance" to "Maintenance", "returned" to "Returned")
private val MY_STATES = listOf("in_use" to "In use", "maintenance" to "Maintenance", "dues" to "Dues", "inactive" to "Inactive")

/** State filter. "dues" and "inactive" are about the holder, not the unit. */
internal fun matches(u: EvUnitOut, state: String) = when (state) {
    "dues" -> (u.totalDues ?: 0.0) > 0
    "inactive" -> u.holderActive == false
    else -> u.status == state
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EvsScreen(
    onOpenPerson: (Long) -> Unit,
    vm: EvsViewModel = hiltViewModel(),
    closeouts: CloseoutsViewModel = hiltViewModel(),
) {
    val scoped = vm.scoped()
    val shown = vm.shown()
    // Tapping a unit opens what can be done with it, in its current state.
    var picked by remember { mutableStateOf<EvUnitOut?>(null) }
    var note by remember { mutableStateOf<String?>(null) }
    var addingUnit by remember { mutableStateOf(false) }
    // A deposit answered from the card rather than at the moment of return.
    var answering by remember { mutableStateOf<CloseoutRow?>(null) }
    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, top = 14.dp, bottom = 10.dp),
            verticalAlignment = Alignment.Bottom,
        ) {
            Text("EVs", style = MaterialTheme.typography.headlineLarge, color = Qwik.Ink, modifier = Modifier.weight(1f))
            Text("${shown.size} of ${scoped.size}", style = MaterialTheme.typography.bodySmall, color = Qwik.N700)
        }
        Column(Modifier.padding(horizontal = 20.dp).padding(bottom = 12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Segmented(
                listOf("All fleet", "My fleet"),
                selected = if (vm.mine) 1 else 0,
                onSelect = {
                    vm.mine = it == 1
                    if (vm.state !in (if (vm.mine) MY_STATES else ALL_STATES).map { s -> s.first }) vm.state = "in_use"
                },
            )
            val zoneChoices = vm.zoneChoices()
            if (!vm.mine && zoneChoices.isNotEmpty()) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Kicker("Zone")
                    Spacer(Modifier.width(10.dp))
                    Chips(zoneChoices + "All", vm.zone, onSelect = { vm.zone = it })
                }
            }
            val states = if (vm.mine) MY_STATES else ALL_STATES
            Segmented(
                states.map { it.second },
                selected = states.indexOfFirst { it.first == vm.state }.coerceAtLeast(0),
                onSelect = { vm.state = states[it].first },
                counts = states.map { s -> scoped.count { matches(it, s.first) } },
            )
            SearchField(vm.query, onChange = { vm.query = it }, placeholder = "Unit number, model, rider or hub")
        }
        Rule()
        if (vm.error != null) Note(vm.error!!, color = Qwik.Accent700)
        note?.let { Note(it, color = Qwik.Ink) }
        // weight, not fillMaxSize: the bar button below needs its 62 dp.
        PullToRefreshBox(
            isRefreshing = vm.refreshing,
            onRefresh = { vm.refresh(); closeouts.load() },
            modifier = Modifier.weight(1f).fillMaxWidth(),
        ) {
            // One list, always: the fleet's own empty state is a row in it, so
            // the deposits card above stays reachable — and so pulling down
            // still refreshes when there is nothing to show.
            LazyColumn(Modifier.fillMaxSize()) {
                // The deposits this recruiter owes an answer on. It sits above
                // the fleet because it is the one thing here with a deadline
                // somebody else is waiting on.
                item(key = "closeouts") {
                    CloseoutsCard(vm = closeouts, onAnswer = { row -> note = null; answering = row })
                    Rule()
                }

                if (shown.isEmpty()) {
                    item(key = "empty") {
                        Note(
                            when {
                                vm.refreshing && vm.all.isEmpty() -> "Loading the fleet…"
                                vm.query.isNotBlank() -> "Nothing matches \"${vm.query}\"."
                                vm.mine -> "No units in this state with your riders."
                                else -> "Nothing in this state right now."
                            },
                        )
                    }
                }
                items(shown, key = { it.evId }) { u ->
                    val sub = if (u.currentRiderName != null) {
                        listOfNotNull(
                            u.currentRiderName,
                            u.hub,
                            u.handoverDate?.let { "since " + shortDate(it) },
                            u.totalDues?.takeIf { it > 0 }?.let { "owes " + rupees(it) },
                            if (u.holderActive == false) "rider inactive" else null,
                        ).joinToString(" · ")
                    } else {
                        "${u.provider} ${u.model} · ${rupees(u.weeklyRate)}/wk" + (u.notes?.takeIf { it.isNotBlank() }?.let { " · $it" } ?: "")
                    }
                    ListRow(
                        title = u.evId,
                        sub = sub,
                        onClick = { note = null; picked = u },
                        trailing = {
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                u.zone?.let { Tag(it) }
                                when {
                                    u.holderActive == false -> Tag("inactive", accent = true)
                                    (u.totalDues ?: 0.0) > 0 -> Tag("dues", accent = true)
                                    else -> Tag(u.status.replace('_', ' '), accent = u.status == "maintenance")
                                }
                            }
                        },
                    )
                }
                item(key = "tail") { Spacer(Modifier.height(24.dp)) }
            }
        }
        Rule()
        BarButton(
            "New unit",
            onClick = { note = null; addingUnit = true },
            primary = false,
            modifier = Modifier.fillMaxWidth(),
        )
    }

    if (addingUnit) {
        AddUnitSheet(
            onDone = { message -> note = message; addingUnit = false; vm.refresh() },
            onDismiss = { addingUnit = false },
        )
    }

    picked?.let { unit ->
        EvUnitSheet(
            unit = unit,
            onOpenPerson = { id -> picked = null; onOpenPerson(id) },
            // A return raises the deposit question, so whichever way the sheet
            // closes the card above has to be told to look again.
            onDone = { message -> note = message; picked = null; vm.refresh(); closeouts.load() },
            onDismiss = { picked = null },
            closeouts = closeouts,
        )
    }

    answering?.let { row ->
        CloseoutSheet(
            row = row,
            onDone = { message -> note = message; answering = null },
            onDismiss = { answering = null },
            vm = closeouts,
        )
    }
}
