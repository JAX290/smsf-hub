package cn.ppps.forwarder.utils

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.ResolveInfo
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.annotation.RequiresApi
import cn.ppps.forwarder.R

@Suppress("DEPRECATION")
class KeepAliveUtils private constructor() {

    companion object {
        fun isIgnoreBatteryOptimization(activity: Activity): Boolean {
            //安卓6.0以下没有忽略电池优化
            return if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
                true
            } else try {
                val powerManager: PowerManager = activity.getSystemService(Context.POWER_SERVICE) as PowerManager
                powerManager.isIgnoringBatteryOptimizations(activity.packageName)
            } catch (e: Exception) {
                XToastUtils.error(R.string.unsupport)
                false
            }
        }

        @RequiresApi(api = Build.VERSION_CODES.M)
        fun ignoreBatteryOptimization(activity: Activity) {
            try {
                if (isIgnoreBatteryOptimization(activity)) {
                    return
                }
                @SuppressLint("BatteryLife") val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                intent.data = Uri.parse("package:" + activity.packageName)
                val resolveInfo: ResolveInfo? = activity.packageManager.resolveActivity(intent, 0)
                if (resolveInfo != null) {
                    activity.startActivity(intent)
                } else {
                    XToastUtils.error(R.string.unsupport)
                }
            } catch (e: Exception) {
                XToastUtils.error(R.string.unsupport)
            }
        }

        /**
         * 是不是 MIUI / HyperOS（小米、红米）。
         *
         * 为什么要单独判：这些 ROM 把标准的电池优化入口改掉了 ——
         * 实测 MIUI 12.5 上 `ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` 会被解析成
         * `com.android.internal.app.ResolverActivity`，弹出来的是 MIUI 自己的
         * 「电量详情」页，那页只有「结束运行 / 卸载 / 应用信息」，**没有电池优化开关**，
         * 用户点进来只会一脸问号（真实反馈：2026-10-09）。
         */
        fun isMiui(): Boolean {
            return try {
                val m = (Build.MANUFACTURER ?: "").lowercase()
                val d = (Build.DISPLAY ?: "").lowercase()
                val b = (Build.BRAND ?: "").lowercase()
                m.contains("xiaomi") || m.contains("redmi") ||
                        b.contains("xiaomi") || b.contains("redmi") ||
                        d.contains("miui") || d.contains("hyperos")
            } catch (e: Exception) {
                false
            }
        }

        /**
         * 打开「电池优化」列表页。
         *
         * 实测 MIUI 上这个 action 会落到
         * `com.miui.powerkeeper.ui.HiddenAppsContainerManagementActivity` ——
         * 也就是 MIUI 自己的省电策略管理页，在里面把「收音机」设成「无限制」才真正管用。
         */
        fun openBatteryOptimizationList(activity: Activity) {
            try {
                activity.startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            } catch (e: Exception) {
                XToastUtils.error(R.string.unsupport)
            }
        }

        /** 打开「应用信息」页（MIUI 的应用信息里也有「省电策略」，是第二个能设到「无限制」的入口）*/
        fun openAppInfo(activity: Activity) {
            try {
                val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                intent.data = Uri.parse("package:" + activity.packageName)
                activity.startActivity(intent)
            } catch (e: Exception) {
                XToastUtils.error(R.string.unsupport)
            }
        }

    }
}