package cn.ppps.forwarder.database.entity

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * 【v55 新增】待发摘要 —— 手机端「攒一波再发」的队列。
 *
 * 为什么要有它：
 *   手机每发一条消息就要唤醒一次射频。实测某台手机一天 715 条消息
 *   = 715 次射频唤醒，其中 73% 是真人消息、20% 是系统状态。
 *   把消息先攒在这张表里、到点合并成**一个请求**发出去，
 *   唤醒次数能降到约 1/6（服务端会再拆回一条条，归档粒度不变）。
 *
 * dueAt 决定什么时候该发：
 *   · 普通通知（含微信/QQ/Telegram）→ 收到时间 + digestNearMinutes（默认 15 分钟）
 *   · 系统/应用状态类（常驻、"正在后台运行"）→ 收到时间 + digestDailyHours（默认 24 小时）
 *   · 短信/来电/已发送/定位 以及命中「立即关键词」的，根本不进这张表，直接发
 *
 * 窗口值由服务端通过**心跳响应**下发（见 pipeline.digest_config），
 * 所以在面板上改完就生效，不用重新编译 APK。
 */
@Entity(tableName = "Digest", indices = [Index("dueAt")])
data class Digest(
    @PrimaryKey(autoGenerate = true) var id: Long = 0,
    /** 到点该发的时间（毫秒） */
    var dueAt: Long = 0,
    /** 消息收到的真实时间（毫秒），服务端用它做归档时间 */
    var time: Long = 0,
    /** 2 = 短窗（普通通知/真人消息）；0 = 日摘要（系统状态） */
    var tier: Int = 2,
    /** 类型，目前都是 notify（短信/来电/定位有自己的通道） */
    var type: String = "notify",
    /** 发件人（通知里就是包名） */
    var from: String = "",
    /** 应用名（中文名拿不到就退回包名，避免归档目录被标题拆散） */
    var app: String = "",
    /** 通知标题 */
    var title: String = "",
    /** 正文（含 NAT 属性行） */
    var content: String = ""
)
