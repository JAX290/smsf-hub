package cn.ppps.forwarder.workers

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import cn.ppps.forwarder.database.AppDatabase
import cn.ppps.forwarder.database.entity.Digest
import cn.ppps.forwarder.entity.MsgInfo
import cn.ppps.forwarder.utils.Log
import cn.ppps.forwarder.utils.SettingUtils
import cn.ppps.forwarder.utils.Worker
import com.google.gson.Gson
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.util.Date
import java.util.concurrent.TimeUnit

/**
 * 【v55 新增】摘要冲刷：把 Digest 表里到点的消息**合并成一个请求**发出去。
 *
 * 为什么要做：
 *   手机每发一条消息就要唤醒一次射频。实测某台手机一天 715 条消息
 *   = 715 次射频唤醒，其中 73% 是真人消息、20% 是系统状态。
 *   攒成一批只发一次，唤醒次数能降到约 1/6。
 *
 * 包格式（服务端 pipeline.parse_digest 负责拆回一条条）：
 *     DIG|3
 *     {"ts":1790697000000,"k":"notify","a":"com.tencent.mm","n":"微信","ti":"张三","c":"晚上吃饭吗"}
 *     ...
 *
 * 为什么走 SendWorker 而不是直接调 WebhookUtils：
 *   SendWorker 会把这条消息落进 Msg/Logs 表，于是**离线队列的重试能力**直接复用
 *   （网络不通、secret 对不上都能自动补发）。所以我们把摘要包交给 SendWorker 之后
 *   就可以安全地删掉队列里的原始行 —— 投递责任已经转移给日志表了。
 */
class DigestWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    companion object {
        private const val TAG = "DigestWorker"
        private const val UNIQUE_NAME = "digest_flush"

        /** 摘要包的标记（要和服务器端 pipeline.py 的 DIGEST_RE 一致） */
        const val MARK = "__digest__"

        /** 兜底清理：超过这么多天的积压直接丢掉 */
        private const val KEEP_DAYS = 30L

        /**
         * 排一次冲刷。delayMs 是「最早一条到期还有多久」——
         * 到点才唤醒，不空转（和 HeartbeatWorker 一样用一次性任务）。
         */
        fun schedule(context: Context, delayMs: Long = 0L) {
            try {
                val request = OneTimeWorkRequestBuilder<DigestWorker>()
                    .setInitialDelay(delayMs.coerceAtLeast(0L), TimeUnit.MILLISECONDS)
                    .setConstraints(Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build())
                    .build()
                WorkManager.getInstance(context)
                    .enqueueUniqueWork(UNIQUE_NAME, ExistingWorkPolicy.REPLACE, request)
            } catch (e: Exception) {
                Log.e(TAG, "安排摘要冲刷失败: ${e.message}")
            }
        }

        /** 当前排着的那个任务的到期时刻（0 = 没排） */
        @Volatile
        private var scheduledDueAt = 0L

        /**
         * 有新的待发条目进来时调用。
         *
         * ⚠️ 这里**不能无脑重排**（2026-10-08 实测踩过）：
         *    每来一条通知都会调用本方法，而无条件 enqueue(REPLACE) 会把
         *    「已经排好、马上就要跑」的任务取消再重排 —— 通知一多就一直在取消重排，
         *    worker 永远轮不到执行。实测小米14：摘要队列堆到 20 条、
         *    最早一条过期 30 分钟，一条都没发出去。
         *
         * 所以只在「新的到期时间**比已经排着的更早**」时才重排：
         *   · 同一批里的后续消息 → 到期时间相同 → 什么都不做（这正是攒批要的）
         *   · 新来的短窗消息遇上已排的日摘要 → 15 分钟 < 24 小时 → 重排到更早
         */
        fun scheduleAtNextDue(context: Context) {
            try {
                val next = AppDatabase.getInstance(context).digestDao().nextDue() ?: return
                val now = System.currentTimeMillis()
                synchronized(Companion) {
                    if (scheduledDueAt > now && scheduledDueAt <= next) {
                        return
                    }
                    scheduledDueAt = next
                }
                schedule(context, (next - now).coerceAtLeast(3_000L))
            } catch (e: Exception) {
                Log.e(TAG, "读取下次到期时间失败: ${e.message}")
                schedule(context, 60_000L)
            }
        }

        /** 本轮跑完，标记「没有排着的任务了」，好让 finally 里能重新排 */
        private fun clearScheduled() {
            synchronized(Companion) { scheduledDueAt = 0L }
        }
    }

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        try {
            flush()
        } catch (e: Exception) {
            Log.e(TAG, "摘要冲刷异常: ${e.message}")
        } finally {
            // 不管成没成，都按当前最早到期时间排下一次
            clearScheduled()
            scheduleAtNextDue(applicationContext)
        }
        Result.success()
    }

    private fun flush() {
        val dao = AppDatabase.getInstance(applicationContext).digestDao()
        val now = System.currentTimeMillis()
        val limit = SettingUtils.digestMaxItems.coerceIn(20, 1000)
        val due = dao.due(now, limit)

        if (due.isNotEmpty()) {
            // 按档次分组：短窗一包、日摘要一包（不同档次的时效要求不一样）
            val groups = due.groupBy { it.tier }
            groups.forEach { (tier, items) -> handOff(items, tier) }
            dao.deleteByIds(due.map { it.id })
            Log.i(TAG, "已交给发送队列：" + due.size + " 条，分 " + groups.size + " 个摘要包")
        }

        // 兜底：清掉异常久远的积压，防表无限膨胀
        dao.purgeBefore(now - KEEP_DAYS * 24 * 3600 * 1000L)
    }

    /** 把一批消息打成一个摘要包，交给 SendWorker（复用离线队列的重试能力）。 */
    private fun handOff(items: List<Digest>, tier: Int) {
        val body = StringBuilder()
        body.append("DIG|").append(items.size)
        for (it in items) {
            val obj = JSONObject()
            obj.put("ts", it.time)
            // 注意：手机端内部把应用通知叫 "app"，服务端叫 "notify"。
            // 这里必须转成服务端的叫法，否则会被当成短信（分级直接给「关键」）。
            obj.put("k", if (it.type == "app") "notify" else it.type)
            obj.put("a", it.from)
            obj.put("n", it.app)
            obj.put("ti", it.title)
            obj.put("c", it.content)
            // JSONObject.toString() 会把正文里的换行转义成 \n，所以一条正好占一行
            body.append("\n").append(obj.toString())
        }

        val msg = MsgInfo(
            type = "app",
            from = MARK,
            content = body.toString(),
            date = Date(),
            simInfo = ""
        )
        val request = OneTimeWorkRequestBuilder<SendWorker>()
            .setInputData(workDataOf(Worker.SEND_MSG_INFO to Gson().toJson(msg)))
            .build()
        WorkManager.getInstance(applicationContext).enqueue(request)
        Log.i(TAG, "摘要包已入队：tier=$tier 条数=${items.size}")
    }
}
