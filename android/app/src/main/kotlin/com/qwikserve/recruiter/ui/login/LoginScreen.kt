package com.qwikserve.recruiter.ui.login

import android.os.Build
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
import androidx.compose.ui.unit.sp
import com.qwikserve.recruiter.ui.common.BarButton
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
import androidx.compose.ui.Alignment
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
import com.qwikserve.recruiter.data.api.PayoutApi
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
                val detail = runCatching {
                    json.decodeFromString(ApiError.serializer(), e.response()?.errorBody()?.string().orEmpty()).detail
                }.getOrNull()
                error = when (e.code()) {
                    401 -> detail ?: "Wrong email/phone or password."
                    429 -> "Too many attempts — wait a few minutes and try again."
                    else -> detail ?: "The server answered ${e.code()}."
                }
            } catch (e: IOException) {
                error = "Can't reach the server. Check your connection."
            } finally {
                busy = false
            }
        }
    }
}

@Composable
fun LoginScreen(reason: String?, onSignedIn: () -> Unit, vm: LoginViewModel = hiltViewModel()) {
    var user by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var show by rememberSaveable { mutableStateOf(false) }

    Surface(Modifier.fillMaxSize(), color = Qwik.Bg) {
        Column(Modifier.fillMaxSize().systemBarsPadding().imePadding()) {
            // Masthead — the design's 46 px wordmark over a 2 px rule.
            Column(Modifier.padding(horizontal = 20.dp).padding(top = 84.dp, bottom = 22.dp)) {
                Text(
                    "Qwikserve",
                    style = MaterialTheme.typography.headlineLarge.copy(fontSize = 46.sp, lineHeight = 44.sp, letterSpacing = (-1.4).sp),
                    color = Qwik.Ink,
                )
                Spacer(Modifier.height(10.dp))
                Kicker("Recruiter", color = Qwik.Accent700)
            }
            Rule()
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(top = 30.dp)) {
                if (reason != null) {
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
                Text(
                    "You stay signed in on this phone. Ask an admin to reset a password.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = Qwik.N700,
                )
            }
            Rule()
            BarButton(if (vm.busy) "Signing in…" else "Sign in", onClick = { vm.signIn(user, password, onSignedIn) }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth())
        }
    }
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
