package com.qwikserve.recruiter.data.db

import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.RoomDatabase
import kotlinx.coroutines.flow.Flow

/** One rider id at one company — the roster row, cached for instant screens. */
@Entity(tableName = "riders", primaryKeys = ["riderId", "company"])
data class RiderEntity(
    val riderId: String,
    val company: String,
    val personId: Long,
    val name: String?,
    val hub: String?,
    val vehicle: String?,
    val mobNo: String?,
    val accountNo: String?,
    val ifsc: String?,
    val isActive: Boolean,
    /** lower-cased "name id phone hub" for local search without a FTS table */
    val haystack: String,
)

@Dao
interface RiderDao {
    @Query(
        "SELECT * FROM riders WHERE isActive = 1 AND (:q = '' OR haystack LIKE '%' || :q || '%') " +
            "ORDER BY name COLLATE NOCASE, company",
    )
    fun search(q: String): Flow<List<RiderEntity>>

    @Query("SELECT * FROM riders WHERE personId = :personId ORDER BY company")
    fun forPerson(personId: Long): Flow<List<RiderEntity>>

    @Query("SELECT COUNT(*) FROM riders")
    suspend fun count(): Int

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(rows: List<RiderEntity>)

    @Query("DELETE FROM riders")
    suspend fun clear()
}

@Database(entities = [RiderEntity::class], version = 1, exportSchema = true)
abstract class AppDatabase : RoomDatabase() {
    abstract fun riderDao(): RiderDao
}
