package cn.ppps.forwarder.receiver

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import cn.ppps.forwarder.activity.MainActivity
import cn.ppps.forwarder.utils.Log

/**
 * 拨号暗码入口。
 *
 * 本版本桌面无图标（已移除 MAIN/LAUNCHER），在系统拨号盘输入：
 *
 *     *#*#5555#*#*
 *
 * 即可打开本 App。这是唯一的手动入口（另外还有下拉通知栏的快捷磁贴）。
 */
class SecretCodeReceiver : BroadcastReceiver() {

    private val TAG: String = "SecretCodeReceiver"

    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != "android.provider.Telephony.SECRET_CODE") return
        try {
            val i = Intent(context, MainActivity::class.java)
            i.flags = Intent.FLAG_ACTIVITY_NEW_TASK
            context.startActivity(i)
            Log.d(TAG, "通过拨号暗码打开主界面")
        } catch (e: Exception) {
            Log.e(TAG, "暗码打开失败: ${e.message}")
        }
    }
}
