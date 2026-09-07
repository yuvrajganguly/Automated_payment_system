package com.qwikserve.recruiter.ui.stats

import androidx.compose.foundation.background
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
import com.qwikserve.recruiter.data.api.MyRecruiting
import com.qwikserve.recruiter.data.api.PayoutApi
import com.qwikserve.recruiter.ui.common.Hairline
import com.qwikserve.recruiter.ui.common.Kicker
import com.qwikserve.recruiter.ui.common.ListRow
import com.qwikserve.recruiter.ui.common.Note
import com.qwikserve.recruiter.ui.common.NumberTile
import com.qwikserve.recruiter.ui.common.Rule
import com.qwikserve.recruiter.ui.common.Tag
import com.qwikserve.recruiter.ui.common.shortDate
import com.qwikserve.recruiter.ui.theme.Qwik
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import java.io.IOException
import javax.inject.Inject

@HiltViewModel
class StatsViewModel @Inject constructor(private val api: PayoutApi) : ViewModel() {
    var data by mutableStateOf<MyRecruiting?>(null)
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
                data = api.myRecruiting()
            } catch (e: IOException) {
                error = if (data == null) "Can't reach the server — pull down to try again." else null
            } catch (e: Exception) {
                error = e.message ?: "Could not load your numbers"
            } finally {
                refreshing = false
            }
        }
    }
}

/** "My numbers": how many riders this recruiter has onboarded, and where. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StatsScreen(onOpenPerson: (Long) -> Unit, vm: StatsViewModel = hiltViewModel()) {
    val d = vm.data
    val c = d?.counts
    PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize()) {
        LazyColumn(Modifier.fillMaxSize()) {
            item {
                Column(Modifier.padding(start = 20.dp, end = 20.dp, top = 14.dp, bottom = 12.dp)) {
                    Text("My numbers", style = MaterialTheme.typography.headlineLarge, color = Qwik.Ink)
                    Spacer(Modifier.height(6.dp))
                    Kicker("Riders you onboarded" + (d?.asOf?.let { " · as of " + shortDate(it) } ?: ""))
                }
                Rule()
            }
            if (vm.error != null) item { Note(vm.error!!, color = Qwik.Accent700) }
            item {
                Row(Modifier.fillMaxWidth()) {
                    NumberTile((c?.today ?: 0).toString(), "Today", Modifier.weight(1f), accent = (c?.today ?: 0) > 0)
                    Box(Modifier.width(1.dp).height(78.dp).background(Qwik.N400))
                    NumberTile((c?.week ?: 0).toString(), "This week", Modifier.weight(1f))
                    Box(Modifier.width(1.dp).height(78.dp).background(Qwik.N400))
                    NumberTile((c?.month ?: 0).toString(), "This month", Modifier.weight(1f))
                }
                Rule()
                Row(Modifier.fillMaxWidth()) {
                    NumberTile((c?.allTime ?: 0).toString(), "All time", Modifier.weight(1f))
                    Box(Modifier.width(1.dp).height(78.dp).background(Qwik.N400))
                    NumberTile((c?.active ?: 0).toString(), "Still active", Modifier.weight(1f))
                    Box(Modifier.width(1.dp).height(78.dp).background(Qwik.N400))
                    NumberTile((c?.evHolders ?: 0).toString(), "Holding an EV", Modifier.weight(1f))
                }
                Rule()
                if ((c?.persons ?: 0) != (c?.allTime ?: 0) && c != null) {
                    Text(
                        "${c.allTime} rider ids across ${c.persons} people — a person with two company ids counts twice.",
                        style = MaterialTheme.typography.bodySmall, color = Qwik.N700,
                        modifier = Modifier.padding(horizontal = 20.dp, vertical = 10.dp),
                    )
                }
            }
            if (d != null && d.byCompany.isNotEmpty()) {
                item { Kicker("By company", Modifier.padding(start = 20.dp, top = 18.dp, bottom = 4.dp)) }
                val max = d.byCompany.maxOf { it.riders }.coerceAtLeast(1)
                items(d.byCompany, key = { "co" + it.companyName }) { co ->
                    Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(co.companyName, style = MaterialTheme.typography.titleMedium, color = Qwik.Ink, modifier = Modifier.weight(1f))
                            Text("${co.riders}" + if (co.active != co.riders) " · ${co.active} active" else "", style = MaterialTheme.typography.bodyMedium, color = Qwik.N700)
                        }
                        Spacer(Modifier.height(6.dp))
                        Row(Modifier.fillMaxWidth().height(8.dp).background(Qwik.N200)) {
                            Box(Modifier.fillMaxWidth(co.riders / max.toFloat()).height(8.dp).background(Qwik.Accent))
                        }
                    }
                    Hairline()
                }
            }
            if (d != null) {
                item { Kicker("Latest onboardings", Modifier.padding(start = 20.dp, top = 18.dp, bottom = 4.dp)) }
                if (d.recent.isEmpty()) item { Note("Nobody yet. Riders you add show up here.") }
                items(d.recent, key = { it.riderId + "@" + it.companyName }) { r ->
                    ListRow(
                        title = r.name ?: r.riderId,
                        sub = listOfNotNull(r.riderId, r.hub, r.createdAt?.let { shortDate(it) }).joinToString(" · "),
                        onClick = { onOpenPerson(r.personId) },
                        trailing = {
                            Row {
                                Tag(r.companyName, outline = true)
                                if (!r.isActive) { Spacer(Modifier.width(6.dp)); Tag("inactive") }
                            }
                        },
                    )
                }
            }
            item { Spacer(Modifier.height(28.dp)) }
        }
    }
}
