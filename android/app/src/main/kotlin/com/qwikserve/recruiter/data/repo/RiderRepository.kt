package com.qwikserve.recruiter.data.repo

import com.qwikserve.recruiter.data.api.PayoutApi
import com.qwikserve.recruiter.data.api.PersonOut
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
    fun search(q: String): Flow<List<RiderEntity>> = dao.search(q.trim().lowercase())

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
        haystack = listOfNotNull(name, riderId, mobNo?.filter { it.isDigit() }, mobNo, hub, company)
            .joinToString(" ")
            .lowercase(),
    )
}
