package com.qwikserve.recruiter.data.repo

import com.qwikserve.recruiter.data.api.Bootstrap
import com.qwikserve.recruiter.data.api.PayoutApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import javax.inject.Inject
import javax.inject.Singleton

/** Process-wide small state: the bootstrap payload (me, companies, hubs, zones). */
@Singleton
class AppRepository @Inject constructor(private val api: PayoutApi) {
    private val _bootstrap = MutableStateFlow<Bootstrap?>(null)
    val bootstrap: StateFlow<Bootstrap?> = _bootstrap

    suspend fun refreshBootstrap(): Bootstrap = api.bootstrap().also { _bootstrap.value = it }

    /** The zone a list should open on: the recruiter's own, else "All". */
    fun defaultZone(): String = _bootstrap.value?.me?.zone ?: "All"
}
