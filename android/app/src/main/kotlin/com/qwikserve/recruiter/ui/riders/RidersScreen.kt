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
import com.qwikserve.recruiter.ui.common.SearchField
import com.qwikserve.recruiter.ui.common.Segmented
import com.qwikserve.recruiter.ui.common.Skeleton
import com.qwikserve.recruiter.ui.common.Tag
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
    var refreshing by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var hasCache by mutableStateOf<Boolean?>(null)
        private set

    private val me: String? get() = store.email

    /** The list reacts to typing and filters from Room — no network on a keystroke. */
    val riders: StateFlow<List<RiderEntity>> =
        combine(query.debounce(80), scope, zone) { q, s, z -> Triple(q, s, z) }
            .flatMapLatest { (q, s, z) ->
                repo.search(
                    q,
                    mine = if (s == Scope.MINE) me.orEmpty() else null,
                    zone = if (s == Scope.ALL && z != "All") z else null,
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
fun RidersScreen(onOpenPerson: (Long) -> Unit, vm: RidersViewModel = hiltViewModel()) {
    val riders by vm.riders.collectAsStateWithLifecycle()
    val q by vm.query.collectAsStateWithLifecycle()
    val scope by vm.scope.collectAsStateWithLifecycle()
    val zone by vm.zone.collectAsStateWithLifecycle()

    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, top = 14.dp, bottom = 10.dp),
            verticalAlignment = Alignment.Bottom,
        ) {
            Text("Riders", style = MaterialTheme.typography.headlineLarge, color = Qwik.Ink, modifier = Modifier.weight(1f))
            Text("${riders.size} shown", style = MaterialTheme.typography.bodySmall, color = Qwik.N700)
        }
        Column(Modifier.padding(horizontal = 20.dp).padding(bottom = 12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Segmented(
                listOf("All riders", "My riders"),
                selected = if (scope == Scope.ALL) 0 else 1,
                onSelect = { vm.scope.value = if (it == 0) Scope.ALL else Scope.MINE },
            )
            if (scope == Scope.ALL) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Kicker("Zone")
                    Spacer(Modifier.width(10.dp))
                    Chips(listOf("North", "South", "All"), zone, onSelect = { vm.zone.value = it })
                }
            }
            SearchField(q, onChange = { vm.query.value = it }, placeholder = "Name, rider id, phone or hub")
        }
        Rule()
        if (vm.error != null) Note(vm.error!!, color = Qwik.Accent700)
        PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize()) {
            when {
                vm.hasCache == false && riders.isEmpty() && vm.refreshing -> SkeletonList()
                riders.isEmpty() -> Note(
                    when {
                        q.isNotBlank() -> "No rider matches \"$q\"."
                        scope == Scope.MINE -> "You haven't onboarded anyone yet. Riders you add will show here."
                        zone != "All" -> "No riders at $zone stores yet — or their hubs still need a zone on the web."
                        else -> "No riders yet."
                    },
                )
                else -> LazyColumn(Modifier.fillMaxSize()) {
                    items(riders, key = { it.riderId + "@" + it.company }) { r ->
                        ListRow(
                            title = r.name ?: "—",
                            sub = listOfNotNull(r.riderId, r.hub, r.zone?.let { "$it zone" }).joinToString(" · "),
                            onClick = { onOpenPerson(r.personId) },
                            leading = { Avatar(r.personId, r.name) },
                            trailing = {
                                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                    Tag(r.company, outline = true)
                                    if (r.vehicle == "EV") Tag("EV", accent = true)
                                }
                            },
                        )
                    }
                    item { Spacer(Modifier.height(24.dp)) }
                }
            }
        }
    }
}

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
