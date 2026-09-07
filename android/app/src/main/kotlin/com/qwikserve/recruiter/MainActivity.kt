package com.qwikserve.recruiter

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.SideEffect
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import dagger.hilt.android.AndroidEntryPoint
import com.qwikserve.recruiter.data.CrashLog
import com.qwikserve.recruiter.ui.AppRoot
import com.qwikserve.recruiter.ui.theme.QwikTheme

/**
 * The app proper. [LaunchActivity] is what the launcher starts; it comes here
 * once it is happy, so a start-up that dies in Compose or in the dependency
 * graph is still reportable next time.
 */
@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    /** One breadcrumb, not one per recomposition. */
    private var drewOnce = false

    override fun onCreate(savedInstanceState: Bundle?) {
        CrashLog.breadcrumb(this, "main.pre_super")
        // Splash and edge-to-edge are decoration: never let them take the app down.
        runCatching { installSplashScreen() }
        super.onCreate(savedInstanceState)
        CrashLog.breadcrumb(this, "main.post_super")
        runCatching { enableEdgeToEdge() }
        setContent {
            QwikTheme {
                SideEffect {
                    if (!drewOnce) {
                        drewOnce = true
                        CrashLog.breadcrumb(this@MainActivity, CrashLog.FIRST_FRAME)
                    }
                }
                AppRoot()
            }
        }
        CrashLog.breadcrumb(this, "main.set_content")
    }
}
