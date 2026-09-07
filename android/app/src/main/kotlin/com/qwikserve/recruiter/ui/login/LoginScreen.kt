package com.qwikserve.recruiter.ui.login

import android.os.Build
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.sp
import com.qwikserve.recruiter.R
import com.qwikserve.recruiter.ui.common.BarButton
import com.qwikserve.recruiter.ui.common.GhostAction
import com.qwikserve.recruiter.ui.common.Kicker
import com.qwikserve.recruiter.ui.common.Rule
import com.qwikserve.recruiter.ui.theme.Qwik
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import com.qwikserve.recruiter.data.api.ApiError
import com.qwikserve.recruiter.data.api.ForgotPasswordIn
import com.qwikserve.recruiter.data.api.PayoutApi
import com.qwikserve.recruiter.data.api.ResetPasswordIn
import com.qwikserve.recruiter.data.auth.TokenStore
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import retrofit2.HttpException
import java.io.IOException
import javax.inject.Inject

@HiltViewModel
class LoginViewModel @Inject constructor(
    private val api: PayoutApi,
    private val store: TokenStore,
    private val json: Json,
) : ViewModel() {
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    /** Reset flow: what the server last told us, shown under the code field. */
    var resetNote by mutableStateOf<String?>(null)
        private set
    var codeSent by mutableStateOf(false)
        private set

    fun signIn(user: String, password: String, onDone: () -> Unit) {
        if (busy) return
        val u = user.trim()
        if (u.isEmpty() || password.isEmpty()) { error = "Enter your email or phone and your password."; return }
        busy = true; error = null
        viewModelScope.launch {
            try {
                val device = "android ${Build.MANUFACTURER} ${Build.MODEL}".trim()
                val tok = api.login(u, password, device)
                store.save(tok.accessToken, tok.refreshToken, tok.email, tok.role)
                onDone()
            } catch (e: HttpException) {
                error = httpMessage(e, unauthorized = "Wrong email/phone or password.")
            } catch (e: IOException) {
                error = "Can't reach the server. Check your connection."
            } finally {
                busy = false
            }
        }
    }

    /** Email a 6-digit code. The identifier may be an email or a phone number;
     *  the code always lands in the account's inbox. */
    fun sendCode(ident: String) {
        if (busy) return
        val u = ident.trim()
        if (u.isEmpty()) { error = "Enter the email or phone your account uses."; return }
        busy = true; error = null; resetNote = null
        viewModelScope.launch {
            try {
                api.forgotPassword(ForgotPasswordIn(u))
                codeSent = true
                resetNote = "If that account exists, a 6-digit code is on its way. It expires in 10 minutes."
            } catch (e: HttpException) {
                error = httpMessage(e, unauthorized = "That didn't work.")
            } catch (e: IOException) {
                error = "Can't reach the server. Check your connection."
            } finally {
                busy = false
            }
        }
    }

    fun resetPassword(email: String, code: String, newPassword: String, onDone: () -> Unit) {
        if (busy) return
        if (email.isBlank() || code.isBlank()) { error = "Enter your account email and the code you were sent."; return }
        if (newPassword.length < 8) { error = "The new password must be at least 8 characters."; return }
        busy = true; error = null
        viewModelScope.launch {
            try {
                api.resetPassword(ResetPasswordIn(email.trim(), code.trim(), newPassword))
                codeSent = false; resetNote = null
                onDone()
            } catch (e: HttpException) {
                error = httpMessage(e, unauthorized = "Incorrect code.")
            } catch (e: IOException) {
                error = "Can't reach the server. Check your connection."
            } finally {
                busy = false
            }
        }
    }

    fun leaveReset() { error = null; resetNote = null; codeSent = false }

    private fun httpMessage(e: HttpException, unauthorized: String): String {
        val detail = runCatching {
            json.decodeFromString(ApiError.serializer(), e.response()?.errorBody()?.string().orEmpty()).detail
        }.getOrNull()
        return when (e.code()) {
            401 -> detail ?: unauthorized
            429 -> "Too many attempts — wait a few minutes and try again."
            503 -> detail ?: "That isn't set up on this server yet. Ask an admin."
            else -> detail ?: "The server answered ${e.code()}."
        }
    }
}

@Composable
fun LoginScreen(reason: String?, onSignedIn: () -> Unit, vm: LoginViewModel = hiltViewModel()) {
    var user by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var show by rememberSaveable { mutableStateOf(false) }
    var resetting by rememberSaveable { mutableStateOf(false) }
    var done by rememberSaveable { mutableStateOf<String?>(null) }

    Surface(Modifier.fillMaxSize(), color = Qwik.Bg) {
        Column(Modifier.fillMaxSize().systemBarsPadding().imePadding()) {
            // Masthead — the winged Q over the design's 46 px wordmark and a 2 px rule.
            Column(Modifier.padding(horizontal = 20.dp).padding(top = 56.dp, bottom = 22.dp)) {
                Image(
                    painter = painterResource(R.drawable.qwik_logo),
                    contentDescription = "Qwikserve",
                    modifier = Modifier.height(58.dp),
                )
                Spacer(Modifier.height(18.dp))
                Text(
                    "Qwikserve",
                    style = MaterialTheme.typography.headlineLarge.copy(fontSize = 46.sp, lineHeight = 44.sp, letterSpacing = (-1.4).sp),
                    color = Qwik.Ink,
                )
                Spacer(Modifier.height(10.dp))
                Kicker(if (resetting) "Reset password" else "Recruiter", color = Qwik.Accent700)
            }
            Rule()
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(top = 30.dp)) {
                if (resetting) {
                    ResetFields(
                        vm = vm,
                        ident = user,
                        onIdent = { user = it },
                        onDone = { done = "Password changed. Sign in with the new one."; resetting = false; password = "" },
                    )
                } else {
                    if (done != null) {
                        Text(done!!, color = Qwik.Ink, style = MaterialTheme.typography.bodyMedium)
                        Spacer(Modifier.height(14.dp))
                    } else if (reason != null) {
                        Text(reason, color = Qwik.Accent700, style = MaterialTheme.typography.bodyMedium)
                        Spacer(Modifier.height(14.dp))
                    }
                    Field("Email or phone") {
                        OutlinedTextField(
                            value = user,
                            onValueChange = { user = it },
                            placeholder = { Text("you@qwikserve.in", color = Qwik.N600) },
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Next),
                            colors = fieldColors(),
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                    Spacer(Modifier.height(16.dp))
                    Field("Password") {
                        OutlinedTextField(
                            value = password,
                            onValueChange = { password = it },
                            singleLine = true,
                            visualTransformation = if (show) VisualTransformation.None else PasswordVisualTransformation(),
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                            keyboardActions = KeyboardActions(onDone = { vm.signIn(user, password, onSignedIn) }),
                            trailingIcon = {
                                IconButton(onClick = { show = !show }) {
                                    Icon(
                                        if (show) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                                        contentDescription = if (show) "Hide password" else "Show password",
                                        tint = Qwik.N700,
                                    )
                                }
                            },
                            colors = fieldColors(),
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                    Text(
                        vm.error ?: "",
                        color = Qwik.Accent700,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(top = 5.dp).heightIn(min = 20.dp),
                    )
                    Spacer(Modifier.height(10.dp))
                    GhostAction("Forgot password?", onClick = { done = null; vm.leaveReset(); resetting = true })
                    Spacer(Modifier.height(10.dp))
                    Text(
                        "You stay signed in on this phone. Your account is created by an admin; the code for a forgotten password comes by email.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = Qwik.N700,
                    )
                }
            }
            Rule()
            if (resetting) {
                BarButton(
                    "Back to sign in",
                    onClick = { vm.leaveReset(); resetting = false },
                    primary = false,
                    enabled = !vm.busy,
                    modifier = Modifier.fillMaxWidth(),
                )
            } else {
                BarButton(
                    if (vm.busy) "Signing in…" else "Sign in",
                    onClick = { done = null; vm.signIn(user, password, onSignedIn) },
                    enabled = !vm.busy,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
    }
}

/** Step 1: ask for a code. Step 2: code + new password. The account email is
 *  asked for again because a phone number can receive the code but the reset
 *  itself is keyed to the address the mail went to. */
@Composable
private fun ResetFields(
    vm: LoginViewModel,
    ident: String,
    onIdent: (String) -> Unit,
    onDone: () -> Unit,
) {
    var email by rememberSaveable { mutableStateOf(if (ident.contains('@')) ident else "") }
    var code by rememberSaveable { mutableStateOf("") }
    var pass by rememberSaveable { mutableStateOf("") }

    Field("Email or phone on the account") {
        OutlinedTextField(
            value = ident,
            onValueChange = onIdent,
            placeholder = { Text("you@qwikserve.in", color = Qwik.N600) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Next),
            colors = fieldColors(),
            modifier = Modifier.fillMaxWidth(),
        )
    }
    Spacer(Modifier.height(12.dp))
    BarButton(
        if (vm.busy && !vm.codeSent) "Sending…" else if (vm.codeSent) "Send another code" else "Email me a code",
        onClick = {
            if (ident.contains('@')) email = ident.trim()
            vm.sendCode(ident)
        },
        enabled = !vm.busy,
        modifier = Modifier.fillMaxWidth(),
    )
    if (vm.resetNote != null) {
        Spacer(Modifier.height(10.dp))
        Text(vm.resetNote!!, style = MaterialTheme.typography.bodyMedium, color = Qwik.N700)
    }
    if (vm.codeSent) {
        Spacer(Modifier.height(20.dp))
        Field("Account email (where the code went)") {
            OutlinedTextField(
                value = email,
                onValueChange = { email = it },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Next),
                colors = fieldColors(),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        Spacer(Modifier.height(16.dp))
        Field("6-digit code") {
            OutlinedTextField(
                value = code,
                onValueChange = { code = it.filter { c -> c.isDigit() }.take(6) },
                placeholder = { Text("000000", color = Qwik.N600) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword, imeAction = ImeAction.Next),
                colors = fieldColors(),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        Spacer(Modifier.height(16.dp))
        Field("New password (at least 8 characters)") {
            OutlinedTextField(
                value = pass,
                onValueChange = { pass = it },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { vm.resetPassword(email, code, pass, onDone) }),
                colors = fieldColors(),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        Spacer(Modifier.height(16.dp))
        BarButton(
            if (vm.busy) "Saving…" else "Set new password",
            onClick = { vm.resetPassword(email, code, pass, onDone) },
            enabled = !vm.busy,
            modifier = Modifier.fillMaxWidth(),
        )
    }
    Text(
        vm.error ?: "",
        color = Qwik.Accent700,
        style = MaterialTheme.typography.bodySmall,
        modifier = Modifier.padding(top = 8.dp).heightIn(min = 20.dp),
    )
    Spacer(Modifier.height(8.dp))
    Text(
        "No email arriving? Ask an admin to set a password for you from the Users page.",
        style = MaterialTheme.typography.bodyMedium,
        color = Qwik.N700,
    )
}

@Composable
fun Field(label: String, content: @Composable () -> Unit) {
    Column {
        Text(label, style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp), color = Qwik.N700, modifier = Modifier.padding(bottom = 5.dp))
        content()
    }
}

@Composable
fun fieldColors() = OutlinedTextFieldDefaults.colors(
    focusedContainerColor = Qwik.Surface,
    unfocusedContainerColor = Qwik.Surface,
    focusedBorderColor = Qwik.Accent,
    unfocusedBorderColor = Qwik.Divider,
    cursorColor = Qwik.Accent,
    focusedTextColor = Qwik.Ink,
    unfocusedTextColor = Qwik.Ink,
)
