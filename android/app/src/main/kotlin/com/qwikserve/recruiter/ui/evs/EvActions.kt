package com.qwikserve.recruiter.ui.evs

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qwikserve.recruiter.data.api.ApiError
import com.qwikserve.recruiter.data.api.EvAssignIn
import com.qwikserve.recruiter.data.api.EvModelLite
import com.qwikserve.recruiter.data.api.EvReturnIn
import com.qwikserve.recruiter.data.api.EvUnitIn
import com.qwikserve.recruiter.data.api.EvUnitOut
import com.qwikserve.recruiter.data.api.MaintenanceClose
import com.qwikserve.recruiter.data.api.MaintenanceIn
import com.qwikserve.recruiter.data.api.PayoutApi
import com.qwikserve.recruiter.data.db.RiderEntity
import com.qwikserve.recruiter.data.repo.AppRepository
import com.qwikserve.recruiter.data.repo.RiderRepository
import com.qwikserve.recruiter.ui.common.BarButton
import com.qwikserve.recruiter.ui.common.GhostAction
import com.qwikserve.recruiter.ui.common.Hairline
import com.qwikserve.recruiter.ui.common.Kicker
import com.qwikserve.recruiter.ui.common.ListRow
import com.qwikserve.recruiter.ui.common.SearchField
import com.qwikserve.recruiter.ui.common.Segmented
import com.qwikserve.recruiter.ui.common.Tag
import com.qwikserve.recruiter.ui.common.rupees
import com.qwikserve.recruiter.ui.common.shortDate
import com.qwikserve.recruiter.ui.theme.Qwik
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import retrofit2.HttpException
import java.io.IOException
import java.time.LocalDate
import javax.inject.Inject

/**
 * The four things a recruiter does with a vehicle, in the app rather than on
 * the phone to the office: hand one over, take it back for good, take it back
 * and keep it as a spare, and send it in for repair (or bring it out again).
 *
 * The rules live on the server — one open assignment per person, rent stops on
 * the return date, a returned unit closes any open maintenance window, the
 * deposit close-out is an admin's job — so this only asks, and reports what
 * came back in a sentence.
 */
@OptIn(ExperimentalCoroutinesApi::class, FlowPreview::class)
@HiltViewModel
class EvActionsViewModel @Inject constructor(
    private val api: PayoutApi,
    private val riders: RiderRepository,
    private val app: AppRepository,
    private val json: Json,
) : ViewModel() {
    /** Provider + model rate card, for a unit that is not in the system yet. */
    val evModels: List<EvModelLite> get() = app.bootstrap.value?.evModels.orEmpty()
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    /** Idle units for "give an EV" — spare first, then anything not held. */
    var idle by mutableStateOf<List<EvUnitOut>>(emptyList())
        private set
    var loadingIdle by mutableStateOf(false)
        private set

    val riderQuery = MutableStateFlow("")
    val riderHits = riderQuery.debounce(80)
        .flatMapLatest { q -> if (q.isBlank()) flowOf(emptyList()) else riders.search(q).map { it.take(8) } }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val unitQuery = MutableStateFlow("")

    fun clear() { error = null }

    fun loadIdleUnits() {
        if (loadingIdle) return
        loadingIdle = true
        viewModelScope.launch {
            runCatching { if (app.bootstrap.value == null) app.refreshBootstrap() }
            runCatching { api.evs() }
                .onSuccess { all ->
                    idle = all.filter { it.status == "spare" || it.currentPersonId == null }
                        .filter { it.status != "maintenance" }
                        .sortedBy { if (it.status == "spare") 0 else 1 }
                }
                .onFailure { error = it.readable("Could not load the fleet") }
            loadingIdle = false
        }
    }

    /** A vehicle that arrived today: create it and hand it over in one call. */
    fun addAndAssign(
        evId: String,
        model: EvModelLite,
        personId: Long?,
        notes: String,
        onDone: (String) -> Unit,
    ) {
        val id = evId.trim().uppercase()
        if (id.isBlank()) { error = "The unit needs its number."; return }
        act(if (personId == null) "$id added" else "$id added and handed over", onDone) {
            api.createEv(
                EvUnitIn(
                    evId = id,
                    provider = model.provider,
                    model = model.modelName,
                    notes = notes.trim().ifBlank { null },
                    personId = personId,
                ),
            )
        }
    }

    fun assign(evId: String, personId: Long, onDone: (String) -> Unit) =
        act("$evId handed over", onDone) { api.assignEv(EvAssignIn(evId = evId, personId = personId)) }

    fun returnUnit(evId: String, onDone: (String) -> Unit) =
        act("$evId returned — the office settles the deposit", onDone) {
            api.returnEv(EvReturnIn(evId = evId))
        }

    fun toSpare(evId: String, onDone: (String) -> Unit) =
        act("$evId is now a spare", onDone) { api.evToSpare(EvReturnIn(evId = evId)) }

    fun sendToMaintenance(evId: String, reason: String, onDone: (String) -> Unit) =
        act("$evId sent for repair", onDone) {
            api.openMaintenance(
                MaintenanceIn(
                    evId = evId,
                    fromDate = LocalDate.now().toString(),
                    reason = reason.trim().ifBlank { null },
                ),
            )
        }

    fun backFromMaintenance(evId: String, onDone: (String) -> Unit) =
        act("$evId is back in service", onDone) {
            val open = api.maintenance(evId).firstOrNull { it.toDate == null }
                ?: throw IllegalStateException("That unit has no open repair to close.")
            api.closeMaintenance(open.id, MaintenanceClose())
        }

    /** Every action is the same shape: busy, ask, say what happened. */
    private fun act(success: String, onDone: (String) -> Unit, call: suspend () -> Unit) {
        if (busy) return
        busy = true; error = null
        viewModelScope.launch {
            try {
                call()
                onDone(success)
            } catch (e: HttpException) {
                error = e.readable("The server answered ${e.code()}")
            } catch (e: IOException) {
                error = "No signal — this one needs the server."
            } catch (e: Exception) {
                error = e.message ?: "That did not work"
            } finally {
                busy = false
            }
        }
    }

    private fun Throwable.readable(fallback: String): String = when (this) {
        is HttpException -> runCatching {
            json.decodeFromString(ApiError.serializer(), response()?.errorBody()?.string().orEmpty()).detail
        }.getOrNull() ?: fallback
        is IOException -> "No signal — this one needs the server."
        else -> message ?: fallback
    }
}

/** The actions that make sense for a unit in this state. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EvUnitSheet(
    unit: EvUnitOut,
    onOpenPerson: (Long) -> Unit,
    onDone: (String) -> Unit,
    onDismiss: () -> Unit,
    vm: EvActionsViewModel = hiltViewModel(),
) {
    val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var mode by remember { mutableStateOf("") } // "" | give | repair
    var reason by remember { mutableStateOf("") }
    val hits by vm.riderHits.collectAsStateWithLifecycle()
    val q by vm.riderQuery.collectAsStateWithLifecycle()
    LaunchedEffect(unit.evId) { vm.clear() }

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheet, containerColor = Qwik.Bg) {
        Column(Modifier.fillMaxWidth().imePadding().padding(horizontal = 20.dp).padding(bottom = 24.dp)) {
            Text(unit.evId, style = MaterialTheme.typography.headlineLarge, color = Qwik.Ink)
            Spacer(Modifier.height(6.dp))
            Kicker(
                listOfNotNull(
                    "${unit.provider} ${unit.model}",
                    rupees(unit.weeklyRate) + "/wk",
                    unit.status.replace('_', ' '),
                    unit.hub,
                ).joinToString(" · "),
            )
            if (unit.currentRiderName != null) {
                Spacer(Modifier.height(10.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        "With ${unit.currentRiderName}" +
                            (unit.handoverDate?.let { " since " + shortDate(it) } ?: ""),
                        style = MaterialTheme.typography.bodyMedium,
                        color = Qwik.Ink,
                        modifier = Modifier.weight(1f),
                    )
                    unit.currentPersonId?.let { GhostAction("Open", onClick = { onOpenPerson(it) }) }
                }
                if ((unit.totalDues ?: 0.0) > 0) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        "Owes " + rupees(unit.totalDues) + " — taking the EV back does not clear it.",
                        style = MaterialTheme.typography.bodySmall,
                        color = Qwik.Accent700,
                    )
                }
            }
            if (vm.error != null) {
                Spacer(Modifier.height(10.dp))
                Text(vm.error!!, color = Qwik.Accent700, style = MaterialTheme.typography.bodySmall)
            }
            Spacer(Modifier.height(18.dp))

            when (mode) {
                "give" -> {
                    Kicker("Give it to")
                    Spacer(Modifier.height(8.dp))
                    SearchField(q, onChange = { vm.riderQuery.value = it }, placeholder = "Rider name, id or phone")
                    Spacer(Modifier.height(8.dp))
                    RiderHits(hits, busy = vm.busy) { rider ->
                        vm.assign(unit.evId, rider.personId, onDone)
                    }
                }
                "repair" -> {
                    Kicker("What is wrong?")
                    Spacer(Modifier.height(8.dp))
                    SearchField(reason, onChange = { reason = it }, placeholder = "e.g. battery not charging")
                    Spacer(Modifier.height(14.dp))
                    BarButton(
                        if (vm.busy) "Sending…" else "Send for repair",
                        onClick = { vm.sendToMaintenance(unit.evId, reason, onDone) },
                        enabled = !vm.busy,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                else -> Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    when (unit.status) {
                        "in_use" -> {
                            BarButton(
                                "Take it back — keep as spare",
                                onClick = { vm.toSpare(unit.evId, onDone) },
                                enabled = !vm.busy,
                                modifier = Modifier.fillMaxWidth(),
                            )
                            BarButton(
                                "Take it back — return to the provider",
                                onClick = { vm.returnUnit(unit.evId, onDone) },
                                primary = false,
                                enabled = !vm.busy,
                                modifier = Modifier.fillMaxWidth(),
                            )
                            GhostAction("Send for repair", onClick = { mode = "repair" })
                        }
                        "maintenance" -> {
                            BarButton(
                                "Back in service",
                                onClick = { vm.backFromMaintenance(unit.evId, onDone) },
                                enabled = !vm.busy,
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }
                        else -> {
                            BarButton(
                                "Give it to a rider",
                                onClick = { mode = "give" },
                                enabled = !vm.busy,
                                modifier = Modifier.fillMaxWidth(),
                            )
                            GhostAction("Send for repair", onClick = { mode = "repair" })
                            if (unit.status != "returned") {
                                Spacer(Modifier.height(2.dp))
                                GhostAction("Return to the provider", onClick = { vm.returnUnit(unit.evId, onDone) })
                            }
                        }
                    }
                }
            }
        }
    }
}

/** "Give an EV" from a rider's page: the same actions, the other way round. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun GiveEvSheet(
    personId: Long,
    personName: String?,
    onDone: (String) -> Unit,
    onDismiss: () -> Unit,
    vm: EvActionsViewModel = hiltViewModel(),
) {
    val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val q by vm.unitQuery.collectAsStateWithLifecycle()
    var adding by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { vm.clear(); vm.loadIdleUnits() }
    val shown = remember(vm.idle, q) {
        val needle = q.trim().lowercase()
        vm.idle.filter {
            needle.isBlank() ||
                listOfNotNull(it.evId, it.provider, it.model).joinToString(" ").lowercase().contains(needle)
        }.take(40)
    }

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheet, containerColor = Qwik.Bg) {
        Column(Modifier.fillMaxWidth().imePadding().padding(horizontal = 20.dp).padding(bottom = 24.dp)) {
            Text("Give an EV", style = MaterialTheme.typography.headlineLarge, color = Qwik.Ink)
            Spacer(Modifier.height(6.dp))
            Kicker(personName ?: "This rider")
            Spacer(Modifier.height(14.dp))
            Segmented(
                listOf("Free units", "New unit"),
                selected = if (adding) 1 else 0,
                onSelect = { adding = it == 1; vm.clear() },
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(14.dp))
            if (vm.error != null) {
                Text(vm.error!!, color = Qwik.Accent700, style = MaterialTheme.typography.bodySmall)
                Spacer(Modifier.height(8.dp))
            }
            if (adding) {
                NewUnitForm(
                    models = vm.evModels,
                    busy = vm.busy,
                    action = "Add and hand over",
                    onAdd = { id, model, notes -> vm.addAndAssign(id, model, personId, notes, onDone) },
                )
                return@Column
            }
            SearchField(q, onChange = { vm.unitQuery.value = it }, placeholder = "Unit number or model")
            Spacer(Modifier.height(8.dp))
            when {
                vm.loadingIdle && vm.idle.isEmpty() ->
                    Text("Looking for free units…", style = MaterialTheme.typography.bodyMedium, color = Qwik.N700)
                shown.isEmpty() ->
                    Text(
                        "No free unit matches. Add it as a new unit above, or ask the fleet desk from Requests → EVs.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = Qwik.N700,
                    )
                else -> LazyColumn(Modifier.fillMaxWidth().heightIn(max = 360.dp)) {
                    items(shown, key = { it.evId }) { u ->
                        ListRow(
                            title = u.evId,
                            sub = "${u.provider} ${u.model} · ${rupees(u.weeklyRate)}/wk",
                            onClick = { if (!vm.busy) vm.assign(u.evId, personId, onDone) },
                            trailing = { Tag(u.status.replace('_', ' ')) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun RiderHits(hits: List<RiderEntity>, busy: Boolean, onPick: (RiderEntity) -> Unit) {
    if (hits.isEmpty()) {
        Text(
            "Type a name to find the rider.",
            style = MaterialTheme.typography.bodyMedium,
            color = Qwik.N700,
            modifier = Modifier.horizontalScroll(rememberScrollState()),
        )
        return
    }
    Column(Modifier.fillMaxWidth().heightIn(max = 320.dp)) {
        hits.forEach { r ->
            ListRow(
                title = r.name ?: r.riderId,
                sub = listOfNotNull(r.riderId, r.company, r.hub).joinToString(" · "),
                onClick = { if (!busy) onPick(r) },
            )
            Hairline()
        }
    }
}


/** Unit number, then the provider and model from the rate card. */
/** Stock arriving for the fleet, with no rider attached yet. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AddUnitSheet(
    onDone: (String) -> Unit,
    onDismiss: () -> Unit,
    vm: EvActionsViewModel = hiltViewModel(),
) {
    val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    LaunchedEffect(Unit) { vm.clear(); vm.loadIdleUnits() }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheet, containerColor = Qwik.Bg) {
        Column(Modifier.fillMaxWidth().imePadding().padding(horizontal = 20.dp).padding(bottom = 24.dp)) {
            Text("New unit", style = MaterialTheme.typography.headlineLarge, color = Qwik.Ink)
            Spacer(Modifier.height(6.dp))
            Kicker("It joins the fleet as a spare — hand it over whenever")
            Spacer(Modifier.height(14.dp))
            if (vm.error != null) {
                Text(vm.error!!, color = Qwik.Accent700, style = MaterialTheme.typography.bodySmall)
                Spacer(Modifier.height(8.dp))
            }
            NewUnitForm(
                models = vm.evModels,
                busy = vm.busy,
                action = "Add to the fleet",
                onAdd = { id, model, notes -> vm.addAndAssign(id, model, null, notes, onDone) },
            )
        }
    }
}

@Composable
private fun NewUnitForm(
    models: List<EvModelLite>,
    busy: Boolean,
    action: String,
    onAdd: (String, EvModelLite, String) -> Unit,
) {
    var id by remember { mutableStateOf("") }
    var notes by remember { mutableStateOf("") }
    var chosen by remember(models) { mutableStateOf(models.firstOrNull()) }
    if (models.isEmpty()) {
        Text(
            "The rate card has not loaded yet — pull down on the EVs tab and try again.",
            style = MaterialTheme.typography.bodyMedium,
            color = Qwik.N700,
        )
        return
    }
    Column {
        Kicker("Unit number")
        Spacer(Modifier.height(6.dp))
        SearchField(id, onChange = { id = it.uppercase() }, placeholder = "e.g. CBICEVD0244")
        Spacer(Modifier.height(14.dp))
        Kicker("Model")
        Spacer(Modifier.height(6.dp))
        Column(Modifier.heightIn(max = 220.dp).verticalScroll(rememberScrollState())) {
            models.forEach { m ->
                val on = m.modelId == chosen?.modelId
                ListRow(
                    title = "${m.provider} ${m.modelName}",
                    sub = if (on) "selected" else null,
                    onClick = { chosen = m },
                    trailing = { if (on) Tag("✓", accent = true) },
                )
                Hairline()
            }
        }
        Spacer(Modifier.height(14.dp))
        Kicker("Note (optional)")
        Spacer(Modifier.height(6.dp))
        SearchField(notes, onChange = { notes = it }, placeholder = "e.g. new from the provider today")
        Spacer(Modifier.height(16.dp))
        BarButton(
            if (busy) "Adding…" else action,
            onClick = { chosen?.let { onAdd(id, it, notes) } },
            enabled = !busy && id.isNotBlank() && chosen != null,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}
