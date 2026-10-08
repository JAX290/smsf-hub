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
    // ----------------------------------------------------------------------------------
    //  【v58 修复】待重试的判定必须包含 forward_status = 1
    //
    //  三个状态的来历：0 = 待发；1 = 已发起、等回音；2 = 成功。
    //  以前这里只捞 0，于是**发起过但一直没回音**的记录被永久漏掉 ——
    //  进程被杀、请求挂死、线程池被压满，都会留下这种记录。
    //
    //  实测（2026-10-08，小米14）：status=1 积了 3440 条、横跨 8 天、retry_count 全是 0；
    //  最近 3 小时里成功 79 条、卡住 1917 条 —— 那台手机每小时产生约 640 条通知，
    //  只有 26 条发得出去，消息自然延迟几小时。而这些卡住的记录再也回不来。
    //
    //  所以：status=1 且**已经过去足够久**（超过 STALE_IN_FLIGHT_MS）的，当成待发重试。
    //  加时间条件是为了不误伤真正还在传输中的请求（避免重复发送）。
    // ----------------------------------------------------------------------------------
    @Query(
        "SELECT * FROM Logs WHERE (forward_status = 0" +
                " OR (forward_status = 1 AND time < :staleBefore))" +
                " AND retry_count < :maxRetry" +
                " AND next_retry_at <= :now" +
                " ORDER BY id ASC LIMIT :limit"
    )
    fun getPendingRetry(maxRetry: Int, now: Long, limit: Int, staleBefore: Long): List<Logs>

    /** 标记某条已重试：次数+1，并记下下次最早可重试时间（退避） */
    @Query("UPDATE Logs SET retry_count = retry_count + 1, next_retry_at = :nextRetryAt WHERE id = :id")
    fun markRetried(id: Long, nextRetryAt: Long): Int

    /** 队列里还剩多少条待重试（含上面说的僵尸记录，口径要和 getPendingRetry 一致） */
    @Query("SELECT COUNT(*) FROM Logs WHERE forward_status = 0" +
            " OR (forward_status = 1 AND time < :staleBefore)")
    fun countPendingRetry(staleBefore: Long): Int

    /**
     * 清理：重试次数耗尽、或已经太老的失败记录，避免队列无限膨胀。
     *
     * 注意这里**不动 status = 1 的记录** —— 那是还没定论的（可能正在传），
     * 由 getPendingRetry 的超时判定去接管；真到了太老的定义也在那边重试时被消化掉。
     */
    @Query("DELETE FROM Logs WHERE forward_status = 0 AND (retry_count >= :maxRetry OR time < :before)")
    fun purgePendingRetry(maxRetry: Int, before: Long): Int

    // ===== 【v61】数据精简 =====
    // 只裁「已经成功发出」（forward_status = 2）的记录：
    //   · 待发(0) 和卡住(1) 的绝不能删 —— 那些还要重试，删了就真丢了
    //   · 手机端是短期缓冲，永久档案在服务端
    @Query("DELETE FROM Logs WHERE forward_status = 2 AND time < :before")
    fun deleteSentBefore(before: Long): Int

    @Query("SELECT COUNT(*) FROM Logs WHERE forward_status = 2")
    fun countSent(): Int

    /** 条数兜底：按 id 从小到大（最旧）裁掉多余的已成功记录 */
    @Query("DELETE FROM Logs WHERE forward_status = 2 AND id IN (" +
            "SELECT id FROM Logs WHERE forward_status = 2 ORDER BY id ASC LIMIT :excess)")
    fun trimSentOldest(excess: Int): Int

    @Transaction
    @Query("SELECT * FROM Logs WHERE type = :type ORDER BY id DESC")
    fun pagingSource(type: String): PagingSource<Int, LogsAndRuleAndSender>

    @Transaction
    @RawQuery(observedEntities = [Logs::class])
    fun getLogsRaw(query: SupportSQLiteQuery): List<Logs>
}