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

    /**
     * Zones this user may actually choose between, empty when there is no
     * choice to make.
     *
     * The server fences field staff to the zone on their account and answers
     * for that zone whatever is asked, so offering North / South / Misc / All
     * to a North recruiter would be four buttons that all do the same thing.
     * The bootstrap sends back only the zones they may pick; one of them means
     * no filter row.
     */
    fun zoneChoices(): List<String> {
        val boot = _bootstrap.value ?: return listOf("North", "South", "Misc")
        return if (boot.me.zone != null && boot.zones.size <= 1) emptyList() else boot.zones
    }
}
