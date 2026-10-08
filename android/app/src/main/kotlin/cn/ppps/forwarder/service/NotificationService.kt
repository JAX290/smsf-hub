package cn.ppps.forwarder.service

import android.annotation.SuppressLint
import android.app.Notification
import android.content.ComponentName
import android.os.Build
import android.os.UserHandle
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
import cn.ppps.forwarder.core.Core
import cn.ppps.forwarder.database.entity.Rule
import cn.ppps.forwarder.entity.MsgInfo
import cn.ppps.forwarder.utils.Log
import cn.ppps.forwarder.utils.PACKAGE_NAME
import cn.ppps.forwarder.utils.SettingUtils
import cn.ppps.forwarder.utils.Worker
import cn.ppps.forwarder.workers.SendWorker
import com.google.gson.Gson
import com.xuexiang.xrouter.utils.TextUtils
import com.xuexiang.xutil.display.ScreenUtils
import java.util.Date


@Suppress("PrivatePropertyName", "DEPRECATION")
class NotificationService : NotificationListenerService() {

    private val TAG: String = NotificationService::class.java.simpleName

    override fun onListenerConnected() {
        Log.d(TAG, "onListenerConnected")
    }

    override fun onListenerDisconnected() {
        //纯客户端模式
        if (SettingUtils.enablePureClientMode) return

        //总开关
        if (!SettingUtils.enableAppNotify) return

        Log.d(TAG, "通知侦听器断开连接 - 请求重新绑定")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            requestRebind(ComponentName(this, NotificationListenerService::class.java))
        }
    }

    @SuppressLint("DiscouragedPrivateApi")
    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        try {
            //纯客户端模式
            if (SettingUtils.enablePureClientMode) return

            //异常通知跳过
            val notification = sbn?.notification ?: return
            val extras = notification.extras ?: return

            //自动消除额外APP通知
            SettingUtils.cancelExtraAppNotify
                .takeIf { it.isNotEmpty() }
                ?.split("\n")
                ?.forEach { app ->
                    if (sbn.packageName == app.trim()) {
                        Log.d(TAG, "自动消除额外APP通知：$app")
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                            cancelNotification(sbn.key)
                        } else {
                            cancelNotification(sbn.packageName, sbn.tag, sbn.id)
                        }
                        return@forEach
                    }
                }


            //总开关
            if (!SettingUtils.enableAppNotify) return

            //仅锁屏状态转发APP通知
            if (SettingUtils.enableNotUserPresent && !ScreenUtils.isScreenLock()) return

            // 【2026-09-28 再改造】发件人一律用「包名」，不再用应用名。
            //
            // 之前的做法是取 getApplicationLabel()（中文名），拿不到才退回包名。
            // 问题是同一个应用会因此产生两种值：正常情况下报「Soul」，
            // 取名字失败时报「cn.soulapp.android」，服务端就把它当成两个应用，
            // 面板筛选里出现两个一模一样的「Soul」。
            //
            // 包名是稳定的，永远不变；中文名交给服务端那张映射表去翻。
            // 同时模板里的 app 字段会带上 {{APP_NAME}}，服务端能拿到中文名用于显示。
            val from = sbn.packageName
            //自身通知跳过
            if (PACKAGE_NAME == sbn.packageName) return
            // 标题
            val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString() ?: ""
            // 通知内容
            var text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString() ?: ""
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                val bigText = extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString() ?: ""
                if (bigText.isNotEmpty()) {
                    text = bigText
                }
            }
            if (text.isEmpty() && notification.tickerText != null) {
                text = notification.tickerText.toString()
            }

            //不处理空消息（标题跟内容都为空）
            if (TextUtils.isEmpty(title) && TextUtils.isEmpty(text)) return

            //关键词黑名单：一行一个，支持正则，命中标题或内容则不转发
            if (isInBlacklist(title, text)) {
                Log.d(TAG, "命中APP通知关键词黑名单，跳过转发。title=$title, text=$text")
                return
            }

            // 【v53 新增】噪音跳过：只针对「系统应用发的纯状态通知」。
            //
            // 判据是通知自己的属性（常驻 + 通知类别），不是猜包名 ——
            // 「正在播放 / VPN 已连接 / 系统正在优化 / USB 调试已连接」这类
            // 都是 ongoing + category=service|progress|transport|sysinfo，
            // 对用户没有任何信息量，直接不发，省流量也省服务端存储。
            //
            // 刻意只跳过系统应用（uid < 10000）的：第三方 App 的状态通知
            // （音乐播放器、下载器等）照旧上报，服务端会把它判成「噪音」
            // 并在归档里只留一行摘要，历史仍然可查。
            if (SettingUtils.enableSkipSystemStatusNoise && isSystemStatusNoise(sbn, notification)) {
                Log.d(TAG, "跳过系统状态通知：" + sbn.packageName + " cat=" + notification.category)
                return
            }

            // 【v53 新增】把通知自身的属性拼成一行附在正文末尾，交给服务端判级：
            //     NAT|cat=msg|ong=0|imp=3|grp=0
            // 为什么用这种行格式：WebhookUtils 会把正文套进用户配置的模板里，
            // 结构化字段会被打散；行格式即使被前后包了别的内容也能正则捞出来
            //（和心跳的 HBT| 是同一个思路）。
            val natLine = buildNotifyAttr(sbn, notification)
            val contentForSend = if (natLine.isEmpty()) text else text + "\n" + natLine

            val msgInfo = MsgInfo("app", from, contentForSend, Date(), title, -1)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                Log.d(TAG, "消息的UID====>" + sbn.uid)
                msgInfo.uid = sbn.uid
            }
            //TODO：自动消除通知（临时方案，重复查询换取准确性）
            if (SettingUtils.enableCancelAppNotify) {
                val ruleList: List<Rule> = Core.rule.getRuleList(msgInfo.type, 1, "SIM0")
                for (rule in ruleList) {
                    if (rule.checkMsg(msgInfo)) {
                        Log.d(TAG, "自动消除通知")
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                            cancelNotification(sbn.key)
                        } else {
                            cancelNotification(sbn.packageName, sbn.tag, sbn.id)
                        }
                        break
                    }
                }
            }

            val request = OneTimeWorkRequestBuilder<SendWorker>().setInputData(
                workDataOf(
                    Worker.SEND_MSG_INFO to Gson().toJson(msgInfo),
                )
            ).build()
            WorkManager.getInstance(applicationContext).enqueue(request)

        } catch (e: Exception) {
            Log.e(TAG, "Parsing Notification failed: " + e.message.toString())
        }

    }

    /**
     * 把通知自身的属性拼成一行，供服务端判级用。
     *
     *     NAT|cat=msg|ong=0|imp=3|grp=0
     *
     * cat = Notification.category（Android 官方语义：msg/call/email/service/progress/transport…）
     * ong = 是否常驻（正在播放、VPN 已连接、正在充电这类都是常驻）
     * imp = 通知渠道重要度 0-5（0 = 渠道被用户关掉了）
     * grp = 是否是群组摘要
     *
     * 有了这几项，服务端判「这条是不是真在通知用户」就非常准，
     * 不用再去猜包名属于哪一类应用。
     */
    private fun buildNotifyAttr(sbn: StatusBarNotification, notification: Notification): String {
        return try {
            val sb = StringBuilder("NAT")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                val cat = notification.category ?: ""
                if (cat.isNotEmpty()) {
                    sb.append("|cat=").append(cat)
                }
                sb.append("|ong=").append(if (sbn.isOngoing) 1 else 0)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                val imp = channelImportance(sbn)
                if (imp >= 0) {
                    sb.append("|imp=").append(imp)
                }
            }
            val grp = (notification.flags and Notification.FLAG_GROUP_SUMMARY) != 0
            sb.append("|grp=").append(if (grp) 1 else 0)
            sb.toString()
        } catch (e: Exception) {
            Log.w(TAG, "生成通知属性行失败：" + e.message)
            ""
        }
    }

    /** 取通知渠道的重要度（0=关闭 1=低 2=默认 3=高 4=紧急），拿不到返回 -1。 */
    private fun channelImportance(sbn: StatusBarNotification): Int {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return -1
        val chId = sbn.notification.channelId ?: return -1
        if (chId.isEmpty()) return -1
        return try {
            // 必须走 NotificationListenerService 的接口：NotificationManager
            // 只能看到「本应用自己」的通知渠道，查别的应用会返回 null。
            // 注意签名是 getNotificationChannels(pkg, UserHandle)，不是 (pkg, int uid)
            // —— 编译踩过两次，这里记一笔。
            val user = UserHandle.getUserHandleForUid(sbn.uid)
            getNotificationChannels(sbn.packageName, user)
                ?.firstOrNull { it.id == chId }?.importance ?: -1
        } catch (e: Exception) {
            -1
        }
    }

    /**
     * 是不是「系统应用发的纯状态通知」——这类直接不发。
     *
     * 只认通知自己的属性，不猜包名；而且只认系统应用（uid < 10000），
     * 第三方 App 的状态通知仍然上报（服务端归档里留一行摘要）。
     */
    private fun isSystemStatusNoise(sbn: StatusBarNotification, notification: Notification): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.LOLLIPOP) return false
        if (!sbn.isOngoing) return false
        val uid = try {
            sbn.uid
        } catch (e: Exception) {
            return false
        }
        if (uid < 1000 || uid >= 10000) return false
        val cat = (notification.category ?: "").lowercase()
        return cat == "service" || cat == "progress" || cat == "transport" ||
                cat == "sysinfo" || cat == "status" || cat == "system"
    }

    //关键词黑名单匹配：一行一个关键词，支持正则表达式，命中通知标题或内容任意一项即返回 true
    private fun isInBlacklist(title: String, text: String): Boolean {        val blacklist = SettingUtils.appNotifyBlacklist
        if (TextUtils.isEmpty(blacklist)) return false

        for (line in blacklist.split("\n")) {
            val keyword = line.trim()
            if (keyword.isEmpty()) continue
            try {
                val regex = Regex(keyword)
                if (regex.containsMatchIn(title) || regex.containsMatchIn(text)) {
                    return true
                }
            } catch (e: Exception) {
                //正则表达式非法时，降级为普通包含匹配
                Log.w(TAG, "黑名单关键词正则非法，降级为包含匹配：$keyword, ${e.message}")
                if (title.contains(keyword) || text.contains(keyword)) {
                    return true
                }
            }
        }
        return false
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification?) {
        Log.d(TAG, "Removed Package Name : ${sbn?.packageName}")
    }

}