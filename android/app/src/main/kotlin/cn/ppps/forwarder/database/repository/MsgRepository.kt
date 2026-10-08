package cn.ppps.forwarder.database.repository

import androidx.annotation.WorkerThread
import cn.ppps.forwarder.database.dao.MsgDao
import cn.ppps.forwarder.database.entity.Msg

class MsgRepository(private val msgDao: MsgDao) {

    @WorkerThread
    suspend fun insert(msg: Msg): Long = msgDao.insert(msg)

    @WorkerThread
    fun delete(id: Long) = msgDao.delete(id)

    fun deleteAll() = msgDao.deleteAll()

    @WorkerThread
    fun deleteTimeAgo(time: Long) = msgDao.deleteTimeAgo(time)

    // ===== 【v61】数据精简（只删没有任何转发记录的旧消息）=====

    @WorkerThread
    fun countAll(): Int = msgDao.countAll()

    @WorkerThread
    fun deleteOrphansBefore(before: Long): Int = msgDao.deleteOrphansBefore(before)

    @WorkerThread
    fun trimOrphansOldest(excess: Int): Int = msgDao.trimOrphansOldest(excess)

}