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
import cn.ppps.forwarder.database.entity.Logs
import cn.ppps.forwarder.database.entity.LogsAndRuleAndSender
import io.reactivex.Completable
import io.reactivex.Single

@Dao
interface LogsDao {

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insert(logs: Logs): Long

    @Delete
    fun delete(logs: Logs): Completable

    @Query("DELETE FROM Logs where id=:id")
    fun delete(id: Long)

    @Query("DELETE FROM Logs where type=:type")
    fun deleteAll(type: String): Completable

    @Query("DELETE FROM Logs")
    fun deleteAll()

    @Update
    fun update(logs: Logs): Completable

    @Query(
        "UPDATE Logs SET forward_status=:status" +
                ",forward_response=CASE WHEN (trim(forward_response) = '' or trim(forward_response) = 'ok')" +
                " THEN :response" +
                " ELSE forward_response || '\n--------------------\n' || :response" +
                " END" +
                " where id=:id"
    )
    fun updateStatus(id: Long, status: Int, response: String): Int

    @Query(
        "UPDATE Logs SET forward_response=CASE WHEN (trim(forward_response) = '' or trim(forward_response) = 'ok')" +
                " THEN :response" +
                " ELSE forward_response || '\n' || :response" +
                " END" +
                " where id=:id"
    )
    fun updateResponse(id: Long, response: String): Int

    @Query("SELECT * FROM Logs where id=:id")
    fun get(id: Long): Single<Logs>

    @Transaction
    @Query("SELECT * FROM Logs where id=:id")
    fun getOne(id: Long): LogsAndRuleAndSender

    @Query("SELECT count(*) FROM Logs where type=:type and forward_status=:forwardStatus")
    fun count(type: String, forwardStatus: Int): Single<Int>

    // ===== 【新增】离线待发队列 =====
    // 背景：网络不通、或换服务器后 secret 没对上（401）时，原来这条转发记录就永远停在
    //      forward_status=0，消息本身再也没机会发出去。现在把失败记录当成队列，
    //      等网络恢复或定时再逐条重试。

    /** 取一批「该重试」的失败记录：次数没到上限、且已过退避等待时间 */
    @Query(
        "SELECT * FROM Logs WHERE forward_status = 0" +
                " AND retry_count < :maxRetry" +
                " AND next_retry_at <= :now" +
                " ORDER BY id ASC LIMIT :limit"
    )
    fun getPendingRetry(maxRetry: Int, now: Long, limit: Int): List<Logs>

    /** 标记某条已重试：次数+1，并记下下次最早可重试时间（退避） */
    @Query("UPDATE Logs SET retry_count = retry_count + 1, next_retry_at = :nextRetryAt WHERE id = :id")
    fun markRetried(id: Long, nextRetryAt: Long): Int

    /** 队列里还剩多少条待重试 */
    @Query("SELECT COUNT(*) FROM Logs WHERE forward_status = 0")
    fun countPendingRetry(): Int

    /** 清理：重试次数耗尽、或已经太老的失败记录，避免队列无限膨胀 */
    @Query("DELETE FROM Logs WHERE forward_status = 0 AND (retry_count >= :maxRetry OR time < :before)")
    fun purgePendingRetry(maxRetry: Int, before: Long): Int

    @Transaction
    @Query("SELECT * FROM Logs WHERE type = :type ORDER BY id DESC")
    fun pagingSource(type: String): PagingSource<Int, LogsAndRuleAndSender>

    @Transaction
    @RawQuery(observedEntities = [Logs::class])
    fun getLogsRaw(query: SupportSQLiteQuery): List<Logs>
}