package com.qwikserve.recruiter.ui.requests

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
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
import androidx.lifecycle.viewModelScope
import com.qwikserve.recruiter.data.api.MoneyRequest
import com.qwikserve.recruiter.data.api.PayoutApi
import com.qwikserve.recruiter.ui.common.Hairline
import com.qwikserve.recruiter.ui.common.Kicker
import com.qwikserve.recruiter.ui.common.Note
import com.qwikserve.recruiter.ui.common.Rule
import com.qwikserve.recruiter.ui.common.Tag
import com.qwikserve.recruiter.ui.common.rupees
import com.qwikserve.recruiter.ui.common.shortDate
import com.qwikserve.recruiter.ui.theme.Qwik
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import java.io.IOException
import javax.inject.Inject

@HiltViewModel
class RequestsViewModel @Inject constructor(private val api: PayoutApi) : ViewModel() {
    var rows by mutableStateOf<List<MoneyRequest>>(emptyList())
        private set
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
                rows = api.requests(limit = 200)
            } catch (e: IOException) {
                error = if (rows.isEmpty()) "Can't reach the server — pull down to try again." else null
            } catch (e: Exception) {
                error = e.message ?: "Could not load requests"
            } finally {
                refreshing = false
            }
        }
    }
}

/** "My requests": every credit/debit request I filed, open ones first, with the admin's note. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RequestsScreen(onOpenPerson: (Long) -> Unit, vm: RequestsViewModel = hiltViewModel()) {
    val open = vm.rows.count { it.status == "open" }
    Column(Modifier.fillMaxSize()) {
        Column(Modifier.padding(start = 20.dp, end = 20.dp, top = 14.dp, bottom = 12.dp)) {
            Text("My requests", style = MaterialTheme.typography.headlineLarge, color = Qwik.Ink)
            Spacer(Modifier.height(6.dp))
            Kicker("$open open · ${vm.rows.size} filed")
        }
        Rule()
        if (vm.error != null) Note(vm.error!!, color = Qwik.Accent700)
        PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize()) {
            if (vm.rows.isEmpty()) {
                Note(if (vm.refreshing) "Loading…" else "No requests yet. File one from a rider's page when money needs adding or deducting.")
            } else {
                LazyColumn(Modifier.fillMaxSize()) {
                    items(vm.rows, key = { it.id }) { r -> RequestRow(r, onOpen = { onOpenPerson(r.personId) }) }
                    item { Spacer(Modifier.height(24.dp)) }
                }
            }
        }
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
