package com.qwikserve.recruiter.data

import android.content.Context
import android.os.Build
import com.qwikserve.recruiter.BuildConfig
import java.io.BufferedReader
import java.net.HttpURLConnection
import java.net.URL

/**
 * Sends a start-up failure to the server (`POST /app/crash`).
 *
 * Written with `HttpURLConnection` and hand-rolled JSON on purpose: this runs
 * when the app is already dying, so it must not need Hilt, OkHttp, Retrofit or
 * kotlinx-serialization — any of which could be the thing that broke. It also
 * has to run off the main thread (Android forbids network there), so the crash
 * path starts a thread and waits a few seconds for it.
 */
object CrashReporter {
    private const val TIMEOUT_MS = 5_000
    private const val MAX_TRAIL = 7_500 // the server caps at 8 000
    private const val MAX_DETAIL = 15_000 // …and 16 000

    /** Fire and forget — for the "last run never drew a frame" report at start. */
    fun postAsync(context: Context, kind: String, trail: String?, detail: String?) {
        val app = context.applicationContext ?: context
        Thread { runCatching { post(app, kind, trail, detail) } }.apply {
            isDaemon = true
            start()
        }
    }

    /** Blocking, for the crash path: waits up to [waitMs] for the send. */
    fun postBlocking(context: Context, kind: String, trail: String?, detail: String?, waitMs: Long = 6_000) {
        val app = context.applicationContext ?: context
        val t = Thread { runCatching { post(app, kind, trail, detail) } }
        t.isDaemon = true
        t.start()
        runCatching { t.join(waitMs) }
    }

    private fun post(context: Context, kind: String, trail: String?, detail: String?): Boolean {
        val body = json(
            "version" to BuildConfig.VERSION_NAME,
            "device" to "${Build.MANUFACTURER} ${Build.MODEL}",
            "android" to "${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})",
            "kind" to kind,
            "trail" to trail?.take(MAX_TRAIL),
            "detail" to detail?.take(MAX_DETAIL),
        )
        val conn = (URL(BuildConfig.API_BASE_URL + "app/crash").openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = TIMEOUT_MS
            readTimeout = TIMEOUT_MS
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
        }
        return try {
            conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val code = conn.responseCode
            runCatching {
                (if (code in 200..299) conn.inputStream else conn.errorStream)
                    ?.bufferedReader()?.use(BufferedReader::readText)
            }
            CrashLog.breadcrumb(context, "report.sent $kind -> $code")
            code in 200..299
        } catch (t: Throwable) {
            CrashLog.breadcrumb(context, "report.failed ${t.javaClass.simpleName}")
            false
        } finally {
            runCatching { conn.disconnect() }
        }
    }

    private fun json(vararg pairs: Pair<String, String?>): String =
        pairs.filter { it.second != null }.joinToString(",", "{", "}") { (k, v) ->
            "\"$k\":\"${escape(v!!)}\""
        }

    private fun escape(s: String): String = buildString(s.length + 16) {
        for (c in s) when (c) {
            '"' -> append("\\\"")
            '\\' -> append("\\\\")
            '\n' -> append("\\n")
            '\r' -> append("\\r")
            '\t' -> append("\\t")
            else -> if (c < ' ') append("\\u%04x".format(c.code)) else append(c)
        }
    }
}
