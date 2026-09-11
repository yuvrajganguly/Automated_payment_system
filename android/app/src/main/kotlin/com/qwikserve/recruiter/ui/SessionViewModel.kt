package com.qwikserve.recruiter.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import com.qwikserve.recruiter.data.api.LogoutIn
import com.qwikserve.recruiter.data.api.PayoutApi
import com.qwikserve.recruiter.data.auth.LocalCaches
import com.qwikserve.recruiter.data.auth.Session
import com.qwikserve.recruiter.data.auth.TokenAuthenticator
import com.qwikserve.recruiter.data.auth.TokenStore
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class SessionViewModel @Inject constructor(
    private val store: TokenStore,
    private val api: PayoutApi,
    private val authenticator: TokenAuthenticator,
    private val caches: LocalCaches,
) : ViewModel() {
    val session: StateFlow<Session?> = store.session

    /** Why the user landed on sign-in (server's words), if the session was cut. */
    var signedOutReason by mutableStateOf<String?>(null)
        private set

    init {
        // If a refresh failed before this screen existed, surface its reason once.
        authenticator.lastFailureReason?.let { signedOutReason = it }
    }

    fun clearReason() { signedOutReason = null }

    fun signOut() {
        val refresh = store.refreshToken
        store.clear()
        caches.wipe()
        viewModelScope.launch { runCatching { api.logout(LogoutIn(refresh)) } }
    }
}
