package com.qwikserve.recruiter.ui.requests

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.rememberModalBottomSheetState
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
import com.qwikserve.recruiter.data.api.EvRequest
import com.qwikserve.recruiter.data.api.EvRequestIn
import com.qwikserve.recruiter.data.api.MoneyRequest
import com.qwikserve.recruiter.data.api.PayoutApi
import com.qwikserve.recruiter.data.repo.AppRepository
import com.qwikserve.recruiter.ui.common.BarButton
import com.qwikserve.recruiter.ui.common.Chips
import com.qwikserve.recruiter.ui.common.GhostAction
import com.qwikserve.recruiter.ui.common.Hairline
import com.qwikserve.recruiter.ui.common.Kicker
import com.qwikserve.recruiter.ui.common.Note
import com.qwikserve.recruiter.ui.common.Rule
import com.qwikserve.recruiter.ui.common.Segmented
import com.qwikserve.recruiter.ui.common.Tag
import com.qwikserve.recruiter.ui.common.rupees
import com.qwikserve.recruiter.ui.common.shortDate
import com.qwikserve.recruiter.ui.login.Field
import com.qwikserve.recruiter.ui.login.fieldColors
import com.qwikserve.recruiter.ui.theme.Qwik
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import java.io.IOException
import javax.inject.Inject

@HiltViewModel
class RequestsViewModel @Inject constructor(
    private val api: PayoutApi,
    private val repo: AppRepository,
) : ViewModel() {
    var rows by mutableStateOf<List<MoneyRequest>>(emptyList())
        private set
    var evRows by mutableStateOf<List<EvRequest>>(emptyList())
        private set
    var hubs by mutableStateOf<List<String>>(emptyList())
        private set
    var refreshing by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var sending by mutableStateOf(false)
        private set
    var sendError by mutableStateOf<String?>(null)
        private set

    init { refresh() }

    fun refresh() {
        if (refreshing) return
        refreshing = true; error = null
        viewModelScope.launch {
            try {
                rows = api.requests(limit = 200)
                evRows = api.evRequests(limit = 200)
                hubs = repo.bootstrap.value?.hubs
                    ?: runCatching { repo.refreshBootstrap().hubs }.getOrDefault(hubs)
            } catch (e: IOException) {
                error = if (rows.isEmpty()) "Can't reach the server — pull down to try again." else null
            } catch (e: Exception) {
                error = e.message ?: "Could not load requests"
            } finally {
                refreshing = false
            }
        }
    }

    fun clearSendError() { sendError = null }

    /** File "I need N EVs at <store>"; on success the sheet closes itself. */
    fun askForEvs(quantity: Int, hub: String?, note: String?, onDone: () -> Unit) {
        if (sending) return
        sending = true; sendError = null
        viewModelScope.launch {
            try {
                val made = api.createEvRequest(
                    EvRequestIn(
                        quantity = quantity,
                        hub = hub?.takeIf { it.isNotBlank() },
                        note = note?.takeIf { it.isNotBlank() },
                    ),
                )
                evRows = listOf(made) + evRows
                onDone()
            } catch (e: IOException) {
                sendError = "Can't reach the server. Try again."
            } catch (e: Exception) {
                sendError = e.message ?: "Could not send the request"
            } finally {
                sending = false
            }
        }
    }

    fun withdraw(id: Long) {
        viewModelScope.launch {
            runCatching { api.cancelEvRequest(id) }
                .onSuccess { done -> evRows = evRows.map { if (it.id == id) done else it } }
                .onFailure { error = it.message ?: "Could not withdraw that request" }
        }
    }
}

/** "My requests": money changes I asked an admin for, and EVs I asked the
 *  fleet desk for. Open ones first, each with the admin's answer. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RequestsScreen(onOpenPerson: (Long) -> Unit, vm: RequestsViewModel = hiltViewModel()) {
    var tab by remember { mutableStateOf(0) }
    var asking by remember { mutableStateOf(false) }
    val openMoney = vm.rows.count { it.status == "open" }
    val openEvs = vm.evRows.filter { it.status == "open" }
    val unitsWaiting = openEvs.sumOf { it.quantity }

    Column(Modifier.fillMaxSize()) {
        Column(Modifier.padding(start = 20.dp, end = 20.dp, top = 14.dp, bottom = 12.dp)) {
            Text("My requests", style = MaterialTheme.typography.headlineLarge, color = Qwik.Ink)
            Spacer(Modifier.height(6.dp))
            Kicker(
                if (tab == 0) "$openMoney open · ${vm.rows.size} filed"
                else "${openEvs.size} open · $unitsWaiting EV${if (unitsWaiting == 1) "" else "s"} waiting",
            )
        }
        Segmented(
            options = listOf("Money", "EVs"),
            selected = tab,
            onSelect = { tab = it },
            counts = listOf(openMoney, openEvs.size),
            modifier = Modifier.padding(horizontal = 20.dp).padding(bottom = 12.dp),
        )
        Rule()
        if (vm.error != null) Note(vm.error!!, color = Qwik.Accent700)
        Box(Modifier.weight(1f)) {
            PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize()) {
                if (tab == 0) {
                    if (vm.rows.isEmpty()) {
                        Note(if (vm.refreshing) "Loading…" else "No requests yet. File one from a rider's page when money needs adding or deducting.")
                    } else {
                        LazyColumn(Modifier.fillMaxSize()) {
                            items(vm.rows, key = { it.id }) { r -> RequestRow(r, onOpen = { onOpenPerson(r.personId) }) }
                            item { Spacer(Modifier.height(24.dp)) }
                        }
                    }
                } else {
                    if (vm.evRows.isEmpty()) {
                        Note(if (vm.refreshing) "Loading…" else "No EV requests yet. Ask for vehicles when a store needs them — the fleet desk sees it straight away.")
                    } else {
                        LazyColumn(Modifier.fillMaxSize()) {
                            items(vm.evRows, key = { it.id }) { r -> EvRequestRow(r, onWithdraw = { vm.withdraw(r.id) }) }
                            item { Spacer(Modifier.height(24.dp)) }
                        }
                    }
                }
            }
        }
        if (tab == 1) {
            Rule()
            BarButton(
                "Ask for EVs",
                onClick = { vm.clearSendError(); asking = true },
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }

    if (asking) {
        val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
        ModalBottomSheet(
            onDismissRequest = { asking = false },
            sheetState = sheet,
            containerColor = Qwik.Bg,
        ) {
            AskForEvs(
                hubs = vm.hubs,
                busy = vm.sending,
                error = vm.sendError,
                onSend = { qty, hub, note -> vm.askForEvs(qty, hub, note) { asking = false } },
            )
        }
    }
}

/** The composer: how many, which store, why. Quantity is a row of chips —
 *  the answer is almost always a small number. */
@Composable
private fun AskForEvs(
    hubs: List<String>,
    busy: Boolean,
    error: String?,
    onSend: (Int, String?, String?) -> Unit,
) {
    var qty by remember { mutableStateOf(1) }
    var hub by remember { mutableStateOf("") }
    var note by remember { mutableStateOf("") }
    val choices = listOf(1, 2, 3, 4, 5, 6, 8, 10)

    Column(Modifier.fillMaxWidth().imePadding().padding(horizontal = 20.dp).padding(bottom = 24.dp)) {
        Text("Ask for EVs", style = MaterialTheme.typography.headlineLarge, color = Qwik.Ink)
        Spacer(Modifier.height(6.dp))
        Kicker("The fleet desk sees this with your store and zone")
        Spacer(Modifier.height(18.dp))
        Text("How many", style = MaterialTheme.typography.bodySmall, color = Qwik.N700)
        Spacer(Modifier.height(6.dp))
        Chips(
            options = choices.map { it.toString() },
            selected = qty.toString(),
            onSelect = { qty = it.toIntOrNull() ?: 1 },
            modifier = Modifier.horizontalScroll(rememberScrollState()),
        )
        Spacer(Modifier.height(16.dp))
        Field("Store (optional)") {
            OutlinedTextField(
                value = hub,
                onValueChange = { hub = it },
                placeholder = { Text("e.g. Belur", color = Qwik.N600) },
                singleLine = true,
                colors = fieldColors(),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        if (hub.length >= 2) {
            val matches = hubs.filter { it.contains(hub, ignoreCase = true) && !it.equals(hub, true) }.take(4)
            if (matches.isNotEmpty()) {
                Spacer(Modifier.height(8.dp))
                Chips(
                    options = matches,
                    selected = hub,
                    onSelect = { hub = it },
                    modifier = Modifier.horizontalScroll(rememberScrollState()),
                )
            }
        }
        Spacer(Modifier.height(16.dp))
        Field("Why (optional)") {
            OutlinedTextField(
                value = note,
                onValueChange = { note = it },
                placeholder = { Text("two joiners waiting", color = Qwik.N600) },
                singleLine = true,
                colors = fieldColors(),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        if (error != null) {
            Spacer(Modifier.height(8.dp))
            Text(error, color = Qwik.Accent700, style = MaterialTheme.typography.bodySmall)
        }
        Spacer(Modifier.height(20.dp))
        BarButton(
            if (busy) "Sending…" else "Send request for $qty EV${if (qty == 1) "" else "s"}",
            onClick = { onSend(qty, hub.trim(), note.trim()) },
            enabled = !busy,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun RequestRow(r: MoneyRequest, onOpen: () -> Unit) {
    val head = (if (r.direction == "credit") "Add " else "Deduct ") + rupees(r.amount)
    val bar = when (r.status) { "open" -> Qwik.Accent; "approved" -> Qwik.N500; else -> Qwik.N400 }
    val note = when (r.status) {
        "open" -> "Filed " + shortDate(r.createdAt) + " · waiting for an admin"
        "approved" -> "Approved" +
            (r.appliedAmount?.takeIf { it != r.amount }?.let { " for " + rupees(it) } ?: "") +
            (r.resolvedBy?.let { " by " + it.substringBefore('@') } ?: "") +
            (r.resolutionNote?.takeIf { it.isNotBlank() }?.let { " · “$it”" } ?: "")
        else -> "Rejected" + (r.resolutionNote?.takeIf { it.isNotBlank() }?.let { " · “$it”" } ?: "")
    }
    Row(Modifier.fillMaxWidth().clickable(onClick = onOpen).padding(start = 20.dp, end = 20.dp, top = 14.dp, bottom = 12.dp)) {
        Box(Modifier.width(4.dp).height(52.dp).background(bar))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(head, style = MaterialTheme.typography.titleLarge, color = Qwik.Ink, modifier = Modifier.weight(1f))
                Tag(r.status, accent = r.status == "open")
            }
            Text(r.personName ?: "Person #${r.personId}", style = MaterialTheme.typography.bodyMedium, color = Qwik.Ink)
            Text(r.reason, style = MaterialTheme.typography.bodyMedium, color = Qwik.N700)
            Text(note, style = MaterialTheme.typography.bodySmall, color = Qwik.N600, modifier = Modifier.padding(top = 3.dp))
        }
    }
    Hairline()
}

@Composable
private fun EvRequestRow(r: EvRequest, onWithdraw: () -> Unit) {
    val bar = when (r.status) { "open" -> Qwik.Accent; "fulfilled" -> Qwik.N500; else -> Qwik.N400 }
    val where = listOfNotNull(r.hub?.takeIf { it.isNotBlank() }, r.zone).joinToString(" · ").ifBlank { "No store given" }
    val line = when (r.status) {
        "open" -> "Filed " + shortDate(r.createdAt) + " · waiting for the fleet desk"
        "fulfilled" -> "Fulfilled" +
            (r.fulfilledQuantity?.takeIf { it != r.quantity }?.let { " — $it given" } ?: "") +
            (r.resolvedBy?.let { " by " + it.substringBefore('@') } ?: "") +
            (r.resolutionNote?.takeIf { it.isNotBlank() }?.let { " · “$it”" } ?: "")
        "cancelled" -> "Withdrawn"
        else -> "Rejected" + (r.resolutionNote?.takeIf { it.isNotBlank() }?.let { " · “$it”" } ?: "")
    }
    Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, top = 14.dp, bottom = 12.dp)) {
        Box(Modifier.width(4.dp).height(52.dp).background(bar))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "${r.quantity} EV${if (r.quantity == 1) "" else "s"}",
                    style = MaterialTheme.typography.titleLarge,
                    color = Qwik.Ink,
                    modifier = Modifier.weight(1f),
                )
                Tag(r.status, accent = r.status == "open")
            }
            Text(where, style = MaterialTheme.typography.bodyMedium, color = Qwik.Ink)
            val why = r.note?.takeIf { it.isNotBlank() }
            if (why != null) Text(why, style = MaterialTheme.typography.bodyMedium, color = Qwik.N700)
            Text(line, style = MaterialTheme.typography.bodySmall, color = Qwik.N600, modifier = Modifier.padding(top = 3.dp))
            if (r.status == "open") {
                Spacer(Modifier.height(4.dp))
                GhostAction("Withdraw", onClick = onWithdraw)
            }
        }
    }
    Hairline()
}
