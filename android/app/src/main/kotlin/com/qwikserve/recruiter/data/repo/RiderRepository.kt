package com.qwikserve.recruiter.data.repo

import com.qwikserve.recruiter.data.api.PayoutApi
import com.qwikserve.recruiter.data.api.PersonOut
import com.qwikserve.recruiter.data.api.RiderIn
import com.qwikserve.recruiter.data.api.RiderOut
import androidx.room.withTransaction
import com.qwikserve.recruiter.data.db.AppDatabase
import com.qwikserve.recruiter.data.db.RiderDao
import com.qwikserve.recruiter.data.db.RiderEntity
import kotlinx.coroutines.flow.Flow
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Read-cached, write-online. The roster (a few hundred rows) is pulled whole
 * and kept in Room; every list and search reads Room, and [refresh] runs
 * behind the screen. Writes go straight to the server and re-sync.
 */
@Singleton
class RiderRepository @Inject constructor(
    private val api: PayoutApi,
    private val db: AppDatabase,
    private val dao: RiderDao,
) {
    fun search(
        q: String,
        mine: String? = null,
        zone: String? = null,
        working: Boolean? = null,
    ): Flow<List<RiderEntity>> = dao.search(q.trim().lowercase(), mine, zone, working)

    fun forPerson(personId: Long): Flow<List<RiderEntity>> = dao.forPerson(personId)

    suspend fun hasCache(): Boolean = dao.count() > 0

    /** Pull the whole roster (active and inactive) and replace the cache. */
    suspend fun refresh() {
        val res = api.riders(limit = 2000)
        val body = res.body() ?: throw IllegalStateException("HTTP ${res.code()}")
        val rows = body.map { it.toEntity() }
        db.withTransaction {
            dao.clear()
            dao.upsertAll(rows)
        }
    }

    suspend fun person(personId: Long): PersonOut = api.person(personId)

    /** Onboard a rider (online only), then fold the new row into the cache. */
    suspend fun create(body: RiderIn): RiderOut {
        val out = api.createRider(body)
        dao.upsertAll(listOf(out.toEntity()))
        return out
    }

    private fun RiderOut.toEntity() = RiderEntity(
        riderId = riderId,
        company = company,
        personId = personId,
        name = name,
        hub = hub,
        vehicle = vehicle,
        mobNo = mobNo,
        accountNo = accountNo,
        ifsc = ifsc,
        isActive = isActive,
        recruitedBy = recruitedBy,
        zone = zone,
        working = working,
        lastWorkedOn = lastWorkedOn,
        haystack = listOfNotNull(name, riderId, mobNo?.filter { it.isDigit() }, mobNo, hub, company)
            .joinToString(" ")
            .lowercase(),
    )
}
