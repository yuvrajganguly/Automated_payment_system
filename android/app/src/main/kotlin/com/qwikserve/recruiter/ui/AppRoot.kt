package com.qwikserve.recruiter.ui

import android.net.Uri
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
import com.qwikserve.recruiter.ui.home.HomeScreen
import com.qwikserve.recruiter.ui.login.LoginScreen
import com.qwikserve.recruiter.ui.onboard.NewRiderScreen
import com.qwikserve.recruiter.ui.person.PersonScreen

object Routes {
    const val LOGIN = "login"
    const val HOME = "home"

    /**
     * One screen, two jobs. With no arguments it onboards somebody new. With
     * `personId` it adds an existing rider to a second company — the same
     * form, but attached to a person who already has a ledger, so the server
     * skips duplicate detection and copies their bank details across.
     *
     * The name rides along in the route rather than being fetched again: the
     * caller already has it on screen, and a recruiter standing in a hub with
     * one bar of signal should not need a round trip to fill in a form.
     */
    const val NEW_RIDER = "new-rider?personId={personId}&name={name}"

    fun newRider(personId: Long? = null, name: String? = null) =
        "new-rider?personId=${personId ?: -1L}&name=${Uri.encode(name ?: "")}"

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
        startDestination = if (session == null) Routes.LOGIN else Routes.HOME,
    ) {
        composable(Routes.LOGIN) {
            LoginScreen(
                reason = vm.signedOutReason,
                onSignedIn = {
                    vm.clearReason()
                    nav.navigate(Routes.HOME) { popUpTo(Routes.LOGIN) { inclusive = true } }
                },
            )
        }
        composable(Routes.HOME) {
            HomeScreen(
                onOpenPerson = { id -> nav.navigate(Routes.person(id)) },
                onNewRider = { nav.navigate(Routes.newRider()) },
                onAddCompany = { id, name -> nav.navigate(Routes.newRider(id, name)) },
                onSignOut = {
                    vm.signOut()
                    nav.navigate(Routes.LOGIN) { popUpTo(0) { inclusive = true } }
                },
            )
        }
        composable(
            Routes.NEW_RIDER,
            arguments = listOf(
                navArgument("personId") { type = NavType.LongType; defaultValue = -1L },
                navArgument("name") { type = NavType.StringType; defaultValue = "" },
            ),
        ) {
            NewRiderScreen(
                onBack = { nav.popBackStack() },
                onSaved = { id, _ ->
                    nav.navigate(Routes.person(id)) { popUpTo(Routes.HOME) }
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
                onAddCompany = { id, name ->
                    nav.navigate(Routes.newRider(personId = id, name = name))
                },
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
