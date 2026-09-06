package com.qwikserve.recruiter.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.qwikserve.recruiter.ui.login.LoginScreen
import com.qwikserve.recruiter.ui.person.PersonScreen
import com.qwikserve.recruiter.ui.riders.RidersScreen

object Routes {
    const val LOGIN = "login"
    const val RIDERS = "riders"
    const val PERSON = "person/{personId}"
    fun person(id: Long) = "person/$id"
}

/**
 * Signed out → sign-in screen; signed in → the app. The switch is driven by
 * the token store, so a revoked session anywhere (refresh failed, password
 * changed by the creator) drops straight back to sign-in.
 */
@Composable
fun AppRoot(vm: SessionViewModel = hiltViewModel()) {
    val session by vm.session.collectAsStateWithLifecycle()
    val nav = rememberNavController()
    NavHost(
        navController = nav,
        startDestination = if (session == null) Routes.LOGIN else Routes.RIDERS,
    ) {
        composable(Routes.LOGIN) {
            LoginScreen(
                reason = vm.signedOutReason,
                onSignedIn = {
                    vm.clearReason()
                    nav.navigate(Routes.RIDERS) { popUpTo(Routes.LOGIN) { inclusive = true } }
                },
            )
        }
        composable(Routes.RIDERS) {
            RidersScreen(
                onOpenPerson = { id -> nav.navigate(Routes.person(id)) },
                onSignOut = {
                    vm.signOut()
                    nav.navigate(Routes.LOGIN) { popUpTo(0) { inclusive = true } }
                },
            )
        }
        composable(
            Routes.PERSON,
            arguments = listOf(navArgument("personId") { type = NavType.LongType }),
        ) { back ->
            PersonScreen(
                personId = back.arguments?.getLong("personId") ?: 0L,
                onBack = { nav.popBackStack() },
            )
        }
    }
    // A session that disappears while inside the app (refresh revoked) → sign-in.
    LaunchedEffect(session) {
        if (session == null && nav.currentDestination?.route != Routes.LOGIN) {
            nav.navigate(Routes.LOGIN) { popUpTo(0) { inclusive = true } }
        }
    }
}
