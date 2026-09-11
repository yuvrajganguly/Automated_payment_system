package com.qwikserve.recruiter.ui.riders

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
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.qwikserve.recruiter.data.auth.TokenStore
import com.qwikserve.recruiter.data.db.RiderEntity
import com.qwikserve.recruiter.data.repo.AppRepository
import com.qwikserve.recruiter.data.repo.RiderRepository
import com.qwikserve.recruiter.ui.common.Avatar
import com.qwikserve.recruiter.ui.common.Chips
import com.qwikserve.recruiter.ui.common.Hairline
import com.qwikserve.recruiter.ui.common.Kicker
import com.qwikserve.recruiter.ui.common.ListRow
import com.qwikserve.recruiter.ui.common.Note
import com.qwikserve.recruiter.ui.common.Rule
import com.qwikserve.recruiter.ui.common.ScreenAction
import com.qwikserve.recruiter.ui.common.SearchField
import com.qwikserve.recruiter.ui.common.Segmented
import com.qwikserve.recruiter.ui.common.Skeleton
import com.qwikserve.recruiter.ui.common.Tag
import com.qwikserve.recruiter.ui.common.shortDate
import com.qwikserve.recruiter.ui.theme.Qwik
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.io.IOException
import javax.inject.Inject

/** Which riders: everyone, or only the ones I onboarded. */
enum class Scope { MINE, ALL }

/**
 * Working or idle, by the server's rule: a rider is "working" when they
 * appeared in the last payout their company actually ran. Somebody onboarded
 * since that payout, or whose id the recruiter has switched off, or whose
 * company we have stopped running, is not counted against them. The flag is
 * cached with the rest of the roster, so this filter works with no signal
 * like the zone and Mine/All ones do.
 */
enum class Activity(val label: String, val working: Boolean?) {
    ALL("All", null), WORKING("Working", true), IDLE("Idle", false);

    companion object {
        fun of(label: String): Activity = entries.firstOrNull { it.label == label } ?: ALL
    }
}

private data class Filters(val q: String, val scope: Scope, val zone: String, val activity: Activity)

/**
 * One person, however many rider ids they hold.
 *
 * The roster is cached one row per (rider_id, company) because that is the key
 * everything else needs — switching an id off, renaming it, adding another.
 * But a recruiter reads this screen as a list of people, and somebody with a
 * Kaptan id and a Nykaa id was showing up twice, with the count in the header
 * agreeing with neither the list nor the person-based numbers on Stats.
 *
 * So the grouping happens here, on the cached rows, after the filters have
 * run. Filtering first is deliberate: the zone comes from the store, so a
 * person with a North id and a South id genuinely belongs in both zones' lists
 * — and in each of them, once.
 */
private data class PersonRow(
    val personId: Long,
    val name: String?,
    val riderIds: List<String>,
    val companies: List<String>,
    val hub: String?,
    val zone: String?,
    val hasEv: Boolean,
    val working: Boolean?,
    val lastWorkedOn: String?,
)

private fun List<RiderEntity>.byPerson(): List<PersonRow> {
    val order = LinkedHashMap<Long, MutableList<RiderEntity>>()
    forEach { order.getOrPut(it.personId) { mutableListOf() }.add(it) }
    return order.map { (pid, rows) ->
        PersonRow(
            personId = pid,
            name = rows.firstNotNullOfOrNull { it.name },
            riderIds = rows.map { it.riderId }.distinct(),
            companies = rows.map { it.company }.distinct().sorted(),
            hub = rows.firstNotNullOfOrNull { it.hub?.takeIf(String::isNotBlank) },
            zone = rows.firstNotNullOfOrNull { it.zone?.takeIf(String::isNotBlank) },
            hasEv = rows.any { it.vehicle == "EV" },
            // Working is a property of the person on the server, so every row
            // carries the same answer; ORed anyway so a half-synced cache
            // cannot report somebody idle who is not.
            working = if (rows.any { it.working == true }) true else rows.firstNotNullOfOrNull { it.working },
            lastWorkedOn = rows.mapNotNull { it.lastWorkedOn }.maxOrNull(),
        )
    }
}

@OptIn(ExperimentalCoroutinesApi::class, FlowPreview::class)
@HiltViewModel
class RidersViewModel @Inject constructor(
    private val repo: RiderRepository,
    private val app: AppRepository,
    private val store: TokenStore,
) : ViewModel() {
    val query = MutableStateFlow("")
    val scope = MutableStateFlow(Scope.ALL)
    /** "North" / "South" / "All" — All riders opens on the recruiter's own zone. */
    val zone = MutableStateFlow(app.defaultZone())

    fun zoneChoices(): List<String> = app.zoneChoices()

    /** Fenced to a single zone by the server — see AppRepository.zoneChoices. */
    private val fenced get() = app.zoneChoices().isEmpty()
    val activity = MutableStateFlow(Activity.ALL)
    var refreshing by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var hasCache by mutableStateOf<Boolean?>(null)
        private set

    private val me: String? get() = store.email

    /** The list reacts to typing and filters from Room — no network on a keystroke. */
    val riders: StateFlow<List<RiderEntity>> =
        combine(query.debounce(80), scope, zone, activity) { q, s, z, a -> Filters(q, s, z, a) }
            .flatMapLatest { f ->
                repo.search(
                    f.q,
                    mine = if (f.scope == Scope.MINE) me.orEmpty() else null,
                    // No client-side zone filter when the server has fenced
                    // this recruiter: everything the server sent is already
                    // theirs, so filtering again here can only subtract.
                    zone = if (f.scope == Scope.ALL && f.zone != "All" && !fenced) f.zone else null,
                    working = f.activity.working,
                )
            }
            .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    init {
        viewModelScope.launch {
            hasCache = repo.hasCache()
            refresh()
        }
    }

    fun refresh() {
        if (refreshing) return
        refreshing = true; error = null
        viewModelScope.launch {
            try {
                repo.refresh()
                hasCache = true
            } catch (e: IOException) {
                error = if (hasCache == true) null else "Can't reach the server — pull down to try again."
            } catch (e: Exception) {
                error = e.message ?: "Could not load riders"
            } finally {
                refreshing = false
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RidersScreen(onOpenPerson: (Long) -> Unit, onNewRider: () -> Unit, vm: RidersViewModel = hiltViewModel()) {
    val rows by vm.riders.collectAsStateWithLifecycle()
    // One entry per person. remember() keys on the filtered list, so the
    // grouping runs when the list changes and not on every recomposition.
    val riders = remember(rows) { rows.byPerson() }
    val q by vm.query.collectAsStateWithLifecycle()
    val scope by vm.scope.collectAsStateWithLifecycle()
    val zone by vm.zone.collectAsStateWithLifecycle()
    val activity by vm.activity.collectAsStateWithLifecycle()

    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, top = 14.dp, bottom = 10.dp),
            verticalAlignment = Alignment.Bottom,
        ) {
            Text("Riders", style = MaterialTheme.typography.headlineLarge, color = Qwik.Ink, modifier = Modifier.weight(1f))
            Text(
                if (riders.size == 1) "1 rider" else "${riders.size} riders",
                style = MaterialTheme.typography.bodySmall,
                color = Qwik.N700,
            )
        }
        Column(Modifier.padding(horizontal = 20.dp).padding(bottom = 12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Segmented(
                listOf("All riders", "My riders"),
                selected = if (scope == Scope.ALL) 0 else 1,
                onSelect = { vm.scope.value = if (it == 0) Scope.ALL else Scope.MINE },
            )
            // No zone row for a recruiter the server has fenced to one zone:
            // it would offer choices that all resolve to the same list.
            val zoneChoices = vm.zoneChoices()
            if (scope == Scope.ALL && zoneChoices.isNotEmpty()) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Kicker("Zone")
                    Spacer(Modifier.width(10.dp))
                    Chips(zoneChoices + "All", zone, onSelect = { vm.zone.value = it })
                }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Kicker("Working")
                Spacer(Modifier.width(10.dp))
                Chips(
                    Activity.entries.map { it.label },
                    activity.label,
                    onSelect = { vm.activity.value = Activity.of(it) },
                )
            }
            SearchField(q, onChange = { vm.query.value = it }, placeholder = "Name, rider id, phone or hub")
        }
        Rule()
        if (vm.error != null) Note(vm.error!!, color = Qwik.Accent700)
        PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::refresh, modifier = Modifier.weight(1f)) {
            when {
                vm.hasCache == false && riders.isEmpty() && vm.refreshing -> SkeletonList()
                riders.isEmpty() -> Note(
                    when {
                        q.isNotBlank() -> "No rider matches \"$q\"."
                        activity == Activity.WORKING ->
                            "Nobody here was in their company's last payout. Try All."
                        activity == Activity.IDLE ->
                            "Everybody here is working — nothing idle to chase."
                        scope == Scope.MINE -> "You haven't onboarded anyone yet. Riders you add will show here."
                        zone != "All" -> "No riders at $zone stores yet — or their hubs still need a zone on the web."
                        else -> "No riders yet."
                    },
                )
                else -> LazyColumn(Modifier.fillMaxSize()) {
                    items(riders, key = { it.personId }) { r ->
                        ListRow(
                            title = r.name ?: "—",
                            sub = listOfNotNull(
                                r.riderIds.joinToString(" / "),
                                r.hub,
                                r.zone?.let { "$it zone" },
                                lastWorked(r),
                            ).joinToString(" · "),
                            onClick = { onOpenPerson(r.personId) },
                            leading = { Avatar(r.personId, r.name) },
                            // Company and EV on top, the working state under
                            // them — three tags side by side would run off a
                            // 360 dp phone. Somebody at three companies gets
                            // the first plus a count for the same reason.
                            trailing = {
                                Column(
                                    horizontalAlignment = Alignment.End,
                                    verticalArrangement = Arrangement.spacedBy(4.dp),
                                ) {
                                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                        if (r.companies.size > 2) {
                                            Tag(r.companies.first(), outline = true)
                                            Tag("+${r.companies.size - 1}", outline = true)
                                        } else {
                                            r.companies.forEach { Tag(it, outline = true) }
                                        }
                                        if (r.hasEv) Tag("EV", accent = true)
                                    }
                                    Tag(if (r.working == true) "working" else "idle", accent = r.working == true)
                                }
                            },
                        )
                    }
                    item { Spacer(Modifier.height(24.dp)) }
                }
            }
        }
        ScreenAction("New rider", onClick = onNewRider)
    }
}

/** "last worked 4 Sep", or "never worked" for a rider no company ever paid. */
private fun lastWorked(r: PersonRow): String =
    r.lastWorkedOn?.let { "last worked " + shortDate(it) } ?: "never worked"

@Composable
private fun SkeletonList() {
    Column(Modifier.fillMaxSize()) {
        repeat(9) {
            Row(Modifier.fillMaxWidth().padding(20.dp, 13.dp), verticalAlignment = Alignment.CenterVertically) {
                Skeleton(44.dp, 44.dp)
                Spacer(Modifier.width(12.dp))
                Column {
                    Skeleton(160.dp)
                    Spacer(Modifier.height(6.dp))
                    Skeleton(110.dp, 12.dp)
                }
            }
            Hairline()
        }
    }
}
