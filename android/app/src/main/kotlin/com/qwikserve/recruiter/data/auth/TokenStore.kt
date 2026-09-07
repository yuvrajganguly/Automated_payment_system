package com.qwikserve.recruiter.data.auth

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import javax.inject.Inject
import javax.inject.Singleton

data class Session(val email: String, val role: String)

/**
 * Where the tokens live: encrypted preferences backed by the Android
 * keystore. The refresh token is the long-lived credential (30 days from
 * issue, rotated on every use); the access token is a 12-hour convenience.
 */
@Singleton
class TokenStore @Inject constructor(@ApplicationContext context: Context) {
    /**
     * Encrypted preferences when the phone's keystore cooperates. Some ROMs
     * (and a restored backup) hand back a corrupt keyset or refuse the master
     * key outright, and this object is built during app start — so a keystore
     * that says no must not be the end of the app. We wipe the file and try
     * once more, then fall back to ordinary app-private preferences: a signed-in
     * session on a working phone beats a phone that cannot open the app.
     */
    private val prefs: SharedPreferences = encrypted(context)
        ?: run { wipe(context); encrypted(context) }
        ?: context.getSharedPreferences(PLAIN_FILE, Context.MODE_PRIVATE)

    private val _session = MutableStateFlow(readSession())
    val session: StateFlow<Session?> = _session

    /** The signed-in email (lower-case, as the server stores it), or null. */
    val email: String? get() = _session.value?.email?.lowercase()

    @Volatile var accessToken: String? = prefs.getString(KEY_ACCESS, null)
        private set
    @Volatile var refreshToken: String? = prefs.getString(KEY_REFRESH, null)
        private set

    fun save(access: String, refresh: String?, email: String, role: String) {
        accessToken = access
        if (refresh != null) refreshToken = refresh
        val editor = prefs.edit()
            .putString(KEY_ACCESS, access)
            .putString(KEY_EMAIL, email)
            .putString(KEY_ROLE, role)
        if (refresh != null) editor.putString(KEY_REFRESH, refresh)
        editor.apply()
        _session.value = Session(email, role)
    }

    fun clear() {
        accessToken = null
        refreshToken = null
        prefs.edit().clear().apply()
        _session.value = null
    }

    private fun readSession(): Session? {
        val email = prefs.getString(KEY_EMAIL, null) ?: return null
        val role = prefs.getString(KEY_ROLE, null) ?: return null
        if (prefs.getString(KEY_REFRESH, null) == null) return null
        return Session(email, role)
    }

    private companion object {
        const val ENCRYPTED_FILE = "qwik_session"
        const val PLAIN_FILE = "qwik_session_plain"

        fun encrypted(context: Context): SharedPreferences? = runCatching {
            EncryptedSharedPreferences.create(
                context,
                ENCRYPTED_FILE,
                MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
            )
        }.getOrNull()

        /** Throw the unreadable keyset away — the worst case is one sign-in. */
        fun wipe(context: Context) {
            runCatching { context.deleteSharedPreferences(ENCRYPTED_FILE) }
        }

        const val KEY_ACCESS = "access"
        const val KEY_REFRESH = "refresh"
        const val KEY_EMAIL = "email"
        const val KEY_ROLE = "role"
    }
}
