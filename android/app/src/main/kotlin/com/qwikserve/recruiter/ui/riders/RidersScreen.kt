package com.qwikserve.recruiter.ui.riders

import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Logout
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import com.qwikserve.recruiter.data.db.RiderEntity
import com.qwikserve.recruiter.data.repo.RiderRepository
import com.qwikserve.recruiter.ui.common.Avatar
import com.qwikserve.recruiter.ui.common.Emerald
import com.qwikserve.recruiter.ui.common.Pill
import com.qwikserve.recruiter.ui.common.Skeleton
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.io.IOException
import javax.inject.Inject

@OptIn(ExperimentalCoroutinesApi::class, FlowPreview::class)
@HiltViewModel
class RidersViewModel @Inject constructor(private val repo: RiderRepository) : ViewModel() {
    val query = MutableStateFlow("")
    var refreshing by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var hasCache by mutableStateOf<Boolean?>(null)
        private set

    /** The list reacts to typing from Room — no network on a keystroke. */
    val riders: StateFlow<List<RiderEntity>> = query
        .debounce(80)
        .flatMapLatest { repo.search(it) }
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
fun RidersScreen(
    onOpenPerson: (Long) -> Unit,
    onSignOut: () -> Unit,
    vm: RidersViewModel = hiltViewModel(),
) {
    val riders by vm.riders.collectAsStateWithLifecycle()
    val q by vm.query.collectAsStateWithLifecycle()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Riders", fontWeight = FontWeight.Bold) },
                actions = {
                    IconButton(onClick = onSignOut) { Icon(Icons.Filled.Logout, contentDescription = "Sign out") }
                },
            )
        },
    ) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            OutlinedTextField(
                value = q,
                onValueChange = { vm.query.value = it },
                placeholder = { Text("Name, rider id, phone or hub") },
                leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
                trailingIcon = {
                    if (q.isNotEmpty()) IconButton(onClick = { vm.query.value = "" }) {
                        Icon(Icons.Filled.Close, contentDescription = "Clear")
                    }
                },
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            )
            if (vm.error != null) {
                Text(
                    vm.error!!,
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                )
            }
            PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize()) {
                when {
                    vm.hasCache == false && riders.isEmpty() && vm.refreshing -> SkeletonList()
                    riders.isEmpty() -> EmptyState(if (q.isBlank()) "No riders yet." else "No rider matches \"$q\".")
                    else -> LazyColumn(Modifier.fillMaxSize()) {
                        items(riders, key = { it.riderId + "@" + it.company }) { r ->
                            RiderRow(r, onClick = { onOpenPerson(r.personId) })
                            HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.4f))
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun RiderRow(r: RiderEntity, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Avatar(r.personId, r.name)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(r.name ?: "—", style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold)
            Text(
                listOfNotNull(r.riderId, r.hub).joinToString(" · "),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Pill(r.company)
            if (r.vehicle == "EV") Pill("EV", tone = Emerald)
        }
    }
}

@Composable
private fun SkeletonList() {
    Column(Modifier.fillMaxSize()) {
        repeat(9) {
            Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Skeleton(44.dp, 44.dp)
                Spacer(Modifier.width(12.dp))
                Column {
                    Skeleton(160.dp)
                    Spacer(Modifier.height(6.dp))
                    Skeleton(110.dp, 12.dp)
                }
            }
        }
    }
}

@Composable
private fun EmptyState(text: String) {
    Column(Modifier.fillMaxSize().padding(32.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Spacer(Modifier.height(60.dp))
        Text(text, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyLarge)
    }
}
