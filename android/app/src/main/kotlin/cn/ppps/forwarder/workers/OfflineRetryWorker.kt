package cn.ppps.forwarder.workers

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import cn.ppps.forwarder.core.Core
import cn.ppps.forwarder.utils.Log
import cn.ppps.forwarder.utils.SendUtils
import cn.ppps.forwarder.utils.SettingUtils
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import java.util.concurrent.TimeUnit

/**
 * 【新增】离线待发队列。
 *
 * 解决的问题：
 *   网络不通、或者换了服务器后 secret 没对上（上报被 401 拒）时，
 *   原来那条转发记录就永远停在 forward_status=0，消息再也没机会发出去。
 *   用户的原话：「待发信息应该存起来，等恢复通讯的时候重试」。
 *
 * 做法（不另起一套存储，复用现有的 Logs 表）：
 *   失败记录本身就留在 Logs 表里，天然持久化，进程被杀也不丢。
 *   这个 Worker 负责在合适的时机把它们捞出来逐条重发：
 *     · 网络恢复时立刻跑一次
 *     · 平时每 15 分钟兜底跑一次
 *     · App 启动时跑一次
 *   重发成功 → forward_status 变成 2，自然出队。
 *
 * 防重复 / 防雪崩：
 *   · 每次只处理 batchSize 条，条与条之间留间隔，不会一拥而上
 *   · 取出来之前先 markRetried 把 next_retry_at 推后，
 *     这样即使这次还是失败，也要等退避时间过了才会被下一轮捞到，不会原地打转
 *   · 用 uniqueWork 保证同一时刻只有一个实例在跑
 *   · 指数退避 + 次数上限 + 保留天数上限，队列不会无限膨胀
 */
class OfflineRetryWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    companion object {
        private const val TAG = "OfflineRetryWorker"

        /** 一次性任务的唯一名字：同一时刻只允许一个排队或在跑 */
        private const val UNIQUE_ONCE = "offline_retry_once"

        /** 周期兜底任务的唯一名字 */
        private const val UNIQUE_PERIODIC = "offline_retry_periodic"

        /** 周期兜底间隔（WorkManager 允许的最小值就是 15 分钟） */
        private const val PERIODIC_MINUTES = 15L

        /** 相邻两条重发之间留一点间隔，别一拥而上 */
        private const val GAP_MS = 300L

        /**
         * 单次运行最多提交多少条。
         * 积压很多时不能无限跑下去（WorkManager 对单次执行有时限，跑太久会被掐掉），
         * 剩下的交给下一轮（网络恢复 / 15 分钟周期兜底）。
         */
        private const val MAX_PER_RUN = 200

        /**
         * 指数退避：第 n 次失败之后，隔多久才允许再试。
         * 前几次给得短一点（网络抖一下就恢复了），后面拉长到 30 分钟封顶。
         */
        fun backoffMillis(retryCount: Int): Long = when {
            retryCount <= 1 -> 30_000L      // 30 秒
            retryCount == 2 -> 60_000L      // 1 分钟
            retryCount == 3 -> 120_000L     // 2 分钟
            retryCount == 4 -> 300_000L     // 5 分钟
            retryCount == 5 -> 600_000L     // 10 分钟
            else -> 1_800_000L              // 30 分钟（封顶）
        }

        /** 网络恢复 / App 启动时调用：立刻安排一次重试 */
        fun enqueue(context: Context) {
            try {
                val request = OneTimeWorkRequestBuilder<OfflineRetryWorker>()
                    .setConstraints(networkConstraints())
                    .build()
                WorkManager.getInstance(context)
                    .enqueueUniqueWork(UNIQUE_ONCE, ExistingWorkPolicy.KEEP, request)
            } catch (e: Exception) {
                Log.e(TAG, "enqueue error: ${e.message}")
            }
        }

        /** 注册周期兜底任务（重复调用不会叠加） */
        fun schedulePeriodic(context: Context) {
            try {
                val request = PeriodicWorkRequestBuilder<OfflineRetryWorker>(PERIODIC_MINUTES, TimeUnit.MINUTES)
                    .setConstraints(networkConstraints())
                    .build()
                WorkManager.getInstance(context)
                    .enqueueUniquePeriodicWork(UNIQUE_PERIODIC, ExistingPeriodicWorkPolicy.KEEP, request)
            } catch (e: Exception) {
                Log.e(TAG, "schedulePeriodic error: ${e.message}")
            }
        }

        private fun networkConstraints(): Constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
    }

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        try {
            if (!SettingUtils.enableOfflineQueue) {
                Log.d(TAG, "离线队列未启用，跳过")
                return@withContext Result.success()
            }

            val maxRetry = SettingUtils.offlineQueueMaxRetry
            val batchSize = SettingUtils.offlineQueueBatchSize
            val now = System.currentTimeMillis()

            // 顺手清理：重试次数已耗尽的、以及太久以前的失败记录
            val before = now - SettingUtils.offlineQueueMaxAgeDays * 24L * 3600_000L
            val purged = Core.logs.purgePendingRetry(maxRetry, before)
            if (purged > 0) Log.d(TAG, "清理过期失败记录 $purged 条")

            val queuedTotal = Core.logs.countPendingRetry()
            Log.d(TAG, "队列共 $queuedTotal 条待发")
            if (queuedTotal == 0) return@withContext Result.success()

            // ⚠️ 这里必须用循环，不能"跑一批再 enqueue 一次自己"：
            //    enqueue 用的是 ExistingWorkPolicy.KEEP，而此刻当前 Worker 正在运行，
            //    同名任务已存在 → KEEP 会直接忽略，递归根本不会发生（踩过这个坑）。
            //    循环处理是安全的：每条出来后 next_retry_at 被推后至少 30 秒，
            //    所以下一轮查询不会再次捞到同一条，不会原地打转。
            var submitted = 0
            var rounds = 0
            while (submitted < MAX_PER_RUN) {
                val nowRound = System.currentTimeMillis()
                val pending = Core.logs.getPendingRetry(maxRetry, nowRound, batchSize)
                if (pending.isEmpty()) break
                rounds++

                for (log in pending) {
                    // 先标记再发：把 next_retry_at 推后。
                    // 这样即使这条又失败了，也要等退避时间过了才会被下一轮捞到。
                    Core.logs.markRetried(log.id, nowRound + backoffMillis(log.retryCount))
                    try {
                        SendUtils.retrySendMsg(log.id)
                        submitted++
                    } catch (e: Exception) {
                        Log.e(TAG, "重发 logId=${log.id} 失败: ${e.message}")
                    }
                    delay(GAP_MS)
                }
                if (pending.size < batchSize) break
            }

            val left = Core.logs.countPendingRetry()
            Log.d(TAG, "本轮共提交 $submitted 条（$rounds 批），队列还剩 $left 条")
            Result.success()
        } catch (e: Exception) {
            Log.e(TAG, "doWork error: ${e.message}", e)
            Result.retry()
        }
    }
}
