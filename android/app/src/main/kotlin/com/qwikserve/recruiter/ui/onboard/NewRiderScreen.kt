package com.qwikserve.recruiter.ui.onboard

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.qwikserve.recruiter.data.api.ApiError
import com.qwikserve.recruiter.data.api.RiderIn
import com.qwikserve.recruiter.data.db.RiderEntity
import com.qwikserve.recruiter.data.repo.AppRepository
import com.qwikserve.recruiter.data.repo.RiderRepository
import com.qwikserve.recruiter.ui.common.Avatar
import com.qwikserve.recruiter.ui.common.BarButton
import com.qwikserve.recruiter.ui.common.formWidth
import com.qwikserve.recruiter.ui.common.Chips
import com.qwikserve.recruiter.ui.common.GhostAction
import com.qwikserve.recruiter.ui.common.Hairline
import com.qwikserve.recruiter.ui.common.Kicker
import com.qwikserve.recruiter.ui.common.Rule
import com.qwikserve.recruiter.ui.common.Tag
import com.qwikserve.recruiter.ui.login.Field
import com.qwikserve.recruiter.ui.login.fieldColors
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
import javax.inject.Inject

/**
 * Onboard a rider. Company, name and the company's rider id are the must-
 * haves; hub, phone, Aadhaar / PAN, bank and a referrer are optional and
 * all editable later. The referrer is any rider already in the roster —
 * the referral bonus (₹1,000 in two instalments) is the server's business.
 */
@OptIn(ExperimentalCoroutinesApi::class, FlowPreview::class)
@HiltViewModel
class NewRiderViewModel @Inject constructor(
    private val riders: RiderRepository,
    private val app: AppRepository,
    private val json: Json,
) : ViewModel() {
    var company by mutableStateOf("")
    var name by mutableStateOf("")
    var riderId by mutableStateOf("")
    var hub by mutableStateOf("")
    var phone by mutableStateOf("")
    var aadhaar by mutableStateOf("")
    var pan by mutableStateOf("")
    var account by mutableStateOf("")
    var ifsc by mutableStateOf("")
    var referrer by mutableStateOf<RiderEntity?>(null)
    var allowDuplicate by mutableStateOf(false)
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var fieldErrors by mutableStateOf<Map<String, String>>(emptyMap())
        private set
    /** The server refused because a rider with this name exists at the company. */
    var duplicateName by mutableStateOf(false)
        private set

    val companies get() = app.bootstrap.value?.companies?.map { it.companyName }.orEmpty()
    /** Stores of the chosen company (Admin → Hubs), falling back to every hub known. */
    val hubs: List<String>
        get() {
            val b = app.bootstrap.value ?: return emptyList()
            val own = b.companyHubs.filter { it.company == company }.map { it.hub }
            return own.ifEmpty { b.hubs }
        }

    /** Referrer picker: the cached roster filtered as you type. */
    val referrerQuery = MutableStateFlow("")
    val referrerHits = referrerQuery.debounce(80)
        .flatMapLatest { q -> if (q.isBlank()) flowOf(emptyList()) else riders.search(q).map { it.take(8) } }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    private fun validate(): Boolean {
        val e = mutableMapOf<String, String>()
        if (company.isBlank()) e["company"] = "Pick the company."
        if (name.trim().length < 3) e["name"] = "The rider's full name."
        val digits = phone.filter { it.isDigit() }
        if (phone.isNotBlank() && digits.length != 10) e["phone"] = "Ten digits, no country code."
        val a = aadhaar.filter { it.isDigit() }
        if (aadhaar.isNotBlank() && a.length != 12) e["aadhaar"] = "Twelve digits."
        val p = pan.trim().uppercase()
        if (p.isNotBlank() && !Regex("^[A-Z]{5}\\d{4}[A-Z]$").matches(p)) e["pan"] = "Five letters, four digits, one letter."
        val acct = account.filter { it.isDigit() }
        val code = ifsc.trim().uppercase()
        if ((acct.isNotBlank() || code.isNotBlank()) && !Regex("^\\d{6,18}$").matches(acct)) e["account"] = "Digits only, 6 to 18 of them."
        if ((acct.isNotBlank() || code.isNotBlank()) && code.length != 11) e["ifsc"] = "IFSC is exactly 11 characters."
        fieldErrors = e
        return e.isEmpty()
    }

    fun save(onDone: (Long, String) -> Unit) {
        if (busy || !validate()) return
        busy = true; error = null
        viewModelScope.launch {
            try {
                val out = riders.create(
                    RiderIn(
                        company = company,
                        name = name.trim(),
                        riderId = riderId.trim().ifBlank { null },
                        hub = hub.trim().ifBlank { null },
                        mobNo = phone.filter { it.isDigit() }.ifBlank { null },
                        accountNo = account.filter { it.isDigit() }.ifBlank { null },
                        ifsc = ifsc.trim().uppercase().ifBlank { null },
                        aadhaarNo = aadhaar.filter { it.isDigit() }.ifBlank { null },
                        panNo = pan.trim().uppercase().ifBlank { null },
                        allowDuplicateName = allowDuplicate,
                        referredByPersonId = referrer?.personId,
                    ),
                )
                val note = buildString {
                    append(out.name ?: name.trim()); append(" added")
                    if (out.riderId.startsWith("QSPEND")) append(" with a placeholder id")
                    out.referredBy?.let { append(" · referred by $it") }
                }
                onDone(out.personId, note)
            } catch (e: HttpException) {
                val detail = runCatching {
                    json.decodeFromString(ApiError.serializer(), e.response()?.errorBody()?.string().orEmpty()).detail
                }.getOrNull()
                error = when (e.code()) {
                    409 -> detail ?: "Someone with this name already rides for this company."
                    else -> detail ?: "The server answered ${e.code()}."
                }
                duplicateName = e.code() == 409 && (detail ?: "").contains("add anyway", ignoreCase = true)
            } catch (e: IOException) {
                error = "No signal — onboarding needs the server. Try again when you're online."
            } catch (e: Exception) {
                error = e.message ?: "Could not add the rider"
            } finally {
                busy = false
            }
        }
    }
}

@Composable
fun NewRiderScreen(onBack: () -> Unit, onSaved: (Long, String) -> Unit, vm: NewRiderViewModel = hiltViewModel()) {
    val hits by vm.referrerHits.collectAsStateWithLifecycle()
    val rq by vm.referrerQuery.collectAsStateWithLifecycle()
    val err = vm.fieldErrors
    val companies = vm.companies
    LaunchedEffect(companies.size) { if (vm.company.isBlank()) vm.company = companies.firstOrNull() ?: "" }

    // The form keeps a readable width in the middle of a tablet; on a phone
    // formWidth() is the whole screen, so nothing changes there.
    Surface(Modifier.fillMaxSize(), color = Qwik.Bg) {
        Column(
            Modifier.fillMaxSize().statusBarsPadding().imePadding(),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Row(Modifier.formWidth().padding(start = 20.dp, end = 12.dp, top = 14.dp, bottom = 12.dp), verticalAlignment = Alignment.Bottom) {
                Text("New rider", style = MaterialTheme.typography.headlineLarge, color = Qwik.Ink, modifier = Modifier.weight(1f))
                GhostAction("Cancel", onClick = onBack)
            }
            Rule()
            Column(Modifier.formWidth().weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(top = 16.dp, bottom = 24.dp)) {
                Kicker("Company")
                Spacer(Modifier.height(8.dp))
                Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) { Chips(companies, vm.company, onSelect = { vm.company = it }) }
                ErrorLine(err["company"])
                Spacer(Modifier.height(14.dp))

                Field("Full name") { Input(vm.name, { vm.name = it }, placeholder = "Srijit Purkait", cap = KeyboardCapitalization.Words) }
                ErrorLine(err["name"])
                Field("Rider id (the company's)") { Input(vm.riderId, { vm.riderId = it }, placeholder = "FE5943521 — blank for a placeholder", cap = KeyboardCapitalization.Characters) }
                ErrorLine(null)
                Field("Hub / store") {
                    Input(vm.hub, { vm.hub = it }, placeholder = "Salt Lake", cap = KeyboardCapitalization.Words)
                    val sug = vm.hubs.filter { vm.hub.isNotBlank() && it.contains(vm.hub, ignoreCase = true) && !it.equals(vm.hub, ignoreCase = true) }.take(4)
                    if (sug.isNotEmpty()) {
                        Spacer(Modifier.height(6.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) { sug.forEach { h -> Text(h, style = MaterialTheme.typography.bodySmall, color = Qwik.Accent700, modifier = Modifier.clickable { vm.hub = h }.padding(4.dp)) } }
                    }
                }
                ErrorLine(null)
                Field("Phone") { Input(vm.phone, { vm.phone = it }, placeholder = "98765 43210", keyboard = KeyboardType.Phone) }
                ErrorLine(err["phone"])

                Spacer(Modifier.height(6.dp))
                Kicker("Identity")
                Spacer(Modifier.height(8.dp))
                Field("Aadhaar") { Input(vm.aadhaar, { vm.aadhaar = it }, placeholder = "2345 6789 0123", keyboard = KeyboardType.Number) }
                ErrorLine(err["aadhaar"])
                Field("PAN") { Input(vm.pan, { vm.pan = it }, placeholder = "ABCDE1234F", cap = KeyboardCapitalization.Characters) }
                ErrorLine(err["pan"])

                Spacer(Modifier.height(6.dp))
                Kicker("Bank account")
                Spacer(Modifier.height(8.dp))
                Field("Account number") { Input(vm.account, { vm.account = it }, placeholder = "5550001234", keyboard = KeyboardType.Number) }
                ErrorLine(err["account"])
                Field("IFSC") { Input(vm.ifsc, { vm.ifsc = it }, placeholder = "HDFC0000123", cap = KeyboardCapitalization.Characters) }
                ErrorLine(err["ifsc"])
                Text("Payouts stay blocked until an account is on file; it can be added later.", style = MaterialTheme.typography.bodySmall, color = Qwik.N700)

                Spacer(Modifier.height(20.dp))
                Kicker("Referred by")
                Spacer(Modifier.height(4.dp))
                Text(
                    "An existing rider who brought this one in. Once the new rider has worked four weeks the referrer gets ₹1,000 — two ₹500 instalments with their payouts.",
                    style = MaterialTheme.typography.bodySmall, color = Qwik.N700,
                )
                Spacer(Modifier.height(8.dp))
                val ref = vm.referrer
                if (ref != null) {
                    Row(Modifier.fillMaxWidth().background(Qwik.Surface).padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Avatar(ref.personId, ref.name, size = 36.dp)
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(ref.name ?: ref.riderId, style = MaterialTheme.typography.titleMedium, color = Qwik.Ink)
                            Text(listOfNotNull(ref.riderId, ref.hub).joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = Qwik.N700)
                        }
                        Tag(ref.company, outline = true)
                        Spacer(Modifier.width(8.dp))
                        GhostAction("Remove", onClick = { vm.referrer = null })
                    }
                } else {
                    Input(rq, { vm.referrerQuery.value = it }, placeholder = "Search the roster by name, id or phone")
                    hits.forEach { r ->
                        Row(
                            Modifier.fillMaxWidth().clickable { vm.referrer = r; vm.referrerQuery.value = "" }.padding(vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Avatar(r.personId, r.name, size = 32.dp)
                            Spacer(Modifier.width(10.dp))
                            Column(Modifier.weight(1f)) {
                                Text(r.name ?: r.riderId, style = MaterialTheme.typography.bodyLarge, color = Qwik.Ink)
                                Text(listOfNotNull(r.riderId, r.hub).joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = Qwik.N700)
                            }
                            Tag(r.company, outline = true)
                        }
                        Hairline()
                    }
                }

                if (vm.error != null) {
                    Spacer(Modifier.height(16.dp))
                    Text(vm.error!!, style = MaterialTheme.typography.bodyMedium, color = Qwik.Accent700)
                    if (vm.duplicateName) {
                        Spacer(Modifier.height(6.dp))
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("Same name, different person?", style = MaterialTheme.typography.bodySmall, color = Qwik.N700)
                            Spacer(Modifier.width(8.dp))
                            GhostAction("Add anyway", onClick = { vm.allowDuplicate = true; vm.save(onSaved) })
                        }
                    }
                }
            }
            Rule()
            BarButton(if (vm.busy) "Adding…" else "Add rider", onClick = { vm.save(onSaved) }, enabled = !vm.busy, modifier = Modifier.formWidth())
        }
    }
}

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

@Composable
private fun ErrorLine(text: String?) {
    Text(text ?: "", style = MaterialTheme.typography.bodySmall, color = Qwik.Accent700, modifier = Modifier.padding(top = 4.dp, bottom = 8.dp))
}
