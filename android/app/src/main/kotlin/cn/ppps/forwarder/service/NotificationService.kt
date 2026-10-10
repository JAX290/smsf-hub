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
import cn.ppps.forwarder.database.AppDatabase
import cn.ppps.forwarder.database.entity.Digest
import cn.ppps.forwarder.database.entity.Rule
import cn.ppps.forwarder.entity.MsgInfo
import cn.ppps.forwarder.utils.Log
import cn.ppps.forwarder.utils.PACKAGE_NAME
import cn.ppps.forwarder.utils.SettingUtils
import cn.ppps.forwarder.utils.Worker
import cn.ppps.forwarder.workers.DigestWorker
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

            // 【v59 新增】MIUI 的「XX 正在后台运行」提示：纯噪音，直接丢。
            //
            // 为什么要单列一条（v53 那套判据拦不住它）：
            //   实测小米14，这条提示是 com.android.mms（短信 App，系统 uid）发出来的，
            //   **既不是常驻、也没有通知类别**，靠「系统应用 + 常驻 + 类别」完全判不出来。
            //   8 天里同一条出现了 9428 次，占那台手机全部消息的 23%
            //   （另一条「睡眠服务后台运行中」占 8%）—— 白白占满上报管道。
            //
            // ⚠️ 这里用的是**上面已经拼好的 title/text**，不是通知的各个 extras：
            //    真机上这条文案落在 EXTRA_BIG_TEXT 里，一开始我去读 EXTRA_TEXT 结果一条没拦住
            //    （而 adb 造的测试通知恰好放在 EXTRA_TEXT，所以"测起来是好的"，很坑）。
            //    用拼好的正文就一定能拦住真正会转发出去的东西。
            if (SettingUtils.enableSkipSystemStatusNoise && isMiuiBackgroundNoise(title, text)) {
                Log.d(TAG, "跳过 MIUI 后台提示：$title | $text")
                return
            }

            // 【v53 新增】把通知自身的属性拼成一行附在正文末尾，交给服务端判级：
            //     NAT|cat=msg|ong=0|imp=3|grp=0
            // 为什么用这种行格式：WebhookUtils 会把正文套进用户配置的模板里，
            // 结构化字段会被打散；行格式即使被前后包了别的内容也能正则捞出来
            //（和心跳的 HBT| 是同一个思路）。
            val natLine = buildNotifyAttr(sbn, notification)
            val contentForSend = if (natLine.isEmpty()) text else text + "\n" + natLine

            // 【v55 新增】攒批发送：不在「立即」桶里的通知先存进 Digest 表，
            // 由 DigestWorker 到点合并成**一个请求**发出去（省射频唤醒）。
            // 窗口值由服务端通过心跳响应下发，面板上改完就生效。
            val delayMs = digestDelayMs(from, title, text, natLine)
            if (delayMs != null) {
                try {
                    val now = System.currentTimeMillis()
                    val dao = AppDatabase.getInstance(applicationContext).digestDao()
                    // 攒很久的算「日摘要」（tier 0），其余算「短窗」（tier 2）
                    val tier = if (delayMs >= 3600_000L) 0 else 2
                    // 【关键】复用「本档当前正在等的那一批」的到期时间：
                    // 若各条自己算 now+窗口，相差几秒的消息会各自成批，
                    // 变成"延迟发"而不是"攒批发"（实测 3 条拆成 3 个请求）。
                    val dueAt = dao.pendingDueAt(tier, now) ?: (now + delayMs)
                    dao.insert(
                        Digest(
                            dueAt = dueAt,
                            time = now,
                            tier = tier,
                            type = "app",
                            from = from,
                            app = appLabel(from).ifEmpty { from },
                            title = title,
                            content = contentForSend
                        )
                    )
                    DigestWorker.scheduleAtNextDue(applicationContext)
                    Log.d(TAG, "已存入摘要队列，${(dueAt - now) / 60000} 分钟后合并发送")
                    return
                } catch (e: Exception) {
                    Log.e(TAG, "存入摘要队列失败，改为立即发送: ${e.message}")
                }
            }

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

        // 【v70】不再要求「有通知类别」。
        //
        // 原来这里还要求 category 属于 service/progress/transport/sysinfo/status/system，
        // 但真机上那些最烦人的常驻通知**根本没有类别** ✗：
        //   已连接到 USB 调试 / 正在通过 USB 充电 / 扫描设备 / 0B/s↑ 0B/s↓ / 正在同步天气
        // 实测 2026-10-10 小米14 的摘要队列里 2656 条积压，绝大多数就是这些
        //（1410 条是 tier=0 的常驻状态），白白占满上报管道。
        //
        // 现在的判据很干脆：**系统应用（uid < 10000）发的常驻通知，一律不发**。
        // 第三方 App 的常驻通知（音乐播放器、下载器等）仍然照发，
        // 由服务端判成「噪音」并在归档里只留一行摘要。
        return true
    }

    /**
     * MIUI「正在后台运行」类提示——固定文案，零信息量。
     *
     * 传入的是 App 已经拼好的标题和正文（见 onNotificationPosted 里的 text 拼装逻辑），
     * 不是通知的原始 extras —— 真机上这段文案在 EXTRA_BIG_TEXT 里，读错字段会一条都拦不到。
     */
    private fun isMiuiBackgroundNoise(title: String, text: String): Boolean {
        val blob = title + "\n" + text
        return blob.contains("点按即可了解详情或停止应用") ||
                blob.contains("正在后台运行") ||
                blob.contains("后台运行中")
    }

    /**
     * 这条通知该立即发、还是攒起来？返回 null = 立即发；否则返回要攒的毫秒数。
     *
     * 判定（手机上只做粗分，细分级交给服务端）：
     *   · 攒批总开关关掉 / 两个窗口都是 0 → 立即
     *   · 命中「立即关键词」（验证码/扣款…）→ 立即
     *   · 在「立即应用」清单里 → 立即
     *   · 系统/应用状态类（常驻、类别是 service/progress/transport/sysinfo）→ 日摘要
     *   · 其余（真人消息、普通推送）→ 短窗摘要
     *
     * 短信/来电/已发送/定位本来就不走这里（各有自己的通道），永远立即发。
     */
    private fun digestDelayMs(pkg: String, title: String, text: String, nat: String): Long? {
        if (!SettingUtils.enableDigest) return null
        val nearMin = SettingUtils.digestNearMinutes
        val dailyHours = SettingUtils.digestDailyHours
        if (nearMin <= 0 && dailyHours <= 0) return null

        val keywords = SettingUtils.digestInstantKeywords
        if (keywords.isNotEmpty()) {
            val blob = (title + "\n" + text).lowercase()
            for (one in keywords.replace("，", ",").split(",")) {
                val k = one.trim().lowercase()
                if (k.isNotEmpty() && blob.contains(k)) return null
            }
        }
        val apps = SettingUtils.digestInstantApps
        if (apps.isNotEmpty()) {
            for (one in apps.replace("，", ",").split(",")) {
                val a = one.trim()
                if (a.isNotEmpty() && pkg.contains(a, ignoreCase = true)) return null
            }
        }

        val statusLike = nat.contains("|ong=1") ||
                nat.contains("cat=service") || nat.contains("cat=progress") ||
                nat.contains("cat=transport") || nat.contains("cat=sysinfo") ||
                nat.contains("cat=status") || nat.contains("cat=system")
        val minutes = if (statusLike) dailyHours * 60 else nearMin
        if (minutes <= 0) return null
        return minutes * 60_000L
    }

    /** 应用中文名（拿不到就返回空串，调用方会退回包名）。 */
    private fun appLabel(pkg: String): String {
        return try {
            cn.ppps.forwarder.App.UserAppList.firstOrNull { it.packageName == pkg }?.name
                ?: cn.ppps.forwarder.App.SystemAppList.firstOrNull { it.packageName == pkg }?.name
                ?: ""
        } catch (e: Exception) {
            ""
        }
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