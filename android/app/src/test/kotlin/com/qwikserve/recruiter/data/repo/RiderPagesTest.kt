package com.qwikserve.recruiter.data.repo

import com.qwikserve.recruiter.data.api.RiderOut
import kotlinx.coroutines.runBlocking
import okhttp3.Headers
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response

class RiderPagesTest {
    private fun rider(id: Int, company: String = "Jiffy") =
        RiderOut(riderId = "TEST-$id", company = company, personId = id.toLong())

    private fun page(rows: List<RiderOut>, total: Int) =
        Response.success(rows, Headers.headersOf("X-Total-Count", total.toString()))

    @Test fun `downloads riders beyond the first 2000 including inactive ids`() = runBlocking {
        val roster = (1..2001).map { rider(it) }.toMutableList()
        roster[2000] = roster.last().copy(isActive = false)
        val offsets = mutableListOf<Int>()
        val result = loadRiderPages { limit, offset ->
            assertEquals(2000, limit)
            offsets.add(offset)
            page(roster.drop(offset).take(limit), roster.size)
        }
        assertEquals(listOf(0, 2000), offsets)
        assertEquals(roster, result)
    }

    @Test fun `total count takes precedence over a short page`() = runBlocking {
        val roster = (1..3).map { rider(it) }
        val result = loadRiderPages { _, offset -> page(roster.drop(offset).take(2), 3) }
        assertEquals(roster, result)
    }

    @Test fun `same rider id at two companies is two cache rows`() = runBlocking {
        val roster = listOf(rider(1), rider(1, "Kaptan"))
        assertEquals(roster, loadRiderPages { _, _ -> page(roster, 2) })
    }

    @Test fun `empty permitted roster completes`() = runBlocking {
        assertEquals(emptyList<RiderOut>(), loadRiderPages { _, _ -> page(emptyList(), 0) })
    }

    @Test fun `without count fetches until the first short page`() = runBlocking {
        val roster = (1..2001).map { rider(it) }
        val offsets = mutableListOf<Int>()
        val result = loadRiderPages { limit, offset ->
            offsets.add(offset)
            Response.success(roster.drop(offset).take(limit))
        }
        assertEquals(listOf(0, 2000), offsets)
        assertEquals(roster, result)
    }

    @Test fun `second page failure never returns a partial roster`() {
        val error = assertThrows(HttpException::class.java) {
            runBlocking {
                loadRiderPages { _, offset ->
                    if (offset == 0) page(listOf(rider(1)), 2)
                    else Response.error(503, "unavailable".toResponseBody())
                }
            }
        }
        assertEquals(503, error.code())
    }

    @Test fun `empty page before expected total is a failed sync`() {
        assertThrows(IllegalStateException::class.java) {
            runBlocking {
                loadRiderPages { _, offset ->
                    page(if (offset == 0) listOf(rider(1)) else emptyList(), 2)
                }
            }
        }
    }

    @Test fun `changing total or repeated rows fail instead of dropping riders`() {
        for (changeCount in listOf(true, false)) {
            assertThrows(IllegalStateException::class.java) {
                runBlocking {
                    loadRiderPages { _, offset ->
                        page(listOf(rider(1)), if (changeCount && offset > 0) 3 else 2)
                    }
                }
            }
        }
    }
}
