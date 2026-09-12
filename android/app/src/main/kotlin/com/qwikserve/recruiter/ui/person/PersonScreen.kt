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
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.rememberModalBottomSheetState
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
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.qwikserve.recruiter.data.api.ApiError
import com.qwikserve.recruiter.data.api.PayoutApi
import com.qwikserve.recruiter.data.api.MoneyRequestIn
import com.qwikserve.recruiter.data.api.PersonOut
import com.qwikserve.recruiter.data.api.RiderPatchBody
import com.qwikserve.recruiter.data.api.TimelineEvent
import com.qwikserve.recruiter.data.db.RiderEntity
import com.qwikserve.recruiter.data.repo.AppRepository
import com.qwikserve.recruiter.data.repo.PhotoRepository
import com.qwikserve.recruiter.data.repo.RiderRepository
import com.qwikserve.recruiter.ui.common.BarButton
import com.qwikserve.recruiter.ui.common.GhostAction
import com.qwikserve.recruiter.ui.evs.CloseoutSheet
import com.qwikserve.recruiter.ui.evs.EvActionsViewModel
import com.qwikserve.recruiter.ui.evs.GiveEvSheet
import com.qwikserve.recruiter.ui.common.Hairline
import com.qwikserve.recruiter.ui.common.Kicker
import com.qwikserve.recruiter.ui.common.PhotoTile
import com.qwikserve.recruiter.ui.common.Rule
import com.qwikserve.recruiter.ui.common.Segmented
import com.qwikserve.recruiter.ui.common.Skeleton
import com.qwikserve.recruiter.ui.common.Tag
import com.qwikserve.recruiter.ui.common.rupees
import com.qwikserve.recruiter.ui.common.shortDate
import com.qwikserve.recruiter.ui.common.shortStamp
import com.qwikserve.recruiter.ui.login.Field
import com.qwikserve.recruiter.ui.login.fieldColors
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
import kotlinx.serialization.json.Json
import retrofit2.HttpException
import java.io.IOException
import javax.inject.Inject
@HiltViewModel
class PersonViewModel @Inject constructor(
    saved: SavedStateHandle,
    private val repo: RiderRepository,
    private val photos: PhotoRepository,
    private val api: PayoutApi,
    private val json: Json,
    private val app: AppRepository,
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

    /* ── editing one rider id ───────────────────────────────────────────── */

    /** Which (rider_id, company) the edit sheet is open on, or null. */
    var editing by mutableStateOf<Pair<String, String>?>(null)
        private set
    var savingRider by mutableStateOf(false)
        private set
    var riderError by mutableStateOf<String?>(null)
        private set

    fun edit(riderId: String, company: String) {
        editing = riderId to company
        riderError = null
    }

    fun closeEdit() {
        editing = null
        riderError = null
    }

    /** Store suggestions for the sheet, from the same list onboarding uses. */
    fun hubChoices(company: String): List<String> = app.hubsFor(company)

    /* ── asking the office to move money ────────────────────────────────── */

    var askingMoney by mutableStateOf(false)
        private set
    var moneyBusy by mutableStateOf(false)
        private set
    var moneyError by mutableStateOf<String?>(null)
        private set
    /** Set once a request is filed, so the page can say so without a reload. */
    var moneyNote by mutableStateOf<String?>(null)
        private set

    fun askMoney() {
        askingMoney = true
        moneyError = null
    }

    fun closeMoney() {
        askingMoney = false
        moneyError = null
    }

    /**
     * File a money request against this rider. It does NOT move money — it
     * sits open until an admin approves it, and that is the whole design: a
     * recruiter knows things the office does not ("he paid ₹500 cash for the
     * helmet") but may not post to the ledger themselves.
     */
    fun sendMoneyRequest(direction: String, rupees: Double, reason: String) {
        if (moneyBusy) return
        val id = _personId.value
        moneyBusy = true
        moneyError = null
        viewModelScope.launch {
            try {
                api.createRequest(MoneyRequestIn(id, direction, rupees, reason.trim()))
                askingMoney = false
                moneyNote = "Request sent to the office. It shows here once they decide."
                loadTimeline()
            } catch (e: IOException) {
                moneyError = "No signal — the request was not sent."
            } catch (e: HttpException) {
                moneyError = runCatching {
                    json.decodeFromString(
                        ApiError.serializer(),
                        e.response()?.errorBody()?.string().orEmpty(),
                    ).detail
                }.getOrNull() ?: "The server answered ${e.code()}."
            } catch (e: Exception) {
                moneyError = e.message ?: "Could not send the request"
            } finally {
                moneyBusy = false
            }
        }
    }

    /**
     * Save one rider id. Only the fields that changed are sent, so a recruiter
     * correcting an account number cannot blank the phone by opening the sheet.
     *
     * The 409 the server answers when the account number already belongs to
     * somebody else is shown as-is: it names the other rider, which is the
     * whole point of it, and is far more useful than "could not save".
     */
    fun saveRider(riderId: String, company: String, body: RiderPatchBody, onDone: () -> Unit) {
        if (savingRider) return
        savingRider = true
        riderError = null
        viewModelScope.launch {
            try {
                repo.update(riderId, company, body)
                load()
                onDone()
            } catch (e: IOException) {
                riderError = "No signal — this one needs the server."
            } catch (e: HttpException) {
                // The server's own sentence. The 409 on a duplicate account
                // number names the other rider, which is the entire value of
                // it and far more use than "could not save".
                riderError = runCatching {
                    json.decodeFromString(
                        ApiError.serializer(),
                        e.response()?.errorBody()?.string().orEmpty(),
                    ).detail
                }.getOrNull() ?: "The server answered ${e.code()}."
            } catch (e: Exception) {
                riderError = e.message ?: "Could not save"
            } finally {
                savingRider = false
            }
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
    /** Opens the onboarding form attached to this person, to give them a
     *  rider id at a second company. Null where there is nowhere to navigate
     *  to, and then the action is simply not offered. */
    onAddCompany: ((Long, String) -> Unit)? = null,
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
                val rows = p?.riders?.map { RiderLine(it.riderId, it.company, it.hub, it.mobNo, it.accountNo, it.ifsc, it.isActive, it.recruitedBy, it.accountName) }
                    // The cache carries the holder name too since it became a column
                    // on RiderEntity, so the offline row says the same as the live one.
                    ?: cached.map { RiderLine(it.riderId, it.company, it.hub, it.mobNo, it.accountNo, it.ifsc, it.isActive, it.recruitedBy, it.accountName) }
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
                        // Only worth a line when it is somebody else's account —
                        // a null here means the rider's own name, which the
                        // heading already says.
                        r.holder?.takeIf { it.isNotBlank() }?.let {
                            Text("In the name of $it", style = MaterialTheme.typography.bodySmall, color = Qwik.Accent700)
                        }
                        r.recruitedBy?.let {
                            Text("Onboarded by " + it.substringBefore('@'), style = MaterialTheme.typography.bodySmall, color = Qwik.N600)
                        }
                        Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                            GhostAction("Edit details", onClick = { vm.edit(r.riderId, r.company) })
                        }
                    }
                }
                Hairline()
                // The backend has always accepted this (POST /riders with a
                // person_id); until now nothing in the app asked for it, so
                // the only route to a second company was an admin merge.
                if (onAddCompany != null) {
                    Row(Modifier.padding(horizontal = 20.dp, vertical = 8.dp)) {
                        GhostAction(
                            "Add an id at another company",
                            // `name` (above) already prefers the person's
                            // display name and falls back to the cache, so
                            // this works offline on a page opened from the list.
                            onClick = { name?.let { onAddCompany(personId, it) } },
                        )
                    }
                    Hairline()
                }

                val phone = rows.firstNotNullOfOrNull { it.phone }
                Row(Modifier.padding(horizontal = 20.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                    if (phone != null) {
                        GhostAction("Call $phone", onClick = {
                            ctx.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:" + phone.filter { it.isDigit() || it == '+' })))
                        })
                    }
                    // The only thing a recruiter may do about money: ask.
                    GhostAction("Ask the office for money", onClick = vm::askMoney)
                }
                vm.moneyNote?.let {
                    Text(
                        it,
                        style = MaterialTheme.typography.bodySmall,
                        color = Qwik.N700,
                        modifier = Modifier.padding(horizontal = 20.dp, vertical = 2.dp),
                    )
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

    // Editing one rider id. `rows` is the same list the section above draws,
    // so the sheet opens on what is on screen rather than re-fetching.
    vm.editing?.let { (rid, co) ->
        val line = (
            vm.person?.riders?.firstOrNull { it.riderId == rid && it.company == co }?.let {
                RiderLine(it.riderId, it.company, it.hub, it.mobNo, it.accountNo, it.ifsc, it.isActive, it.recruitedBy, it.accountName)
            } ?: cached.firstOrNull { it.riderId == rid && it.company == co }?.let {
                RiderLine(it.riderId, it.company, it.hub, it.mobNo, it.accountNo, it.ifsc, it.isActive, it.recruitedBy, it.accountName)
            }
            )
        if (line == null) vm.closeEdit() else EditRiderSheet(
            line = line,
            riderName = name,
            hubs = vm.hubChoices(line.company),
            saving = vm.savingRider,
            error = vm.riderError,
            onSave = { body -> vm.saveRider(rid, co, body) { vm.closeEdit() } },
            onDismiss = vm::closeEdit,
        )
    }

    if (vm.askingMoney) {
        AskMoneySheet(
            riderName = name,
            busy = vm.moneyBusy,
            error = vm.moneyError,
            onSend = vm::sendMoneyRequest,
            onDismiss = vm::closeMoney,
        )
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

/**
 * Edit one rider id: the store, the phone and the bank account.
 *
 * The server has always accepted these from a recruiter — `PATCH /riders/{id}`
 * takes `require_recruiter` and only fences off salary and re-crediting — but
 * nothing in the app ever asked for them, so a wrong account number meant a
 * message to the office and a wait. This is that form.
 *
 * Only what changed is sent. Opening the sheet and saving without touching a
 * field writes nothing, which matters because a half-filled form must not be
 * able to blank a phone number somebody else entered.
 *
 * Two fields need a word:
 *
 *  * **Account holder** is left empty when the account is in the rider's own
 *    name, and the placeholder says so. Clearing a name that was entered by
 *    mistake sends "" rather than null, which is how the server tells "leave
 *    it alone" from "put it back to the rider's own name".
 *  * **On the roster** is the switch the inactive rule reads. Turning it off
 *    says "they left this company", and their absence from that company's
 *    payout stops counting against them — see domain/worked.py. It is not a
 *    delete: the ledger and the id both stay.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun EditRiderSheet(
    line: RiderLine,
    riderName: String?,
    hubs: List<String>,
    saving: Boolean,
    error: String?,
    onSave: (RiderPatchBody) -> Unit,
    onDismiss: () -> Unit,
) {
    val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var hub by remember(line) { mutableStateOf(line.hub.orEmpty()) }
    var phone by remember(line) { mutableStateOf(line.phone.orEmpty()) }
    var account by remember(line) { mutableStateOf(line.account.orEmpty()) }
    var ifsc by remember(line) { mutableStateOf(line.ifsc.orEmpty()) }
    var holder by remember(line) { mutableStateOf(line.holder.orEmpty()) }
    var active by remember(line) { mutableStateOf(line.active) }

    // Null means "not sent". Trimmed on both sides so re-saving the same value
    // with a stray space is still a no-change.
    fun changed(now: String, before: String?): String? =
        now.trim().takeIf { it != (before ?: "").trim() }

    val body = RiderPatchBody(
        hub = changed(hub, line.hub),
        mobNo = changed(phone, line.phone),
        accountNo = changed(account, line.account),
        ifsc = changed(ifsc.uppercase(), line.ifsc),
        accountName = changed(holder, line.holder),
        isActive = active.takeIf { it != line.active },
    )
    val dirty = listOf(body.hub, body.mobNo, body.accountNo, body.ifsc, body.accountName)
        .any { it != null } || body.isActive != null

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheet, containerColor = Qwik.Bg) {
        Column(
            Modifier.fillMaxWidth().imePadding().verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp).padding(bottom = 24.dp),
        ) {
            Text("Edit rider id", style = MaterialTheme.typography.headlineLarge, color = Qwik.Ink)
            Spacer(Modifier.height(6.dp))
            Kicker(line.riderId + " · " + line.company)
            Spacer(Modifier.height(14.dp))

            Field("Store") {
                Input(hub, { hub = it }, placeholder = "Salt Lake", cap = KeyboardCapitalization.Words)
            }
            val suggestions = hubs.filter {
                hub.isNotBlank() && it.contains(hub, ignoreCase = true) && !it.equals(hub, ignoreCase = true)
            }.take(4)
            if (suggestions.isNotEmpty()) {
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    suggestions.forEach { h ->
                        Text(
                            h,
                            style = MaterialTheme.typography.bodySmall,
                            color = Qwik.Accent700,
                            modifier = Modifier.clickable { hub = h }.padding(4.dp),
                        )
                    }
                }
            }
            Field("Phone") {
                Input(phone, { phone = it.filter { c -> c.isDigit() } }, placeholder = "9800011122", keyboard = KeyboardType.Phone)
            }

            Spacer(Modifier.height(4.dp))
            Kicker("Bank account")
            Spacer(Modifier.height(2.dp))
            Text(
                "Where this company's payout goes. Get it wrong and the payment bounces, " +
                    "so check the digits against the passbook rather than a photo of it.",
                style = MaterialTheme.typography.bodySmall,
                color = Qwik.N700,
            )
            Field("Account number") {
                Input(account, { account = it.filter { c -> c.isDigit() } }, placeholder = "0123456789", keyboard = KeyboardType.Number)
            }
            Field("IFSC") {
                Input(ifsc, { ifsc = it.uppercase() }, placeholder = "SBIN0001234", cap = KeyboardCapitalization.Characters)
            }
            Field("Account holder") {
                Input(holder, { holder = it }, placeholder = riderName ?: "The rider's own name", cap = KeyboardCapitalization.Words)
            }
            Text(
                if (holder.isBlank()) {
                    "Empty means the account is in the rider's own name."
                } else {
                    "The payout will name $holder, not the rider."
                },
                style = MaterialTheme.typography.bodySmall,
                color = if (holder.isBlank()) Qwik.N600 else Qwik.Accent700,
            )

            Spacer(Modifier.height(16.dp))
            Hairline()
            Row(
                Modifier.fillMaxWidth().padding(vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text("On the roster", style = MaterialTheme.typography.titleMedium, color = Qwik.Ink)
                    Text(
                        if (active) {
                            "They still work ${line.company}."
                        } else {
                            "They have left ${line.company}. This id stops counting against them."
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = Qwik.N700,
                    )
                }
                Switch(checked = active, onCheckedChange = { active = it })
            }
            Hairline()

            if (error != null) {
                Spacer(Modifier.height(8.dp))
                Text(error, color = Qwik.Accent700, style = MaterialTheme.typography.bodySmall)
            }
            Spacer(Modifier.height(16.dp))
            BarButton(
                if (saving) "Saving…" else "Save",
                onClick = { onSave(body) },
                enabled = !saving && dirty,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                GhostAction("Cancel", onClick = onDismiss, color = Qwik.N700, enabled = !saving)
            }
        }
    }
}

/**
 * Ask the office to credit or debit this rider.
 *
 * This does not move money, and the wording says so twice — once as the
 * heading's note and once on the button — because a recruiter who believes
 * they have just paid somebody will not chase it, and the rider will be back
 * tomorrow asking where it is.
 *
 * Direction is a two-way switch rather than a signed amount. "He owes us 500"
 * and "we owe him 500" are the two things anybody actually means, and a minus
 * sign typed into a number field is the easiest mistake in the app to make.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AskMoneySheet(
    riderName: String?,
    busy: Boolean,
    error: String?,
    onSend: (String, Double, String) -> Unit,
    onDismiss: () -> Unit,
) {
    val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var credit by remember { mutableStateOf(true) }
    var amount by remember { mutableStateOf("") }
    var reason by remember { mutableStateOf("") }
    // Not named `rupees`: that is the formatter imported from ui.common, and
    // shadowing it here would make rupees(...) below a call on a Double.
    val amountRs = amount.toDoubleOrNull() ?: 0.0
    // The server's own floor: 3 characters, because "ok" explains nothing to
    // the admin who has to decide.
    val ready = amountRs > 0 && reason.trim().length >= 3

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheet, containerColor = Qwik.Bg) {
        Column(
            Modifier.fillMaxWidth().imePadding().verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp).padding(bottom = 24.dp),
        ) {
            Text("Ask the office", style = MaterialTheme.typography.headlineLarge, color = Qwik.Ink)
            Spacer(Modifier.height(6.dp))
            Kicker(riderName ?: "This rider")
            Spacer(Modifier.height(10.dp))
            Text(
                "This does not move any money. It goes to the office as a request, " +
                    "and an admin decides — so tell the rider it is pending, not done.",
                style = MaterialTheme.typography.bodyMedium,
                color = Qwik.N700,
            )
            Spacer(Modifier.height(14.dp))
            Segmented(
                listOf("We owe him", "He owes us"),
                selected = if (credit) 0 else 1,
                onSelect = { credit = it == 0 },
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(4.dp))
            Text(
                if (credit) {
                    "A credit: his balance goes up by this much."
                } else {
                    "A debit: it comes off his next payout."
                },
                style = MaterialTheme.typography.bodySmall,
                color = Qwik.N600,
            )
            Spacer(Modifier.height(12.dp))
            Field("Amount (₹)") {
                Input(
                    amount,
                    { amount = it.filter { c -> c.isDigit() || c == '.' } },
                    placeholder = "500",
                    keyboard = KeyboardType.Decimal,
                )
            }
            Field("Why") {
                Input(
                    reason,
                    { reason = it },
                    placeholder = "Paid ₹500 cash for the helmet",
                    cap = KeyboardCapitalization.Sentences,
                )
            }
            Text(
                "The admin sees only this sentence, so write what you would say on " +
                    "the phone.",
                style = MaterialTheme.typography.bodySmall,
                color = Qwik.N600,
            )

            if (error != null) {
                Spacer(Modifier.height(10.dp))
                Text(error, color = Qwik.Accent700, style = MaterialTheme.typography.bodySmall)
            }
            Spacer(Modifier.height(16.dp))
            BarButton(
                when {
                    busy -> "Sending…"
                    amountRs > 0 -> "Send request for " + rupees(amountRs)
                    else -> "Send request"
                },
                onClick = { onSend(if (credit) "credit" else "debit", amountRs, reason) },
                enabled = !busy && ready,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                GhostAction("Cancel", onClick = onDismiss, color = Qwik.N700, enabled = !busy)
            }
        }
    }
}

private data class RiderLine(
    val riderId: String, val company: String, val hub: String?, val phone: String?,
    val account: String?, val ifsc: String?, val active: Boolean, val recruitedBy: String?,
    /** Whose name the account is in, only when it is not the rider's own. */
    val holder: String? = null,
)

/**
 * A form field in the app's style.
 *
 * The third copy of this in the app — ProfileScreen and NewRiderScreen have
 * their own private ones. It is twelve lines and it belongs in ui.common with
 * `Field` and `fieldColors`, which live in ui.login for the same historical
 * reason. Deliberately not moved here: that is a refactor across four files
 * and this change is a fix somebody is waiting on.
 */
@Composable
private fun Input(
    value: String,
    onChange: (String) -> Unit,
    placeholder: String,
    keyboard: KeyboardType = KeyboardType.Text,
    cap: KeyboardCapitalization = KeyboardCapitalization.None,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        placeholder = { Text(placeholder, color = Qwik.N600, maxLines = 1) },
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = keyboard, capitalization = cap),
        colors = fieldColors(),
        modifier = Modifier.fillMaxWidth(),
    )
}
