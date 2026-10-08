package cn.ppps.forwarder.database.dao

import androidx.paging.PagingSource
import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.RawQuery
import androidx.room.Transaction
import androidx.room.Update
import androidx.sqlite.db.SupportSQLiteQuery
import cn.ppps.forwarder.database.entity.Msg
import cn.ppps.forwarder.database.entity.MsgAndLogs
import io.reactivex.Completable
import io.reactivex.Single

@Dao
interface MsgDao {

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insert(msg: Msg): Long

    @Delete
    fun delete(msg: Msg): Completable

    @Query("DELETE FROM Msg where id=:id")
    fun delete(id: Long)

    @RawQuery
    fun deleteAll(sql: SupportSQLiteQuery): Int

    @Query("DELETE FROM Msg")
    fun deleteAll()

    @Query("DELETE FROM Msg where time<:time")
    fun deleteTimeAgo(time: Long)

    // ===== 【v61】数据精简 =====
    // 手机端只是「中转缓冲」，永久档案在服务端。这里只删**已经没有任何转发记录**
    // 且够旧的消息 —— 待发/卡住的消息都还被 Logs 引用着，绝不会被删掉。
    // ⚠️ 子查询里必须排除 NULL/0 的 msg_id：SQL 里 `x NOT IN (…, NULL)` 永远不成立，
    //    一条脏数据就会让整个清理静默失效。
    @Query("SELECT COUNT(*) FROM Msg")
    fun countAll(): Int

    @Query("DELETE FROM Msg WHERE time < :before AND id NOT IN (" +
            "SELECT DISTINCT msg_id FROM Logs WHERE msg_id IS NOT NULL AND msg_id != 0)")
    fun deleteOrphansBefore(before: Long): Int

    @Query("DELETE FROM Msg WHERE id IN (SELECT id FROM Msg WHERE id NOT IN (" +
            "SELECT DISTINCT msg_id FROM Logs WHERE msg_id IS NOT NULL AND msg_id != 0)" +
            " ORDER BY id ASC LIMIT :excess)")
    fun trimOrphansOldest(excess: Int): Int

    @Update
    fun update(msg: Msg): Completable

    @Query("SELECT * FROM Msg where id=:id")
    fun get(id: Long): Single<Msg>

    @Query("SELECT count(*) FROM Msg where type=:type")
    fun count(type: String): Single<Int>

    @Transaction
    @Query("SELECT * FROM Msg WHERE type = :type ORDER BY id DESC")
    fun pagingSource(type: String): PagingSource<Int, MsgAndLogs>

    @Transaction
    @RawQuery(observedEntities = [MsgAndLogs::class])
    fun pagingSource(query: SupportSQLiteQuery): PagingSource<Int, MsgAndLogs>

}