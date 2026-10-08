package cn.ppps.forwarder.database.repository

import androidx.annotation.WorkerThread
import androidx.sqlite.db.SimpleSQLiteQuery
import cn.ppps.forwarder.database.dao.LogsDao
import cn.ppps.forwarder.database.entity.Logs

class LogsRepository(private val logsDao: LogsDao) {

    @WorkerThread
    suspend fun insert(logs: Logs): Long = logsDao.insert(logs)

    @WorkerThread
    fun delete(id: Long) = logsDao.delete(id)

    fun deleteAll() = logsDao.deleteAll()

    @WorkerThread
    fun updateStatus(id: Long, status: Int, response: String): Int = logsDao.updateStatus(id, status, response)

    @WorkerThread
    fun updateResponse(id: Long, response: String): Int = logsDao.updateResponse(id, response)

    fun getOne(id: Long) = logsDao.getOne(id)

    // ===== 【新增】离线待发队列 =====

    /** 取一批「该重试」的失败记录（含发起后长时间没回音的僵尸记录，见 LogsDao 的说明） */
    @WorkerThread
    fun getPendingRetry(maxRetry: Int, now: Long, limit: Int, staleBefore: Long): List<Logs> =
        logsDao.getPendingRetry(maxRetry, now, limit, staleBefore)

    /** 标记已重试，并设置下次最早可重试时间（退避） */
    @WorkerThread
    fun markRetried(id: Long, nextRetryAt: Long): Int = logsDao.markRetried(id, nextRetryAt)

    /** 队列里还剩多少条（口径与 getPendingRetry 一致） */
    @WorkerThread
    fun countPendingRetry(staleBefore: Long): Int = logsDao.countPendingRetry(staleBefore)

    /** 清理超限/过老的失败记录 */
    @WorkerThread
    fun purgePendingRetry(maxRetry: Int, before: Long): Int = logsDao.purgePendingRetry(maxRetry, before)

    // ===== 【v61】数据精简（只裁已经成功发出的记录）=====

    @WorkerThread
    fun deleteSentBefore(before: Long): Int = logsDao.deleteSentBefore(before)

    @WorkerThread
    fun countSent(): Int = logsDao.countSent()

    @WorkerThread
    fun trimSentOldest(excess: Int): Int = logsDao.trimSentOldest(excess)

    fun getIdsByTimeAndStatus(hours: Int, statusList: List<Int>): List<Logs> {
        var sql = "SELECT * FROM Logs WHERE 1=1"
        if (hours > 0) {
            val time = System.currentTimeMillis() - hours * 3600000
            sql += " AND time>=$time"
        }
        if (statusList.isNotEmpty()) {
            val statusListStr = statusList.joinToString(",")
            sql += " AND forward_status IN ($statusListStr)"
        }
        sql += " ORDER BY id ASC"

        val query = SimpleSQLiteQuery(sql)
        return logsDao.getLogsRaw(query)
    }

}