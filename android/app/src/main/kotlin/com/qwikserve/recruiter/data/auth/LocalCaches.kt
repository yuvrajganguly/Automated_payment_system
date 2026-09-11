package com.qwikserve.recruiter.data.auth

import android.content.Context
import coil.imageLoader
import com.qwikserve.recruiter.data.db.AppDatabase
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Everything this phone remembers about whoever was signed in.
 *
 * Clearing the tokens is not the whole of signing out. Two caches outlive the
 * session, and both are keyed on something identical for every account:
 *
 *  * Coil keys its image caches by URL, and the app asks for its own picture
 *    at `recruiters/me/photo` — one string, every user. Sign out, sign in as
 *    somebody else, and the face in the app bar is still the last person's
 *    (reported 2026-09-10: signing in as Shivam showed Yuvraj's picture).
 *  * Room holds the rider list. Riders are fenced by zone since 2026-09, so a
 *    cache left behind shows a North recruiter the South roster until the
 *    first refresh lands — the fence held on the server and leaked on the
 *    phone.
 *
 * This is called from both places a session ends: the sign-out button, and a
 * refresh token the server has rejected. Anything user-specific cached in
 * future belongs here too.
 */
@Singleton
class LocalCaches @Inject constructor(
    @ApplicationContext private val context: Context,
    private val db: AppDatabase,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    fun wipe() {
        // Memory first and synchronously: the sign-in screen is composed
        // immediately after this returns, and an in-memory bitmap would paint
        // before any coroutine got the chance to run.
        runCatching { context.imageLoader.memoryCache?.clear() }
        // Disk and Room are slower and off the main thread. A failure here is
        // not worth breaking a sign-out over — the caches are keyed per user
        // as well, so this is the second line of defence, not the only one.
        scope.launch {
            runCatching { context.imageLoader.diskCache?.clear() }
            runCatching { db.riderDao().clear() }
        }
    }
}
