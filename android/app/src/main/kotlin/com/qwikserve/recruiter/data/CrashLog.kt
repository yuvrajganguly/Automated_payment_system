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
 * app keeps its own last crash — written by the default uncaught-exception
 * handler, shown as plain text on the next launch (see MainActivity), and
 * cleared when it has been read.
 *
 * Deliberately dependency-free: this has to work when Hilt, Compose or the
 * fonts are the thing that broke.
 */
object CrashLog {
    private const val FILE = "last_crash.txt"

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
            val when_ = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.UK).format(Date())
            File(context.filesDir, FILE).writeText(
                buildString {
                    appendLine("Qwikserve Recruiter ${BuildConfig.VERSION_NAME}")
                    appendLine("${Build.MANUFACTURER} ${Build.MODEL} · Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})")
                    appendLine("$when_ · thread $thread")
                    appendLine()
                    append(trace.toString())
                },
            )
        }
    }

    fun read(context: Context): String? = runCatching {
        File(context.filesDir, FILE).takeIf { it.exists() }?.readText()?.takeIf { it.isNotBlank() }
    }.getOrNull()

    fun clear(context: Context) {
        runCatching { File(context.filesDir, FILE).delete() }
    }
}
