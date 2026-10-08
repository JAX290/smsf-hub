package cn.ppps.forwarder.database.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import cn.ppps.forwarder.database.entity.Digest

/**
 * 【v55】待发摘要表的读写。
 *
 * 全部用同步方法（不用 suspend）：NotificationService.onNotificationPosted
 * 不是协程，而建库时开了 allowMainThreadQueries()，同步调用最简单可靠。
 */
@Dao
interface DigestDao {

    @Insert
    fun insert(item: Digest): Long

    /** 到点该发的条目（按到期时间升序） */
    @Query("SELECT * FROM Digest WHERE dueAt <= :now ORDER BY dueAt ASC LIMIT :limit")
    fun due(now: Long, limit: Int): List<Digest>

    /** 最早一条的到期时间，用来安排下一次冲刷；空表返回 null */
    @Query("SELECT MIN(dueAt) FROM Digest")
    fun nextDue(): Long?

    /**
     * 本档「当前正在等的那一批」的到期时间。
     *
     * 用途：新消息进来时**复用同一批的到期时间**，而不是各自算 now+窗口 ——
     * 否则相差几秒的消息会各自成批，等于"延迟发"而不是"攒批发"
     * （实测：3 条消息被拆成 3 个请求，白攒）。
     */
    @Query("SELECT MIN(dueAt) FROM Digest WHERE tier = :tier AND dueAt > :now")
    fun pendingDueAt(tier: Int, now: Long): Long?

    @Query("SELECT COUNT(*) FROM Digest")
    fun count(): Int

    @Query("DELETE FROM Digest WHERE id IN (:ids)")
    fun deleteByIds(ids: List<Long>)

    @Query("DELETE FROM Digest")
    fun clear()

    /** 兜底清理：太老的积压直接丢掉，防表无限膨胀 */
    @Query("DELETE FROM Digest WHERE time < :before")
    fun purgeBefore(before: Long)
}
