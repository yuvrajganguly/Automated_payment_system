package com.qwikserve.recruiter.ui.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.rememberModalBottomSheetState
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
import com.qwikserve.recruiter.data.api.RecruiterRider
import com.qwikserve.recruiter.data.api.RecruiterSeries
import com.qwikserve.recruiter.ui.common.GhostAction
import com.qwikserve.recruiter.ui.common.Hairline
import com.qwikserve.recruiter.ui.common.Kicker
import com.qwikserve.recruiter.ui.common.ListRow
import com.qwikserve.recruiter.ui.common.Note
import com.qwikserve.recruiter.ui.common.NumberTile
import com.qwikserve.recruiter.ui.common.Rule
import com.qwikserve.recruiter.ui.common.Segmented
import com.qwikserve.recruiter.ui.common.Tag
import com.qwikserve.recruiter.ui.common.km
import com.qwikserve.recruiter.ui.common.monthName
import com.qwikserve.recruiter.ui.common.shortDate
import com.qwikserve.recruiter.ui.theme.Qwik
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import java.io.IOException
import java.time.LocalDate
import javax.inject.Inject

/**
 * The four periods behind the count tiles, cut the same way the server cuts
 * them for `/app/my-recruiting`: the week starts on Monday and the month on
 * the first. Getting this wrong would make a tile and its drilldown disagree,
 * which is worse than having no drilldown at all.
 */
enum class Period(val label: String, val status: String = "all", val fixedStatus: Boolean = false) {
    TODAY("Onboarded today"),
    WEEK("Onboarded this week"),
    MONTH("Onboarded this month"),
    ALL("Everyone you onboarded"),

    /** The two tiles that are a filter rather than a date window. Both fix the
     *  status, because widening it would list people the tile did not count. */
    ACTIVE("Still active", status = "working", fixedStatus = true),
    HOLDING("Holding an EV", status = "holding", fixedStatus = true);

    /** Inclusive first day, or null for all time. */
    fun start(today: LocalDate): LocalDate? = when (this) {
        TODAY -> today
        WEEK -> today.minusDays((today.dayOfWeek.value - 1).toLong())
        MONTH -> today.withDayOfMonth(1)
        ALL, ACTIVE, HOLDING -> null
    }
}

@HiltViewModel
class StatsViewModel @Inject constructor(private val api: PayoutApi) : ViewModel() {
    var data by mutableStateOf<MyRecruiting?>(null)
        private set
    var refreshing by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    /* Week by week / month by month. */
    var grain by mutableStateOf("week")
        private set
    var series by mutableStateOf<RecruiterSeries?>(null)
        private set
    var seriesError by mutableStateOf<String?>(null)
        private set
    var loadingSeries by mutableStateOf(false)
        private set

    /* The drilldown behind a tile. */
    var drill by mutableStateOf<Period?>(null)
        private set
    var drillStatus by mutableStateOf("all") // all | working | idle
        private set
    var drillRows by mutableStateOf<List<RecruiterRider>>(emptyList())
        private set
    var drillError by mutableStateOf<String?>(null)
        private set
    var loadingDrill by mutableStateOf(false)
        private set

    init { refresh() } // refresh() pulls the series too

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
        loadSeries()
    }

    fun chooseGrain(g: String) {
        if (g == grain) return
        grain = g
        series = null
        loadSeries()
    }

    fun loadSeries() {
        if (loadingSeries) return
        loadingSeries = true
        val g = grain
        viewModelScope.launch {
            try {
                val s = api.mySeries(grain = g, buckets = 12)
                if (grain == g) { series = s; seriesError = null }
            } catch (e: IOException) {
                if (grain == g) seriesError = "Offline — your week-by-week needs the server."
            } catch (e: Exception) {
                if (grain == g) seriesError = e.message ?: "Could not load your performance"
            } finally {
                loadingSeries = false
            }
        }
    }

    /* ── drilldown ── */

    fun openDrill(period: Period) {
        drill = period
        drillStatus = period.status
        drillRows = emptyList()
        drillError = null
        loadDrill()
    }

    fun closeDrill() { drill = null; drillRows = emptyList(); drillError = null }

    fun chooseDrillStatus(status: String) {
        if (status == drillStatus) return
        drillStatus = status
        loadDrill()
    }

    /** The server lists everyone this recruiter onboarded, flagged working or
     *  idle; the period is applied here so a tile and its list agree. */
    fun loadDrill() {
        val period = drill ?: return
        if (loadingDrill) return
        loadingDrill = true; drillError = null
        val status = drillStatus
        viewModelScope.launch {
            try {
                val all = api.myRiders(status = status, limit = 500)
                val from = period.start(LocalDate.now())?.toString()
                val rows = if (from == null) all else all.filter { (it.createdAt ?: "").take(10) >= from }
                if (drill == period && drillStatus == status) { drillRows = rows; drillError = null }
            } catch (e: IOException) {
                if (drill == period) drillError = "Offline — this list needs the server."
            } catch (e: Exception) {
                if (drill == period) drillError = e.message ?: "Could not load that list"
            } finally {
                loadingDrill = false
            }
        }
    }
}

/** "My numbers": how many riders this recruiter has onboarded, where, and —
 *  the part that matters — how many of them are still working. */
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
                // Every count is a door: tapping one lists the riders behind it.
                Row(Modifier.fillMaxWidth()) {
                    NumberTile(
                        (c?.today ?: 0).toString(), "Today", Modifier.weight(1f),
                        accent = (c?.today ?: 0) > 0, onClick = { vm.openDrill(Period.TODAY) },
                    )
                    Box(Modifier.width(1.dp).height(78.dp).background(Qwik.N400))
                    NumberTile(
                        (c?.week ?: 0).toString(), "This week", Modifier.weight(1f),
                        onClick = { vm.openDrill(Period.WEEK) },
                    )
                    Box(Modifier.width(1.dp).height(78.dp).background(Qwik.N400))
                    NumberTile(
                        (c?.month ?: 0).toString(), "This month", Modifier.weight(1f),
                        onClick = { vm.openDrill(Period.MONTH) },
                    )
                }
                Rule()
                Row(Modifier.fillMaxWidth()) {
                    // People, not rider ids. Somebody with an id at two
                    // companies is one recruit — this tile used to say 3 where
                    // it meant 2, with a footnote underneath explaining that.
                    NumberTile(
                        (c?.allTime ?: 0).toString(), "All time", Modifier.weight(1f),
                        onClick = { vm.openDrill(Period.ALL) },
                    )
                    Box(Modifier.width(1.dp).height(78.dp).background(Qwik.N400))
                    NumberTile(
                        (c?.active ?: 0).toString(), "Still active", Modifier.weight(1f),
                        onClick = { vm.openDrill(Period.ACTIVE) },
                    )
                    Box(Modifier.width(1.dp).height(78.dp).background(Qwik.N400))
                    NumberTile(
                        (c?.evHolders ?: 0).toString(), "Holding an EV", Modifier.weight(1f),
                        onClick = { vm.openDrill(Period.HOLDING) },
                    )
                }
                Rule()
                Text(
                    "Tap any count to see who is behind it. \"Still active\" is the same "
                        + "12-day rule the Riders tab uses"
                        + (c?.onRoster?.let { " — $it are still on the roster" } ?: "") + ".",
                    style = MaterialTheme.typography.bodySmall, color = Qwik.N600,
                    modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp),
                )
            }

            /* ── week by week / month by month ── */
            item { PerformanceHeader(vm) }
            val s = vm.series
            if (s != null && s.series.isNotEmpty()) {
                val max = s.series.maxOf { it.onboarded }.coerceAtLeast(1)
                items(s.series.asReversed(), key = { "b" + vm.grain + it.bucket }) { b ->
                    BucketRow(
                        label = if (vm.grain == "month") monthName(b.bucket) else "Week of " + shortDate(b.bucket),
                        onboarded = b.onboarded,
                        stillWorking = b.stillWorking,
                        evs = b.evsDeployed,
                        distance = b.km,
                        max = max,
                    )
                }
                item {
                    Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp)) {
                        Text(
                            "${s.totals.onboarded} onboarded · ${s.totals.stillWorking} still working · " +
                                "${s.totals.evsDeployed} EVs · " + km(s.totals.km),
                            style = MaterialTheme.typography.bodyMedium, color = Qwik.N800,
                        )
                    }
                    Text(
                        "\"Still working\" is a cohort figure: of the riders you signed up in that " +
                            "bucket, how many a company has paid in the last ${s.activeWithinDays} days.",
                        style = MaterialTheme.typography.bodySmall, color = Qwik.N600,
                        modifier = Modifier.padding(horizontal = 20.dp).padding(bottom = 8.dp),
                    )
                }
            } else if (s != null) {
                item { Note("Nothing to chart yet — the weeks fill in as you onboard.") }
            } else if (vm.seriesError != null) {
                item {
                    Column(Modifier.padding(horizontal = 20.dp, vertical = 10.dp)) {
                        Text(vm.seriesError!!, style = MaterialTheme.typography.bodyMedium, color = Qwik.Accent700)
                        GhostAction("Try again", onClick = vm::loadSeries)
                    }
                }
            } else {
                item { Note("Loading your week-by-week…") }
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

    val period = vm.drill
    if (period != null) {
        val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
        ModalBottomSheet(onDismissRequest = vm::closeDrill, sheetState = sheet, containerColor = Qwik.Bg) {
            DrilldownSheet(
                period = period,
                vm = vm,
                onOpenPerson = { id -> vm.closeDrill(); onOpenPerson(id) },
            )
        }
    }
}

@Composable
private fun PerformanceHeader(vm: StatsViewModel) {
    Column(Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, top = 20.dp, bottom = 10.dp)) {
        Kicker("How you are doing")
        Spacer(Modifier.height(8.dp))
        Segmented(
            listOf("Week by week", "Month by month"),
            selected = if (vm.grain == "week") 0 else 1,
            onSelect = { vm.chooseGrain(if (it == 0) "week" else "month") },
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

/**
 * One bucket. The pale bar is everyone signed up that week or month; the red
 * one inside it is how many of them a company has paid recently. The gap
 * between the two is the number worth arguing about, so both are always drawn
 * even when the second is zero.
 */
@Composable
private fun BucketRow(
    label: String,
    onboarded: Int,
    stillWorking: Int,
    evs: Int,
    distance: Int,
    max: Int,
) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(label, style = MaterialTheme.typography.titleMedium, color = Qwik.Ink, modifier = Modifier.weight(1f))
            Text(
                "$onboarded · $stillWorking working",
                style = MaterialTheme.typography.bodyMedium,
                color = if (stillWorking > 0) Qwik.Ink else Qwik.N600,
            )
        }
        Spacer(Modifier.height(6.dp))
        Box(Modifier.fillMaxWidth().height(10.dp).background(Qwik.N200)) {
            Box(Modifier.fillMaxWidth(onboarded / max.toFloat()).height(10.dp).background(Qwik.N400))
            Box(Modifier.fillMaxWidth(stillWorking / max.toFloat()).height(10.dp).background(Qwik.Accent))
        }
        if (evs > 0 || distance > 0) {
            Spacer(Modifier.height(5.dp))
            Text(
                listOfNotNull(
                    evs.takeIf { it > 0 }?.let { "$it EV" + if (it == 1) "" else "s" },
                    distance.takeIf { it > 0 }?.let { km(it) },
                ).joinToString(" · "),
                style = MaterialTheme.typography.bodySmall, color = Qwik.N600,
            )
        }
    }
    Hairline()
}

/** The riders behind one tile, each with whether they are still working. */
@Composable
private fun DrilldownSheet(period: Period, vm: StatsViewModel, onOpenPerson: (Long) -> Unit) {
    Column(Modifier.fillMaxWidth().imePadding().padding(bottom = 24.dp)) {
        Column(Modifier.padding(horizontal = 20.dp)) {
            Text(period.label, style = MaterialTheme.typography.headlineSmall, color = Qwik.Ink)
            Spacer(Modifier.height(4.dp))
            Kicker("${vm.drillRows.size} shown")
            Spacer(Modifier.height(12.dp))
            // The date tiles can be widened or narrowed by status. The two
            // filter tiles cannot: "Still active" IS the working filter and
            // "Holding an EV" IS the EV one, so a chip row here would only
            // offer ways to stop showing what was tapped.
            if (!period.fixedStatus) {
                Segmented(
                    listOf("All", "Working", "Idle"),
                    selected = when (vm.drillStatus) { "working" -> 1; "idle" -> 2; else -> 0 },
                    onSelect = { vm.chooseDrillStatus(listOf("all", "working", "idle")[it]) },
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(12.dp))
            }
        }
        Rule()
        when {
            vm.drillError != null -> Column(Modifier.padding(horizontal = 20.dp)) {
                Note(vm.drillError!!, color = Qwik.Accent700)
                GhostAction("Try again", onClick = vm::loadDrill)
            }
            vm.loadingDrill && vm.drillRows.isEmpty() -> Note("Loading…")
            vm.drillRows.isEmpty() -> Note(
                when {
                    period == Period.HOLDING -> "None of your riders has an EV out right now."
                    period == Period.ACTIVE ->
                        "None of your riders has been paid for a cycle in the last 12 days."
                    vm.drillStatus == "working" ->
                        "Nobody from this period has been paid in the last 12 days."
                    vm.drillStatus == "idle" -> "Everybody from this period is still working."
                    else -> "Nobody onboarded in this period."
                },
            )
            else -> LazyColumn(Modifier.fillMaxWidth().heightIn(max = 460.dp)) {
                items(vm.drillRows, key = { it.riderId + "@" + it.companyName }) { r ->
                    ListRow(
                        title = r.name ?: r.riderId,
                        sub = listOfNotNull(
                            r.riderId,
                            r.hub,
                            r.createdAt?.let { "added " + shortDate(it) },
                            r.lastWorkedOn?.let { "last worked " + shortDate(it) } ?: "never worked",
                        ).joinToString(" · "),
                        onClick = { onOpenPerson(r.personId) },
                        trailing = {
                            Column(
                                horizontalAlignment = Alignment.End,
                                verticalArrangement = Arrangement.spacedBy(4.dp),
                            ) {
                                Tag(r.companyName, outline = true)
                                // On the EV list the vehicle is the point; on
                                // the others whether they are working is.
                                if (period == Period.HOLDING && r.evId != null) {
                                    Tag(r.evId, accent = true)
                                } else {
                                    Tag(if (r.working) "working" else "idle", accent = r.working)
                                }
                            }
                        },
                    )
                }
            }
        }
    }
}
