package cn.ppps.forwarder.workers

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import cn.ppps.forwarder.core.Core
import cn.ppps.forwarder.entity.MsgInfo
import cn.ppps.forwarder.entity.setting.WebhookSetting
import cn.ppps.forwarder.utils.CommonUtils
import cn.ppps.forwarder.utils.Log
import cn.ppps.forwarder.utils.SettingUtils
import cn.ppps.forwarder.utils.TYPE_WEBHOOK
import cn.ppps.forwarder.utils.sender.WebhookUtils
import com.google.gson.Gson
import com.hjq.permissions.XXPermissions
import com.hjq.permissions.permission.PermissionLists
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.util.Date
import java.util.concurrent.TimeUnit

/**
 * 【新增】心跳：每 10 分钟跟服务器报一次「我还活着」。
 *
 * 为什么要做：
 *   光看「最近有没有消息上报」判断不了手机死活 ——
 *   手机安静一晚上（没短信没通知）和被系统杀了，在服务器数据上长得一模一样。
 *   心跳是主动信号，能把这俩区分开，面板首页就能按手机显示成绿/黄/红。
 *
 * 报什么（负载格式见下方 buildPayload）：
 *   App 版本 / 权限是否齐全 / 转发服务是否在跑
 *
 * 怎么发：
 *   借用数据库里「通知上报」那条通道（含服务器地址和 secret），
 *   但**不走 SendWorker** —— 直接调 WebhookUtils，
 *   这样不会往 Logs/Msg 表里插记录，不污染消息流和统计。
 *
 * 为什么负载不做成 JSON：
 *   WebhookUtils 会把 content 套进用户配置的模板里，
 *   套完之后 JSON 结构就散了。所以用一个「正则能捞出来」的行格式，
 *   服务器端用正则提取（见 app/pipeline.py 的 parse_heartbeat）。
 */
class HeartbeatWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    companion object {
        private const val TAG = "HeartbeatWorker"
        private const val UNIQUE_NAME = "heartbeat"

        /** 心跳间隔（分钟）。服务器端超时阈值是它的 2.5 倍，别只改这里。 */
        private const val INTERVAL_MINUTES = 10L

        /** 心跳标记：服务器靠这个认出心跳包（要和 pipeline.py 的 HEARTBEAT_MARK 一致） */
        const val MARK = "__heartbeat__"

        /**
         * 启动心跳（幂等：用 REPLACE 保证同时只有一个待执行）。
         *
         * 不用 PeriodicWork 是因为它最小周期被系统限制在 15 分钟，
         * 而用户要的是 10 分钟。改成「一次性任务 + 干完自己排下一次」。
         */
        fun schedule(context: Context, delayMinutes: Long = 0L) {
            try {
                val request = OneTimeWorkRequestBuilder<HeartbeatWorker>()
                    .setInitialDelay(delayMinutes, TimeUnit.MINUTES)
                    .setConstraints(Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build())
                    .build()
                WorkManager.getInstance(context)
                    .enqueueUniqueWork(UNIQUE_NAME, ExistingWorkPolicy.REPLACE, request)
            } catch (e: Exception) {
                Log.e(TAG, "安排心跳失败: \${e.message}")
            }
        }
    }

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        try {
            sendOnce()
        } catch (e: Exception) {
            Log.e(TAG, "心跳发送异常: \${e.message}")
        } finally {
            // 不管这次成没成，都排下一次 —— 心跳不能因为一次失败就断了
            schedule(applicationContext, INTERVAL_MINUTES)
        }
        Result.success()
    }

    private fun sendOnce() {
        // 找到「通知上报」那条通道，借用它的服务器地址和 secret
        val sender = Core.sender.getAllNonCache().firstOrNull {
            it.type == TYPE_WEBHOOK && it.name.contains("通知")
        } ?: Core.sender.getAllNonCache().firstOrNull { it.type == TYPE_WEBHOOK }

        if (sender == null) {
            Log.e(TAG, "找不到可用的 Webhook 通道，跳过本次心跳")
            return
        }
        val setting = try {
            Gson().fromJson(sender.jsonSetting, WebhookSetting::class.java)
        } catch (e: Exception) {
            Log.e(TAG, "解析通道配置失败: \${e.message}")
            return
        }
        if (setting == null || setting.webServer.isEmpty()) {
            Log.e(TAG, "通道没有配置服务器地址，跳过本次心跳")
            return
        }

        val msg = MsgInfo(
            type = "app",
            from = MARK,
            content = buildPayload(),
            date = Date(),
            simInfo = ""
        )
        // 直接发，不走 SendWorker —— 心跳不该出现在消息流和日志里
        // 【v55】顺带接收服务端在响应里下发的「摘要窗口」配置并应用
        WebhookUtils.sendMsg(setting, msg) { resp -> applyDigestConfig(resp) }
        Log.i(TAG, "心跳已发送")
    }

    /**
     * 服务端在心跳响应里下发摘要窗口配置（见服务端 pipeline.digest_config），
     * 这里应用到本地设置 —— 于是**面板上改完就生效，不用重装 APK**。
     *
     * 整段 best-effort：解析失败什么都不做，绝不影响心跳本身。
     */
    private fun applyDigestConfig(response: String) {
        try {
            val obj = JSONObject(response)
            val d = obj.optJSONObject("digest") ?: return
            if (d.has("enable")) SettingUtils.enableDigest = d.optBoolean("enable", true)
            if (d.has("near_minutes")) SettingUtils.digestNearMinutes = d.optInt("near_minutes", 15)
            if (d.has("daily_hours")) SettingUtils.digestDailyHours = d.optInt("daily_hours", 24)
            if (d.has("instant_apps")) SettingUtils.digestInstantApps = d.optString("instant_apps", "")
            if (d.has("instant_keywords")) SettingUtils.digestInstantKeywords = d.optString("instant_keywords", "")
            if (d.has("max_items")) SettingUtils.digestMaxItems = d.optInt("max_items", 200)
            Log.i(TAG, "已应用服务端下发的摘要配置：短窗=" + SettingUtils.digestNearMinutes +
                    "分钟 日摘要=" + SettingUtils.digestDailyHours + "小时")
        } catch (e: Exception) {
            Log.e(TAG, "解析服务端摘要配置失败（忽略）: ${e.message}")
        }
    }

    /**
     * 负载格式（一行，用 | 分隔，方便服务器正则提取）：
     *
     *   HBT|版本名|版本号|sms=1,call=1,notify=1,location=1|working=1|uptime=秒
     *
     * 服务器端 pipeline.py 的 parse_heartbeat() 用 HBT\| 开头来认。
     */
    private fun buildPayload(): String {
        val perms = try {
            val ctx = cn.ppps.forwarder.App.context
            val sms = XXPermissions.isGrantedPermissions(ctx, listOf(
                PermissionLists.getReceiveSmsPermission(),
                PermissionLists.getReadSmsPermission()))
            val call = XXPermissions.isGrantedPermissions(ctx, listOf(
                PermissionLists.getReadCallLogPermission(),
                PermissionLists.getReadPhoneStatePermission()))
            val notify = CommonUtils.isNotificationListenerServiceEnabled(ctx)
            val loc = XXPermissions.isGrantedPermissions(ctx, listOf(
                PermissionLists.getAccessFineLocationPermission(),
                PermissionLists.getAccessCoarseLocationPermission()))
            "sms=${if (sms) 1 else 0},call=${if (call) 1 else 0}," +
                    "notify=${if (notify) 1 else 0},location=${if (loc) 1 else 0}"
        } catch (e: Exception) {
            Log.e(TAG, "检查权限失败: \${e.message}")
            ""
        }

        // 「在跑」的判断：转发总开关开着就算在跑（前台服务由系统托管，
        // 这里拿不到更细的状态；而且心跳能发出来本身就说明进程活着）
        val working = if (SettingUtils.enableSms || SettingUtils.enablePhone ||
            SettingUtils.enableAppNotify) 1 else 0

        val ver = try { cn.ppps.forwarder.utils.AppUtils.getAppVersionName() } catch (e: Exception) { "" }
        val code = try { cn.ppps.forwarder.utils.AppUtils.getAppVersionCode() } catch (e: Exception) { 0 }

        return "HBT|" + ver + "|" + code + "|" + perms + "|working=" + working
    }
}
