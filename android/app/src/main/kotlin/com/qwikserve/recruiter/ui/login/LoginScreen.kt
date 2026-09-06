package com.qwikserve.recruiter.ui.login

import android.os.Build
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
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

    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        Column(
            Modifier.fillMaxSize().systemBarsPadding().imePadding().padding(horizontal = 28.dp),
            verticalArrangement = Arrangement.Center,
        ) {
            Text("Qwikserve", style = MaterialTheme.typography.headlineMedium, color = MaterialTheme.colorScheme.primary)
            Text(
                "Recruiter",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(28.dp))
            if (reason != null) {
                Text(reason, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
                Spacer(Modifier.height(12.dp))
            }
            OutlinedTextField(
                value = user,
                onValueChange = { user = it },
                label = { Text("Email or phone") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Next),
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(12.dp))
            OutlinedTextField(
                value = password,
                onValueChange = { password = it },
                label = { Text("Password") },
                singleLine = true,
                visualTransformation = if (show) VisualTransformation.None else PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { vm.signIn(user, password, onSignedIn) }),
                trailingIcon = {
                    IconButton(onClick = { show = !show }) {
                        Icon(
                            if (show) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                            contentDescription = if (show) "Hide password" else "Show password",
                        )
                    }
                },
                modifier = Modifier.fillMaxWidth(),
            )
            if (vm.error != null) {
                Spacer(Modifier.height(10.dp))
                Text(vm.error!!, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
            }
            Spacer(Modifier.height(20.dp))
            Button(
                onClick = { vm.signIn(user, password, onSignedIn) },
                enabled = !vm.busy,
                modifier = Modifier.fillMaxWidth().height(50.dp),
            ) {
                if (vm.busy) CircularProgressIndicator(Modifier.height(20.dp), strokeWidth = 2.dp)
                else Text("Sign in")
            }
            Spacer(Modifier.height(16.dp))
            Text(
                "Forgot your password? Use Forgot password on the web console, or ask an admin to set one.",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.align(Alignment.CenterHorizontally),
            )
        }
    }
}
