package cn.ppps.forwarder.receiver

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import cn.ppps.forwarder.service.ForegroundService
import cn.ppps.forwarder.utils.ACTION_START
import cn.ppps.forwarder.utils.Log

/**
 * 开机自启。
 *
 * ⚠️ 原版行为是 startActivity(SplashActivity) —— 开机后会自动弹出 App 主界面。
 *    本版本已改为【只静默拉起后台服务，绝不弹任何界面】。
 */
class BootCompletedReceiver : BroadcastReceiver() {

    private val TAG: String = "BootCompletedReceiver"

    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action ?: return
        // 【已改造】不再处理 LOCKED_BOOT_COMPLETED：锁屏未解锁时启动进程会因访问
        // 凭据加密存储而崩溃（SharedPreferences in credential encrypted storage…）。
        // 解锁后系统会发送 BOOT_COMPLETED，届时再拉起服务。
        if (action != Intent.ACTION_BOOT_COMPLETED) return

        try {
            val svc = Intent(context, ForegroundService::class.java).apply { this.action = ACTION_START }
            ContextCompat.startForegroundService(context, svc)
            Log.d(TAG, "开机已静默拉起后台服务（不弹界面）")
        } catch (e: Exception) {
            Log.e(TAG, "开机拉起服务失败: ${e.message}")
        }
    }
}
