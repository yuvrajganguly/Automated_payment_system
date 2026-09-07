package com.qwikserve.recruiter.data

import android.content.Context
import android.os.Build
import com.qwikserve.recruiter.BuildConfig
import java.io.File
import java.io.PrintWriter
import java.io.StringWriter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * A field app that dies on launch tells you nothing: the recruiter sees the
 * icon flash and close, and there is no logcat on a phone in a store. So the
 * app keeps two things of its own.
 *
 * **The last crash** — written by the default uncaught-exception handler,
 * installed from `attachBaseContext`, the earliest point we own.
 *
 * **A breadcrumb trail** — one line per startup step. Not every death is a
 * Java exception (a process the ROM kills, or a native crash, leaves no stack
 * trace at all), but the trail still shows exactly how far the last run got:
 * if it stops after `app.inject` we know the dependency graph is what died,
 * and if `ui.first_frame` is missing but everything else is there, the app is
 * failing to draw. The trail is rotated at every start, so what we read is
 * always the *previous* run.
 *
 * Deliberately dependency-free: this has to work when Hilt, Compose or the
 * fonts are the thing that broke.
 */
object CrashLog {
    private const val CRASH = "last_crash.txt"
    private const val TRAIL = "boot_trail.txt"
    private const val TRAIL_PREVIOUS = "boot_trail_previous.txt"

    /** The step that says a run was healthy; its absence is what we report. */
    const val FIRST_FRAME = "ui.first_frame"

    fun install(context: Context) {
        val app = context.applicationContext ?: context
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, error ->
            record(app, error, thread.name)
            previous?.uncaughtException(thread, error)
        }
    }

    fun record(context: Context, error: Throwable, thread: String = "unknown") {
        runCatching {
            val trace = StringWriter().also { error.printStackTrace(PrintWriter(it)) }
            File(context.filesDir, CRASH).writeText(header() + "thread $thread\n\n" + trace)
        }
        breadcrumb(context, "CRASH ${error.javaClass.simpleName}: ${error.message.orEmpty().take(160)}")
    }

    /** Start a fresh trail, keeping the one from the run that just ended. */
    fun rotateTrail(context: Context) {
        runCatching {
            val current = File(context.filesDir, TRAIL)
            val kept = File(context.filesDir, TRAIL_PREVIOUS)
            if (current.exists()) {
                kept.delete()
                if (!current.renameTo(kept)) current.copyTo(kept, overwrite = true)
            }
            File(context.filesDir, TRAIL).writeText(header())
        }
    }

    fun breadcrumb(context: Context, step: String) {
        runCatching {
            File(context.filesDir, TRAIL).appendText("${time()}  $step\n")
        }
    }

    fun previousTrail(context: Context): String? = read(context, TRAIL_PREVIOUS)

    fun lastCrash(context: Context): String? = read(context, CRASH)

    /** True when the previous run never drew a frame — i.e. it died on launch. */
    fun previousRunFailed(context: Context): Boolean {
        val trail = previousTrail(context) ?: return false
        return !trail.contains(FIRST_FRAME)
    }

    fun clear(context: Context) {
        runCatching {
            File(context.filesDir, CRASH).delete()
            File(context.filesDir, TRAIL_PREVIOUS).delete()
        }
    }

    private fun read(context: Context, name: String): String? = runCatching {
        File(context.filesDir, name).takeIf { it.exists() }?.readText()?.takeIf { it.isNotBlank() }
    }.getOrNull()

    private fun header(): String = buildString {
        appendLine("Qwikserve Recruiter ${BuildConfig.VERSION_NAME}")
        appendLine("${Build.MANUFACTURER} ${Build.MODEL} · Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})")
        appendLine(time())
    }

    private fun time(): String =
        SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.UK).format(Date())
}
