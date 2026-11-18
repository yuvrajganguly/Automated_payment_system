package com.qwikserve.recruiter.data.db

import android.app.Application
import androidx.room.Room
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [28])
class RiderSearchTest {
    private lateinit var db: AppDatabase
    private val dao get() = db.riderDao()

    private fun rider(id: String, active: Boolean, zone: String) = RiderEntity(
        riderId = id, company = "Jiffy", personId = if (id == "NTS-TEST") 1L else 2L,
        name = "Existing Rider", hub = "NTS", vehicle = "BIKE", mobNo = null,
        accountNo = null, accountName = null, ifsc = null, isActive = active,
        recruitedBy = "north@example.test", zone = zone, working = false,
        lastWorkedOn = null, haystack = "existing rider ${id.lowercase()} nts jiffy",
    )

    @Before fun setUp() = runBlocking {
        db = Room.inMemoryDatabaseBuilder(RuntimeEnvironment.getApplication(), AppDatabase::class.java)
            .allowMainThreadQueries().build()
        dao.upsertAll(listOf(rider("NTS-TEST", false, "North"), rider("SOUTH-TEST", true, "South")))
    }

    @After fun tearDown() = db.close()

    @Test fun `explicit name and id searches can find an inactive rider`() = runBlocking {
        for (q in listOf("existing rider", "nts-test")) {
            val found = dao.search(q, null, "North", null, includeInactive = true).first()
            assertEquals(listOf("NTS-TEST"), found.map { it.riderId })
        }
    }

    @Test fun `assignment pickers still exclude inactive riders`() = runBlocking {
        for (q in listOf("", "existing rider", "nts-test")) {
            assertEquals(emptyList<RiderEntity>(), dao.search(q, null, "North", null, false).first())
        }
    }

    @Test fun `roster browsing includes inactive riders without a search`() = runBlocking {
        assertEquals(
            listOf("NTS-TEST"),
            dao.search("", null, "North", null, true).first().map { it.riderId },
        )
    }

    @Test fun `including inactive riders preserves zone mine and working filters`() = runBlocking {
        assertEquals(
            listOf("NTS-TEST"),
            dao.search("existing", "north@example.test", "North", false, true).first().map { it.riderId },
        )
        assertEquals(emptyList<RiderEntity>(), dao.search("existing", "other@example.test", "North", null, true).first())
        assertEquals(emptyList<RiderEntity>(), dao.search("nts-test", null, "South", null, true).first())
        assertEquals(emptyList<RiderEntity>(), dao.search("nts-test", null, "North", true, true).first())
    }
}
