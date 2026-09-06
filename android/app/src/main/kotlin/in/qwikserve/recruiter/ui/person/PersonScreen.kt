package `in`.qwikserve.recruiter.ui.person

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import `in`.qwikserve.recruiter.data.api.PersonOut
import `in`.qwikserve.recruiter.data.db.RiderEntity
import `in`.qwikserve.recruiter.data.repo.RiderRepository
import `in`.qwikserve.recruiter.ui.common.Amber
import `in`.qwikserve.recruiter.ui.common.Avatar
import `in`.qwikserve.recruiter.ui.common.Emerald
import `in`.qwikserve.recruiter.ui.common.Pill
import `in`.qwikserve.recruiter.ui.common.Rose
import `in`.qwikserve.recruiter.ui.common.Skeleton
import `in`.qwikserve.recruiter.ui.common.StatTile
import `in`.qwikserve.recruiter.ui.common.rupees
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.io.IOException
import javax.inject.Inject

@HiltViewModel
class PersonViewModel @Inject constructor(
    saved: SavedStateHandle,
    private val repo: RiderRepository,
) : ViewModel() {
    val personId: Long = checkNotNull(saved["personId"])

    /** Cached rider rows paint the screen at once; the live person fills the rest. */
    val cached: StateFlow<List<RiderEntity>> = repo.forPerson(personId)
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())
    var person by mutableStateOf<PersonOut?>(null)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    init { load() }

    fun load() {
        viewModelScope.launch {
            try { person = repo.person(personId); error = null }
            catch (e: IOException) { error = "Offline — showing what was last synced." }
            catch (e: Exception) { error = e.message ?: "Could not load this rider" }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PersonScreen(personId: Long, onBack: () -> Unit, vm: PersonViewModel = hiltViewModel()) {
    val cached by vm.cached.collectAsStateWithLifecycle()
    val p = vm.person
    val name = p?.displayName ?: cached.firstOrNull()?.name

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(name ?: "Rider", fontWeight = FontWeight.Bold) },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back") }
                },
            )
        },
    ) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Avatar(personId, name, size = 72.dp, thumb = false)
                Spacer(Modifier.width(16.dp))
                Column {
                    Text(name ?: "—", style = MaterialTheme.typography.titleLarge)
                    val ids = p?.aadhaarNo?.let { "Aadhaar " + it.chunked(4).joinToString(" ") }
                    val pan = p?.panNo?.let { "PAN $it" }
                    val line = listOfNotNull(ids, pan).joinToString(" · ")
                    if (line.isNotEmpty()) Text(line, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    else if (p != null) Text("No Aadhaar / PAN on file", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    else Skeleton(140.dp, 12.dp)
                }
            }
            if (vm.error != null) {
                Spacer(Modifier.height(8.dp))
                Text(vm.error!!, color = Amber, style = MaterialTheme.typography.labelMedium)
            }
            Spacer(Modifier.height(16.dp))

            // Standing — visible to recruiters so they never ask for money already added.
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                val bal = p?.currentBalance
                val arr = p?.arrearsOutstanding
                val dues = if (bal != null && arr != null) (arr - bal).coerceAtLeast(0.0) else null
                StatTile("Balance", if (p == null) "…" else rupees(bal), Modifier.weight(1f),
                    tone = if ((bal ?: 0.0) < 0) Rose else null)
                StatTile("EV arrears", if (p == null) "…" else rupees(arr), Modifier.weight(1f),
                    tone = if ((arr ?: 0.0) > 0) Amber else null)
                StatTile("Total dues", if (p == null) "…" else rupees(dues), Modifier.weight(1f),
                    tone = if ((dues ?: 0.0) > 0) Rose else Emerald)
            }
            Spacer(Modifier.height(16.dp))

            Section("EV") {
                val ev = p?.ev
                when {
                    p == null -> Skeleton(200.dp)
                    ev == null -> Text("No EV held", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    else -> Column {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text(ev.evId, fontWeight = FontWeight.SemiBold)
                            Pill("${ev.provider} ${ev.model}", tone = Emerald)
                        }
                        Text(
                            listOfNotNull(
                                ev.handoverDate?.let { "since $it" },
                                ev.rentChargedThrough?.let { "rent through $it" },
                            ).joinToString(" · "),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
            Spacer(Modifier.height(12.dp))

            Section("Rider ids") {
                val rows = p?.riders?.map { RiderLine(it.riderId, it.company, it.hub, it.mobNo, it.accountNo, it.ifsc, it.isActive) }
                    ?: cached.map { RiderLine(it.riderId, it.company, it.hub, it.mobNo, it.accountNo, it.ifsc, it.isActive) }
                if (rows.isEmpty()) Skeleton(220.dp)
                rows.forEach { r ->
                    Column(Modifier.padding(vertical = 6.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text(r.riderId, fontWeight = FontWeight.SemiBold)
                            Pill(r.company)
                            if (!r.active) Pill("inactive", tone = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        val detail = listOfNotNull(
                            r.hub,
                            r.phone,
                            r.account?.let { "A/c $it" + (r.ifsc?.let { i -> " · $i" } ?: "") },
                        ).joinToString(" · ")
                        if (detail.isNotEmpty()) Text(detail, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
    }
}

private data class RiderLine(
    val riderId: String, val company: String, val hub: String?, val phone: String?,
    val account: String?, val ifsc: String?, val active: Boolean,
)

@Composable
private fun Section(title: String, content: @Composable () -> Unit) {
    Surface(shape = RoundedCornerShape(14.dp), color = MaterialTheme.colorScheme.surface, tonalElevation = 1.dp, modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp)) {
            Text(title, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(6.dp))
            content()
        }
    }
}
