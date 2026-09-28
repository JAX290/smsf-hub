package cn.ppps.forwarder.receiver

import android.content.Context
import android.database.ContentObserver
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.provider.Telephony
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
import com.google.gson.Gson
import cn.ppps.forwarder.entity.MsgInfo
import cn.ppps.forwarder.utils.Log
import cn.ppps.forwarder.utils.SettingUtils
import cn.ppps.forwarder.utils.Worker
import cn.ppps.forwarder.workers.SendWorker
import java.util.Date

/**
 * 【新增】已发送短信监听。
 *
 * 原理：Android 系统把「发出去的短信」写进 content://sms（type=2）。
 *      这里用 ContentObserver 盯着这个库，一有新记录就按同样的转发链路发出去，
 *      上报类型固定为 "sent"。
 *
 * 为什么不用无障碍：读系统短信库只要短信权限（功能1 已经授权过），
 *      完全后台运行、不留任何可见痕迹；而无障碍要在系统设置里手动开，还会被列出来。
 *
 * 只处理「首次启动之后新发出的短信」——启动时先记住当前最大 _id，
 * 避免把历史短信全部倒出去。
 */
class SentSmsObserver(private val context: Context) : ContentObserver(Handler(Looper.getMainLooper())) {

    private val TAG: String = SentSmsObserver::class.java.simpleName

    /** 已经处理过的最大短信 _id，用来去重 */
    private var lastSeenId: Long = 0L
    private var started = false
    private var registered = false

    /** 开始监听（记住当前最大 id，只转发之后的） */
    fun start() {
        if (registered) return
        lastSeenId = queryLatestSentId()
        started = true
        try {
            context.contentResolver.registerContentObserver(Telephony.Sms.CONTENT_URI, true, this)
            registered = true
            Log.i(TAG, "已开始监听已发送短信，起始 _id = $lastSeenId")
        } catch (e: Exception) {
            Log.e(TAG, "注册已发送短信监听失败: ${e.message}")
        }
    }

    fun stop() {
        if (!registered) return
        try {
            context.contentResolver.unregisterContentObserver(this)
        } catch (e: Exception) {
            Log.e(TAG, "注销监听失败: ${e.message}")
        }
        registered = false
        started = false
    }

    override fun onChange(selfChange: Boolean, uri: Uri?) {
        if (!started) return
        try {
            if (!SettingUtils.enableSentSms) return
            checkNewSent()
        } catch (e: Exception) {
            Log.e(TAG, "onChange: ${e.message}")
        }
    }

    /** 查当前「已发送」里最大的 _id */
    private fun queryLatestSentId(): Long {
        var id = 0L
        try {
            context.contentResolver.query(
                Telephony.Sms.CONTENT_URI, arrayOf("_id"),
                "type = ?", arrayOf("" + Telephony.Sms.MESSAGE_TYPE_SENT),
                "_id desc limit 1"
            )?.use { c ->
                if (c.moveToFirst()) id = c.getLong(0)
            }
        } catch (e: Exception) {
            Log.e(TAG, "queryLatestSentId: ${e.message}")
        }
        return id
    }

    /** 找出 _id 大于 lastSeenId 的已发送短信，逐条转发 */
    private fun checkNewSent() {
        val rows = mutableListOf<Array<String>>()
        val ids = mutableListOf<Long>()
        try {
            //⚠️ 注意：不同 ROM 的短信表字段不一样（华为只有 sub_id，没有 sim_id），
            //所以这里查「全部列」，再按列名取，避免某个列不存在导致整个查询抛异常。
            context.contentResolver.query(
                Telephony.Sms.CONTENT_URI,
                null,
                "type = ? and _id > ?",
                arrayOf("" + Telephony.Sms.MESSAGE_TYPE_SENT, "" + lastSeenId),
                "_id asc"
            )?.use { c ->
                val iId = c.getColumnIndex("_id")
                val iAddr = c.getColumnIndex("address")
                val iBody = c.getColumnIndex("body")
                val iDate = c.getColumnIndex("date")
                val iSub = c.getColumnIndex("sub_id")
                val iSim = c.getColumnIndex("sim_id")
                while (c.moveToNext()) {
                    val id = if (iId >= 0) c.getLong(iId) else 0L
                    val address = if (iAddr >= 0) (c.getString(iAddr) ?: "") else ""
                    val body = if (iBody >= 0) (c.getString(iBody) ?: "") else ""
                    val date = if (iDate >= 0) c.getLong(iDate) else System.currentTimeMillis()
                    // 华为: sub_id 即卡槽主键；小米: sim_id 实际是 subscription_id
                    var subId = 0
                    if (iSub >= 0 && !c.isNull(iSub)) subId = c.getInt(iSub)
                    else if (iSim >= 0 && !c.isNull(iSim)) subId = c.getInt(iSim)
                    ids.add(id)
                    rows.add(arrayOf(address, body, "" + date, "" + subId))
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "查询已发送短信失败: ${e.message}")
            return
        }
        if (rows.isEmpty()) return

        for ((index, row) in rows.withIndex()) {
            val address = row[0]
            val body = row[1]
            val date = row[2].toLongOrNull() ?: System.currentTimeMillis()
            val subId = row[3].toIntOrNull() ?: 0
            Log.i(TAG, "发现新发出的短信：发往 $address，长度 ${body.length}")
            dispatch(address, body, date, subId)
            if (ids[index] > lastSeenId) lastSeenId = ids[index]
        }
    }

    /** 复用现有的转发链路（和短信接收完全一样的出口） */
    private fun dispatch(address: String, body: String, date: Long, subId: Int) {
        try {
            // 卡槽：-1=获取失败、0=卡槽1、1=卡槽2
            var simSlot = -1
            if (SettingUtils.subidSim1 > 0 || SettingUtils.subidSim2 > 0) {
                simSlot = if (subId == SettingUtils.subidSim1) 0 else 1
            }
            val simInfo = when (simSlot) {
                0 -> "SIM1_" + SettingUtils.extraSim1
                1 -> "SIM2_" + SettingUtils.extraSim2
                else -> ""
            }
            val msgInfo = MsgInfo("sent", address, body, Date(date), simInfo, simSlot, subId)
            val request = OneTimeWorkRequestBuilder<SendWorker>().setInputData(
                workDataOf(Worker.SEND_MSG_INFO to Gson().toJson(msgInfo))
            ).build()
            WorkManager.getInstance(context).enqueue(request)
        } catch (e: Exception) {
            Log.e(TAG, "转发已发送短信失败: ${e.message}")
        }
    }
}
