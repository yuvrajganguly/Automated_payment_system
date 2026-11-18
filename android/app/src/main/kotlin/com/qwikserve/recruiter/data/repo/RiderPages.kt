package com.qwikserve.recruiter.data.repo

import com.qwikserve.recruiter.data.api.RiderOut
import retrofit2.HttpException
import retrofit2.Response

/** Fetch every permitted row before replacing Room, so failed pages preserve the old cache. */
internal suspend fun loadRiderPages(
    fetch: suspend (limit: Int, offset: Int) -> Response<List<RiderOut>>,
): List<RiderOut> {
    val pageSize = 2000
    val rows = mutableListOf<RiderOut>()
    val keys = mutableSetOf<Pair<String, String>>()
    var expectedTotal: Int? = null
    while (true) {
        val response = fetch(pageSize, rows.size)
        if (!response.isSuccessful) throw HttpException(response)
        val page = checkNotNull(response.body()) { "The server returned no rider list. Try again." }
        val total = response.headers()["X-Total-Count"]?.toIntOrNull()?.takeIf { it >= 0 }
        if (total != null) {
            check(expectedTotal == null || expectedTotal == total) {
                "The rider list changed during refresh. Pull down to try again."
            }
            expectedTotal = total
        }
        check(page.all { keys.add(it.riderId to it.company) }) {
            "The rider list changed during refresh. Pull down to try again."
        }
        rows.addAll(page)
        val target = expectedTotal
        if (target != null) {
            check(rows.size <= target && (page.isNotEmpty() || rows.size == target)) {
                "The rider list was incomplete. Pull down to try again."
            }
            if (rows.size == target) return rows
        } else if (page.size < pageSize) {
            // Older servers may omit the count; a short page ends that roster.
            return rows
        }
    }
}
