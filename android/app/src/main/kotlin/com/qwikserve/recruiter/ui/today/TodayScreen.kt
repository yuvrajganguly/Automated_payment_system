package com.qwikserve.recruiter.ui.today

import android.content.Intent
import android.net.Uri
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qwikserve.recruiter.data.api.ActivityRow
import com.qwikserve.recruiter.data.api.PayoutApi
import com.qwikserve.recruiter.data.api.Todo
import com.qwikserve.recruiter.data.api.TodoItem
import com.qwikserve.recruiter.data.api.TodoStore
import com.qwikserve.recruiter.data.repo.AppRepository
import com.qwikserve.recruiter.ui.common.BarButton
import com.qwikserve.recruiter.ui.common.Chips
import com.qwikserve.recruiter.ui.common.GhostAction
import com.qwikserve.recruiter.ui.common.Hairline
import com.qwikserve.recruiter.ui.common.Kicker
import com.qwikserve.recruiter.ui.common.Note
import com.qwikserve.recruiter.ui.common.NumberTile
import com.qwikserve.recruiter.ui.common.Rule
import com.qwikserve.recruiter.ui.common.Tag
import com.qwikserve.recruiter.ui.common.rupees
import com.qwikserve.recruiter.ui.common.shortDate
import com.qwikserve.recruiter.ui.home.Tab
import com.qwikserve.recruiter.ui.profile.ShiftNudge
import com.qwikserve.recruiter.ui.theme.Qwik
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.async
import kotlinx.coroutines.launch
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import javax.inject.Inject

@HiltViewModel
class TodayViewModel @Inject constructor(
    private val api: PayoutApi,
    private val app: AppRepository,
) : ViewModel() {
    var zone by mutableStateOf<String?>(null) // null = "my zone" (server default)
        private set
    var todo by mutableStateOf<Todo?>(null)
        private set
    var feed by mutableStateOf<List<ActivityRow>>(emptyList())
        private set
    var openRequests by mutableStateOf(0)
        private set
    var refreshing by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    val bootstrap get() = app.bootstrap.value

    init { refresh() }

    fun pickZone(z: String) {
        zone = if (z == "My zone") null else z
        refresh()
    }

    fun refresh() {
        if (refreshing) return
        refreshing = true; error = null
        viewModelScope.launch {
            try {
                val t = async { api.todo(zone) }
                val f = async {
                    val since = SimpleDateFormat("yyyy-MM-dd", Locale.US).apply { timeZone = TimeZone.getTimeZone("UTC") }
                        .format(Date()) + " 00:00:00"
                    runCatching { api.activity(since = since, limit = 30) }.getOrDefault(emptyList())
                }
                val b = async { runCatching { app.refreshBootstrap() } }
                val r = async { runCatching { api.requests(status = "open", limit = 200).size }.getOrDefault(0) }
                todo = t.await(); feed = f.await(); b.await(); openRequests = r.await()
            } catch (e: IOException) {
                error = "Can't reach the server — pull down to try again."
            } catch (e: Exception) {
                error = e.message ?: "Could not load today's list"
            } finally {
                refreshing = false
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TodayScreen(
    onOpenPerson: (Long) -> Unit,
    onGoTab: (Tab) -> Unit,
    onNewRider: () -> Unit,
    vm: TodayViewModel = hiltViewModel(),
) {
    val todo = vm.todo
    val boot = vm.bootstrap
    val myZone = boot?.me?.zone
    val zoneOptions = (if (myZone != null) listOf("My zone") else emptyList()) + (boot?.zones ?: listOf("North", "South", "Misc")) + listOf("All")
    val selected = vm.zone ?: if (myZone != null) "My zone" else "All"
    val ctx = LocalContext.current

    Column(Modifier.fillMaxSize()) {
    PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::refresh, modifier = Modifier.weight(1f)) {
        LazyColumn(Modifier.fillMaxSize()) {
            item {
                Column(Modifier.padding(start = 20.dp, end = 20.dp, top = 14.dp, bottom = 12.dp)) {
                    Text("Today", style = MaterialTheme.typography.headlineLarge, color = Qwik.Ink)
                    Spacer(Modifier.height(6.dp))
                    Kicker(
                        listOfNotNull(
                            todo?.let { if (it.zone == "all") "All stores" else "${it.zone} zone" },
                            SimpleDateFormat("EEE d MMM", Locale.US).format(Date()),
                        ).joinToString(" · "),
                    )
                    Spacer(Modifier.height(12.dp))
                    Chips(zoneOptions, selected, onSelect = vm::pickZone)
                }
                Rule()
            }

            // The odometer itself lives on Profile — it is twice-a-day data
            // entry about the recruiter's own vehicle, not about riders, and
            // as a panel here it sat in the way of the work all day. What
            // stays is one line, and only while a reading is still owed.
            item {
                ShiftNudge(onOpen = { onGoTab(Tab.PROFILE) })
            }

            if (vm.error != null) item { Note(vm.error!!, color = Qwik.Accent700) }

            // The red band: how much needs a visit.
            item {
                Row(
                    Modifier.fillMaxWidth().background(Qwik.Accent).padding(horizontal = 20.dp, vertical = 14.dp),
                    verticalAlignment = Alignment.Bottom,
                ) {
                    Text(
                        (todo?.counts?.total ?: 0).toString(),
                        style = MaterialTheme.typography.headlineLarge.copy(fontSize = MaterialTheme.typography.headlineLarge.fontSize * 1.18f),
                        color = Qwik.Bg,
                    )
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f).padding(bottom = 4.dp)) {
                        Kicker("Things that need you", color = Qwik.Bg)
                        todo?.counts?.let { c ->
                            Text(
                                listOfNotNull(
                                    c.cod.takeIf { it > 0 }?.let { "$it COD" },
                                    c.evDues.takeIf { it > 0 }?.let { "$it EV dues" },
                                    c.inactiveEv.takeIf { it > 0 }?.let { "$it EVs to collect" },
                                ).joinToString(" · ").ifBlank { "Nothing waiting at your stores" },
                                style = MaterialTheme.typography.bodySmall,
                                color = Qwik.Accent200,
                            )
                        }
                    }
                }
            }

            if (todo != null && todo.stores.isEmpty()) {
                item { Note("Nothing waiting. The stores are square.") }
            }
            todo?.stores?.forEach { store ->
                item(key = "store-" + store.hub) { StoreHeader(store) }
                items(store.items, key = { it.kind + it.personId + (it.evId ?: "") }) { t ->
                    TodoRow(
                        t,
                        onOpen = { onOpenPerson(t.personId) },
                        onCall = t.mobNo?.let { n ->
                            { ctx.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:" + n.filter { c -> c.isDigit() || c == '+' }))) }
                        },
                    )
                }
            }

            // Three-up numbers, each a shortcut to its tab.
            item {
                Spacer(Modifier.height(20.dp))
                Rule()
                Row(Modifier.fillMaxWidth()) {
                    NumberTile(
                        (boot?.counts?.riderIdsActive ?: 0).toString(), "Riders",
                        modifier = Modifier.weight(1f), onClick = { onGoTab(Tab.RIDERS) },
                    )
                    Box(Modifier.width(1.dp).height(78.dp).background(Qwik.N400))
                    val evs = boot?.counts?.evs.orEmpty()
                    NumberTile(
                        evs.values.sum().toString(), "EVs · ${evs["spare"] ?: 0} spare",
                        modifier = Modifier.weight(1f), onClick = { onGoTab(Tab.EVS) },
                    )
                    Box(Modifier.width(1.dp).height(78.dp).background(Qwik.N400))
                    NumberTile(
                        vm.openRequests.toString(), "My requests",
                        modifier = Modifier.weight(1f), accent = vm.openRequests > 0,
                        onClick = { onGoTab(Tab.REQUESTS) },
                    )
                }
                Rule()
            }

            item {
                Row(
                    Modifier.fillMaxWidth().clickable { onGoTab(Tab.STATS) }.padding(horizontal = 20.dp, vertical = 15.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("My numbers", style = MaterialTheme.typography.titleMedium, color = Qwik.Ink, modifier = Modifier.weight(1f))
                    Text("today · week · month  ›", style = MaterialTheme.typography.bodyMedium, color = Qwik.N700)
                }
                Hairline()
            }

            item { Kicker("Logged today", modifier = Modifier.padding(start = 20.dp, top = 20.dp, bottom = 6.dp)) }
            if (vm.feed.isEmpty()) {
                item { Text("Nothing yet today.", style = MaterialTheme.typography.bodyMedium, color = Qwik.N700, modifier = Modifier.padding(horizontal = 20.dp)) }
            }
            items(vm.feed, key = { "act" + it.id }) { a ->
                Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 6.dp)) {
                    Text(a.at?.let { t -> Regex("""\d{2}:\d{2}""").find(t)?.value } ?: "", style = MaterialTheme.typography.bodyMedium, color = Qwik.N600, modifier = Modifier.width(52.dp))
                    Text(
                        listOfNotNull(a.actionLabel ?: a.action, a.entityLabel ?: a.entityId).joinToString(" · "),
                        style = MaterialTheme.typography.bodyMedium, color = Qwik.N800,
                        modifier = Modifier.weight(1f).then(if (a.personId != null) Modifier.clickable { onOpenPerson(a.personId) } else Modifier),
                    )
                }
            }
            item { Spacer(Modifier.height(28.dp)) }
        }
    }
    Rule()
    BarButton("New rider", onClick = onNewRider, modifier = Modifier.fillMaxWidth())
    }
}

@Composable
private fun StoreHeader(store: TodoStore) {
    Row(
        Modifier.fillMaxWidth().background(Qwik.Surface).padding(horizontal = 20.dp, vertical = 9.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(store.hub.ifBlank { "Misc" }, style = MaterialTheme.typography.titleMedium, color = Qwik.Ink, modifier = Modifier.weight(1f))
        Kicker(listOfNotNull(store.zone, "${store.items.size} to do").joinToString(" · "))
    }
    Hairline()
}

@Composable
private fun TodoRow(t: TodoItem, onOpen: () -> Unit, onCall: (() -> Unit)?) {
    val (tag, accent, sub) = when (t.kind) {
        "cod" -> Triple("COD", true, "Holding " + rupees(t.codOutstanding) + " COD · " + t.companies.joinToString(", "))
        "ev_dues" -> Triple(
            "dues", true,
            (t.evId ?: "EV") + " · owes " + rupees(t.totalDues) +
                listOfNotNull(
                    t.outstanding?.takeIf { it > 0 }?.let { "rent " + rupees(it) },
                    t.duesOutstanding?.takeIf { it > 0 }?.let { "dues " + rupees(it) },
                ).joinToString(" + ").let { if (it.isBlank()) "" else " ($it)" },
        )
        else -> Triple(
            "inactive", false,
            (t.evId ?: "EV") + (t.evModel?.let { " · $it" } ?: "") + " · with them since " + shortDate(t.handoverDate) + " · no active rider id",
        )
    }
    Column(Modifier.fillMaxWidth()) {
        Row(Modifier.fillMaxWidth().clickable(onClick = onOpen).padding(start = 20.dp, end = 20.dp, top = 14.dp, bottom = 10.dp)) {
            Box(Modifier.width(4.dp).height(44.dp).background(if (accent) Qwik.Accent else Qwik.N500))
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(t.name, style = MaterialTheme.typography.titleLarge, color = Qwik.Ink)
                Text(sub, style = MaterialTheme.typography.bodyMedium, color = Qwik.N700)
            }
            Spacer(Modifier.width(8.dp))
            Tag(tag, accent = accent)
        }
        Row(Modifier.padding(start = 36.dp, end = 20.dp, bottom = 6.dp), horizontalArrangement = Arrangement.spacedBy(18.dp)) {
            if (onCall != null) GhostAction("Call", onClick = onCall)
            GhostAction("Open rider", onClick = onOpen, color = Qwik.Accent700)
        }
        Hairline()
    }
}
