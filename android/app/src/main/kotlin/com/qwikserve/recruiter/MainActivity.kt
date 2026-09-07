package com.qwikserve.recruiter

import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import dagger.hilt.android.AndroidEntryPoint
import com.qwikserve.recruiter.data.CrashLog
import com.qwikserve.recruiter.ui.AppRoot
import com.qwikserve.recruiter.ui.theme.QwikTheme

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        // Splash and edge-to-edge are decoration: never let them take the app down.
        runCatching { installSplashScreen() }
        super.onCreate(savedInstanceState)
        runCatching { enableEdgeToEdge() }

        // If the last run died, show why — in plain Android views, because the
        // thing that died may well be Compose, Hilt or the fonts.
        val crash = CrashLog.read(this)
        if (crash != null) {
            setContentView(crashView(crash))
            return
        }
        setContent {
            QwikTheme {
                AppRoot()
            }
        }
    }

    /** Last crash as selectable text, with a button to clear it and go on. */
    private fun crashView(text: String): ViewGroup {
        val pad = (16 * resources.displayMetrics.density).toInt()
        val heading = TextView(this).apply {
            setText(R.string.crash_heading)
            setTextColor(Color.BLACK)
            textSize = 16f
            setPadding(pad, pad, pad, pad / 2)
        }
        val body = TextView(this).apply {
            setTextIsSelectable(true)
            setTextColor(Color.BLACK)
            textSize = 11f
            typeface = android.graphics.Typeface.MONOSPACE
            setPadding(pad, 0, pad, pad)
            this.text = text
        }
        val again = Button(this).apply {
            setText(R.string.crash_continue)
            setOnClickListener {
                CrashLog.clear(this@MainActivity)
                recreate()
            }
        }
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.WHITE)
            gravity = Gravity.START
            addView(heading)
            addView(body)
            addView(again)
        }
        return ScrollView(this).apply {
            setBackgroundColor(Color.WHITE)
            addView(column)
        }
    }
}
