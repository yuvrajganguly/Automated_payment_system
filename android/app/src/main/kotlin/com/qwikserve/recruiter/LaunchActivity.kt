package com.qwikserve.recruiter

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import com.qwikserve.recruiter.data.CrashLog

/**
 * The launcher. A plain Activity — no Hilt, no Compose, no theme of ours —
 * so that whatever else is broken, *something* still comes up and can say so.
 *
 * Normal run: hand straight over to [MainActivity]. Run after a launch that
 * never drew a frame: show the breadcrumb trail and the last stack trace, with
 * a button to copy the text and one to carry on.
 */
class LaunchActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        CrashLog.breadcrumb(this, "launch.start")
        if (CrashLog.previousRunFailed(this)) {
            setContentView(report())
        } else {
            open()
        }
    }

    private fun open() {
        CrashLog.breadcrumb(this, "launch.forward")
        startActivity(Intent(this, MainActivity::class.java))
        overridePendingTransition(0, 0)
        finish()
    }

    private fun reportText(): String = buildString {
        appendLine("Qwikserve Recruiter — start-up report")
        appendLine()
        appendLine("── how far the last run got ──")
        appendLine(CrashLog.previousTrail(this@LaunchActivity) ?: "(no trail)")
        appendLine("── last crash ──")
        append(CrashLog.lastCrash(this@LaunchActivity) ?: "(no stack trace — the process was killed rather than throwing)")
    }

    private fun report(): ViewGroup {
        val text = reportText()
        val pad = (16 * resources.displayMetrics.density).toInt()
        val heading = TextView(this).apply {
            setText(R.string.crash_heading)
            setTextColor(Color.BLACK)
            textSize = 15f
            setPadding(pad, pad, pad, pad / 2)
        }
        val buttons = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(pad, 0, pad, 0)
            addView(
                Button(this@LaunchActivity).apply {
                    setText(R.string.crash_copy)
                    setOnClickListener {
                        val clip = getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
                        clip?.setPrimaryClip(ClipData.newPlainText("Qwikserve start-up report", text))
                        Toast.makeText(this@LaunchActivity, R.string.crash_copied, Toast.LENGTH_SHORT).show()
                    }
                },
            )
            addView(
                Button(this@LaunchActivity).apply {
                    setText(R.string.crash_continue)
                    setOnClickListener {
                        CrashLog.clear(this@LaunchActivity)
                        open()
                    }
                },
            )
        }
        val body = TextView(this).apply {
            setTextIsSelectable(true)
            setTextColor(Color.BLACK)
            textSize = 11f
            typeface = Typeface.MONOSPACE
            setPadding(pad, pad / 2, pad, pad)
            this.text = text
        }
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.WHITE)
            addView(heading)
            addView(buttons)
            addView(body)
        }
        return ScrollView(this).apply {
            setBackgroundColor(Color.WHITE)
            addView(column)
        }
    }
}
