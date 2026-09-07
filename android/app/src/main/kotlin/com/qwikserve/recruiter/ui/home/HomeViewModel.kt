package com.qwikserve.recruiter.ui.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qwikserve.recruiter.data.api.Bootstrap
import com.qwikserve.recruiter.data.location.AppOpenLocation
import com.qwikserve.recruiter.data.repo.AppRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class HomeViewModel @Inject constructor(
    private val repo: AppRepository,
    private val location: AppOpenLocation,
) : ViewModel() {
    val bootstrap: StateFlow<Bootstrap?> = repo.bootstrap

    init {
        viewModelScope.launch { runCatching { repo.refreshBootstrap() } }
    }

    fun hasLocationPermission() = location.hasPermission()

    /** Right after the permission dialog (granted or not): take the app-open fix if we may. */
    fun onLocationPermission() = location.recordNow("app_open")
}
