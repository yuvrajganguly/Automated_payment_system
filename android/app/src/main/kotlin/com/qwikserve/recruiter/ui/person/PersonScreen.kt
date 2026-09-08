package com.qwikserve.recruiter.ui.person

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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.qwikserve.recruiter.data.api.PayoutApi
import com.qwikserve.recruiter.data.api.PersonOut
import com.qwikserve.recruiter.data.api.TimelineEvent
import com.qwikserve.recruiter.data.db.RiderEntity
import com.qwikserve.recruiter.data.repo.PhotoRepository
import com.qwikserve.recruiter.data.repo.RiderRepository
import com.qwikserve.recruiter.ui.common.GhostAction
import com.qwikserve.recruiter.ui.evs.CloseoutSheet
import com.qwikserve.recruiter.ui.evs.EvActionsViewModel
import com.qwikserve.recruiter.ui.evs.GiveEvSheet
import com.qwikserve.recruiter.ui.common.Hairline
import com.qwikserve.recruiter.ui.common.Kicker
import com.qwikserve.recruiter.ui.common.PhotoTile
import com.qwikserve.recruiter.ui.common.Rule
import com.qwikserve.recruiter.ui.common.Skeleton
import com.qwikserve.recruiter.ui.common.Tag
import com.qwikserve.recruiter.ui.common.rupees
import com.qwikserve.recruiter.ui.common.shortDate
import com.qwikserve.recruiter.ui.common.shortStamp
import com.qwikserve.recruiter.ui.theme.Qwik
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.io.IOException
import javax.inject.Inject
@HiltViewModel
class PersonViewModel @Inject constructor(
    saved: SavedStateHandle,
    private val repo: RiderRepository,
    private val photos: PhotoRepository,
    private val api: PayoutApi,
) : ViewModel() {
    /** Which rider this screen is showing. It arrives as a navigation argument
     *  on a phone, and as a selection in the second pane on a tablet — where
     *  the same view model is re-pointed at whoever was tapped. */
    private val _personId = MutableStateFlow(saved.get<Long>("personId") ?: 0L)
    val personId: Long get() = _personId.value

    /** Cached rider rows paint the screen at once; the live person fills the rest. */
    @OptIn(ExperimentalCoroutinesApi::class)
    val cached: StateFlow<List<RiderEntity>> = _personId
        .flatMapLatest { id -> if (id == 0L) flowOf(emptyList<RiderEntity>()) else repo.forPerson(id) }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())
    var person by mutableStateOf<PersonOut?>(null)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    /** What has happened to this rider, newest first — added, EV handed over,
     *  returned, sent for repair, closed out. Every hand that touched them,
     *  not only this recruiter's own rows. */
    var timeline by mutableStateOf<List<TimelineEvent>>(emptyList())
        private set
    var timelineError by mutableStateOf<String?>(null)
        private set
    var loadingTimeline by mutableStateOf(false)
        private set

    /** Bumped after a new photo lands, so the cached thumbnail is re-fetched. */
    var photoVersion by mutableStateOf(0)
        private set
    var uploadingPhoto by mutableStateOf(false)
        private set

    init { if (personId != 0L) load() }

    /** Camera or gallery → the rider's profile picture. */
    fun setPhoto(uri: Uri) {
        if (uploadingPhoto) return
        val id = _personId.value
        uploadingPhoto = true
        viewModelScope.launch {
            runCatching { photos.uploadPhoto(id, uri) }
                .onSuccess { if (_personId.value == id) photoVersion++ }
                .onFailure { error = "The photo did not upload. Try again when the signal is better." }
            uploadingPhoto = false
        }
    }

    /** Point the screen at a rider (no-op if it is already there). */
    fun show(id: Long) {
        if (id == 0L || id == _personId.value) return
        _personId.value = id
        person = null
        error = null
        timeline = emptyList()
        timelineError = null
        load()
    }

    fun load() {
        val id = _personId.value
        viewModelScope.launch {
            try {
                val p = repo.person(id)
                if (_personId.value == id) { person = p; error = null }
            } catch (e: IOException) {
                if (_personId.value == id) error = "Offline — showing what was last synced."
            } catch (e: Exception) {
                if (_personId.value == id) error = e.message ?: "Could not load this rider"
            }
        }
        loadTimeline()
    }

    /** The timeline is a separate call and a separate failure: a rider's page
     *  still works when the history does not come back. */
    fun loadTimeline() {
        val id = _personId.value
        if (id == 0L || loadingTimeline) return
        loadingTimeline = true
        viewModelScope.launch {
            try {
                val rows = api.personTimeline(id, limit = 100)
                if (_personId.value == id) { timeline = rows; timelineError = null }
            } catch (e: IOException) {
                if (_personId.value == id && timeline.isEmpty()) {
                    timelineError = "Offline — the history needs the server."
                }
            } catch (e: Exception) {
                if (_personId.value == id) timelineError = e.message ?: "Could not load the history"
            } finally {
                loadingTimeline = false
            }
        }
    }
}

/**
 * A rider's page. Full screen on a phone (with a Back action), or the right
 * half of a tablet — [embedded] drops the status-bar padding the shell has
 * already applied and renames Back to what it does there: clear the pane.
 */
@Composable
fun PersonScreen(
    personId: Long,
    onBack: () -> Unit,
    embedded: Boolean = false,
    vm: PersonViewModel = hiltViewModel(),
) {
    LaunchedEffect(personId) { vm.show(personId) }
    val evActions: EvActionsViewModel = hiltViewModel()
    var giving by remember { mutableStateOf(false) }
    var evNote by remember { mutableStateOf<String?>(null) }
    // True from the moment this page asks for the vehicle back until the
    // deposit question that follows is done with. On a tablet this page and
    // the EVs tab share one EvActionsViewModel, so each only answers its own.
    var takingBack by remember(personId) { mutableStateOf(false) }
    val cached by vm.cached.collectAsStateWithLifecycle()
    val p = vm.person
    val name = p?.displayName ?: cached.firstOrNull()?.name
    val ctx = LocalContext.current

    Surface(Modifier.fillMaxSize(), color = Qwik.Bg) {
        Column(if (embedded) Modifier.fillMaxSize() else Modifier.fillMaxSize().statusBarsPadding()) {
            // Masthead: back, name, identity line.
            Column(Modifier.padding(start = 20.dp, end = 12.dp, top = 8.dp, bottom = 12.dp)) {
                GhostAction(if (embedded) "✕ Close" else "← Back", onClick = onBack, color = Qwik.Accent)
                Row(verticalAlignment = Alignment.Bottom) {
                    Column(Modifier.weight(1f)) {
                        Text(name ?: "Rider", style = MaterialTheme.typography.headlineLarge, color = Qwik.Ink)
                        Spacer(Modifier.height(6.dp))
                        val ids = p?.aadhaarNo?.let { "Aadhaar " + it.chunked(4).joinToString(" ") }
                        val pan = p?.panNo?.let { "PAN $it" }
                        val line = listOfNotNull(ids, pan).joinToString(" · ")
                        when {
                            line.isNotEmpty() -> Text(line, style = MaterialTheme.typography.bodyMedium, color = Qwik.N700)
                            p != null -> Text("No Aadhaar / PAN on file", style = MaterialTheme.typography.bodyMedium, color = Qwik.N700)
                            else -> Skeleton(140.dp, 12.dp)
                        }
                    }
                    Spacer(Modifier.width(12.dp))
                    PhotoTile(
                        picked = null,
                        personId = personId,
                        name = name,
                        version = vm.photoVersion,
                        size = 72.dp,
                        busy = vm.uploadingPhoto,
                        onPicked = vm::setPhoto,
                    )
                }
            }
            Rule()
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                if (vm.error != null) {
                    Text(vm.error!!, color = Qwik.Accent700, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(20.dp, 10.dp))
                }
                // Standing — visible to recruiters so they never ask for money already added.
                val bal = p?.currentBalance
                val arr = p?.arrearsOutstanding
                val dues = if (bal != null && arr != null) (arr - bal).coerceAtLeast(0.0) else null
                Row(Modifier.fillMaxWidth()) {
                    Standing("Balance", if (p == null) "…" else rupees(bal), Modifier.weight(1f), accent = (bal ?: 0.0) < 0)
                    Box(Modifier.width(1.dp).height(74.dp).background(Qwik.N400))
                    Standing("EV arrears", if (p == null) "…" else rupees(arr), Modifier.weight(1f), accent = (arr ?: 0.0) > 0)
                    Box(Modifier.width(1.dp).height(74.dp).background(Qwik.N400))
                    Standing("Total dues", if (p == null) "…" else rupees(dues), Modifier.weight(1f), accent = (dues ?: 0.0) > 0)
                }
                Rule()

                Kicker("EV", Modifier.padding(start = 20.dp, top = 20.dp, bottom = 6.dp))
                val ev = p?.ev
                when {
                    p == null -> Skeleton(200.dp)
                    ev == null -> Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp)) {
                        Text("No EV assigned.", style = MaterialTheme.typography.bodyLarge, color = Qwik.N700)
                        Spacer(Modifier.height(6.dp))
                        GhostAction("Give an EV", onClick = { evNote = null; giving = true })
                    }
                    else -> Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 6.dp)) {
                        Text("${ev.evId} · ${ev.provider} ${ev.model}", style = MaterialTheme.typography.titleLarge, color = Qwik.Ink)
                        Text(
                            listOfNotNull(
                                ev.handoverDate?.let { "Since " + shortDate(it) },
                                ev.rentChargedThrough?.let { "rent through " + shortDate(it) },
                                rupees(ev.weeklyRate) + "/wk",
                            ).joinToString(" · "),
                            style = MaterialTheme.typography.bodyMedium, color = Qwik.N700,
                        )
                        Spacer(Modifier.height(8.dp))
                        // Taking a vehicle back is two different things, and the
                        // difference matters to the fleet: a spare goes to the
                        // next rider, a return goes to the provider.
                        Row(horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                            GhostAction(
                                if (evActions.busy) "Working…" else "Take back — spare",
                                onClick = {
                                    takingBack = true
                                    evActions.toSpare(ev.evId) { m -> takingBack = false; evNote = m; vm.load() }
                                },
                                enabled = !evActions.busy,
                            )
                            GhostAction(
                                "Return to provider",
                                onClick = {
                                    takingBack = true
                                    evActions.returnUnit(ev.evId) { m -> takingBack = false; evNote = m; vm.load() }
                                },
                                enabled = !evActions.busy,
                            )
                        }
                    }
                }
                (evNote ?: evActions.error)?.let {
                    Text(
                        it,
                        style = MaterialTheme.typography.bodySmall,
                        color = if (evActions.error != null) Qwik.Accent700 else Qwik.N700,
                        modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp),
                    )
                }

                Kicker("Rider ids", Modifier.padding(start = 20.dp, top = 20.dp, bottom = 2.dp))
                val rows = p?.riders?.map { RiderLine(it.riderId, it.company, it.hub, it.mobNo, it.accountNo, it.ifsc, it.isActive, it.recruitedBy) }
                    ?: cached.map { RiderLine(it.riderId, it.company, it.hub, it.mobNo, it.accountNo, it.ifsc, it.isActive, it.recruitedBy) }
                if (rows.isEmpty()) Skeleton(220.dp)
                rows.forEach { r ->
                    Hairline()
                    Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text(r.riderId, style = MaterialTheme.typography.titleLarge, color = Qwik.Ink)
                            Tag(r.company, outline = true)
                            if (!r.active) Tag("inactive")
                        }
                        val detail = listOfNotNull(
                            r.hub,
                            r.phone,
                            r.account?.let { "A/c $it" + (r.ifsc?.let { i -> " · $i" } ?: "") } ?: "no account on file",
                        ).joinToString(" · ")
                        Text(detail, style = MaterialTheme.typography.bodyMedium, color = Qwik.N700, modifier = Modifier.padding(top = 3.dp))
                        r.recruitedBy?.let {
                            Text("Onboarded by " + it.substringBefore('@'), style = MaterialTheme.typography.bodySmall, color = Qwik.N600)
                        }
                    }
                }
                Hairline()

                val phone = rows.firstNotNullOfOrNull { it.phone }
                if (phone != null) {
                    Row(Modifier.padding(horizontal = 20.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                        GhostAction("Call $phone", onClick = {
                            ctx.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:" + phone.filter { it.isDigit() || it == '+' })))
                        })
                    }
                }

                Timeline(
                    events = vm.timeline,
                    loading = vm.loadingTimeline,
                    error = vm.timelineError,
                    onRetry = vm::loadTimeline,
                )
                Spacer(Modifier.height(32.dp))
            }
        }
    }

    if (giving) {
        GiveEvSheet(
            personId = personId,
            personName = name,
            onDone = { message -> evNote = message; giving = false; vm.load() },
            onDismiss = { giving = false },
            vm = evActions,
        )
    }

    // A vehicle taken back from this page raises the same deposit question the
    // EVs tab asks, and it is the same person standing there holding it. Left
    // unanswered it waits on the EVs tab; either way the page reloads, because
    // by now the rider has no EV.
    evActions.prompt?.takeIf { takingBack && it.personId == personId }?.let { row ->
        val done = { message: String ->
            evNote = message
            takingBack = false
            evActions.dismissPrompt()
            vm.load()
        }
        CloseoutSheet(
            row = row,
            onDone = { message -> done(evActions.promptNote + " · " + message) },
            onDismiss = { done(evActions.promptNote) },
        )
    }
}

/**
 * What has happened to this rider, newest first. One row per event: when, what
 * (the server's own phrase), who did it, and the thing it was done to when
 * that adds anything. The 2 px ink rail down the left is the design's;
 * the square dot is where an event sits on it.
 */
@Composable
private fun Timeline(
    events: List<TimelineEvent>,
    loading: Boolean,
    error: String?,
    onRetry: () -> Unit,
) {
    Kicker("Timeline", Modifier.padding(start = 20.dp, top = 24.dp, bottom = 8.dp))
    when {
        error != null -> Column(Modifier.padding(horizontal = 20.dp)) {
            Text(error, style = MaterialTheme.typography.bodyMedium, color = Qwik.Accent700)
            Spacer(Modifier.height(4.dp))
            GhostAction("Try again", onClick = onRetry)
        }
        events.isEmpty() && loading -> Column(Modifier.padding(horizontal = 20.dp)) {
            repeat(3) {
                Skeleton(220.dp)
                Spacer(Modifier.height(10.dp))
            }
        }
        events.isEmpty() -> Text(
            "Nothing logged for this rider yet. Everything done from the app — EVs, documents, edits — lands here.",
            style = MaterialTheme.typography.bodyMedium,
            color = Qwik.N700,
            modifier = Modifier.padding(horizontal = 20.dp),
        )
        else -> Column(Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp)) {
            events.forEachIndexed { i, e ->
                Row(Modifier.fillMaxWidth()) {
                    // The rail: a dot on a hairline that runs on to the next
                    // event, and stops at the last one.
                    Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.width(14.dp)) {
                        Spacer(Modifier.height(6.dp))
                        Box(Modifier.size(8.dp).background(if (i == 0) Qwik.Accent else Qwik.N500))
                        if (i < events.lastIndex) {
                            Box(Modifier.width(2.dp).height(36.dp).background(Qwik.N300))
                        }
                    }
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f).padding(bottom = 14.dp)) {
                        Text(
                            shortStamp(e.at).ifBlank { "—" },
                            style = MaterialTheme.typography.bodySmall,
                            color = Qwik.N600,
                        )
                        Text(
                            e.actionLabel ?: e.action,
                            style = MaterialTheme.typography.titleMedium,
                            color = Qwik.Ink,
                        )
                        val who = e.email?.substringBefore('@')
                        // The entity only earns a mention when it names
                        // something — an EV id, a document — rather than
                        // repeating the person this page is already about.
                        val what = (e.entityLabel ?: e.entityId)
                            ?.takeIf { it.isNotBlank() && e.entityType != "person" }
                        val line = listOfNotNull(what, who?.let { "by $it" }).joinToString(" · ")
                        if (line.isNotBlank()) {
                            Text(line, style = MaterialTheme.typography.bodyMedium, color = Qwik.N700)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun Standing(label: String, value: String, modifier: Modifier = Modifier, accent: Boolean = false) {
    Column(modifier.padding(horizontal = 14.dp, vertical = 14.dp)) {
        Kicker(label)
        Spacer(Modifier.height(5.dp))
        Text(value, style = MaterialTheme.typography.headlineSmall, color = if (accent) Qwik.Accent else Qwik.Ink, maxLines = 1)
    }
}

private data class RiderLine(
    val riderId: String, val company: String, val hub: String?, val phone: String?,
    val account: String?, val ifsc: String?, val active: Boolean, val recruitedBy: String?,
)
