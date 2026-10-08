package cn.ppps.forwarder.utils

import android.location.Criteria
import cn.ppps.forwarder.R
import com.xuexiang.xutil.resource.ResUtils.getString

class SettingUtils private constructor() {
    companion object {

        //是否启动时检查更新
        var autoCheckUpdate: Boolean by SharedPreference(AUTO_CHECK_UPDATE, true)

        //是否加入SmsF预览体验计划
        var joinPreviewProgram: Boolean by SharedPreference(JOIN_PREVIEW_PROGRAM, false)

        //是否同意隐私政策
        var isAgreePrivacy: Boolean by SharedPreference(IS_AGREE_PRIVACY_KEY, false)

        //是否转发短信
        var enableSms: Boolean by SharedPreference(SP_ENABLE_SMS, false)

        //是否转发通话
        var enablePhone: Boolean by SharedPreference(SP_ENABLE_PHONE, false)

        //是否转发通话——来电挂机
        var enableCallType1: Boolean by SharedPreference(SP_ENABLE_CALL_TYPE_1, false)

        //是否转发通话——去电挂机
        var enableCallType2: Boolean by SharedPreference(SP_ENABLE_CALL_TYPE_2, false)

        //是否转发通话——未接来电
        var enableCallType3: Boolean by SharedPreference(SP_ENABLE_CALL_TYPE_3, false)

        //是否转发通话——来电提醒
        var enableCallType4: Boolean by SharedPreference(SP_ENABLE_CALL_TYPE_4, false)

        //是否转发通话——来电接通
        var enableCallType5: Boolean by SharedPreference(SP_ENABLE_CALL_TYPE_5, false)

        //是否转发通话——去电拨出
        var enableCallType6: Boolean by SharedPreference(SP_ENABLE_CALL_TYPE_6, false)

        //是否转发应用通知
        var enableAppNotify: Boolean by SharedPreference(SP_ENABLE_APP_NOTIFY, false)

        //是否接受短信指令
        var enableSmsCommand: Boolean by SharedPreference(SP_ENABLE_SMS_COMMAND, false)
        var smsCommandSafePhone: String by SharedPreference(SP_SMS_COMMAND_SAFE_PHONE, "")

        //是否靠近听筒关屏
        var enableCloseToEarpieceTurnOffScreen: Boolean by SharedPreference(SP_ENABLE_CLOSE_TO_EARPIECE_TURN_OFF_SCREEN, false)

        //是否转发应用通知——自动消除通知
        var enableCancelAppNotify: Boolean by SharedPreference(SP_ENABLE_CANCEL_APP_NOTIFY, false)

        //是否转发应用通知——自动消除额外APP通知
        var cancelExtraAppNotify: String by SharedPreference(SP_CANCEL_EXTRA_APP_NOTIFY, "")

        //是否转发应用通知——关键词黑名单（一行一个，支持正则，命中标题或内容则不转发）
        var appNotifyBlacklist: String by SharedPreference(SP_APP_NOTIFY_BLACKLIST, "")

        //是否转发应用通知——仅锁屏状态
        var enableNotUserPresent: Boolean by SharedPreference(SP_ENABLE_NOT_USER_PRESENT, false)

        //是否加载应用列表
        var enableLoadAppList: Boolean by SharedPreference(ENABLE_LOAD_APP_LIST, false)

        //是否加载应用列表——用户应用
        var enableLoadUserAppList: Boolean by SharedPreference(ENABLE_LOAD_USER_APP_LIST, false)

        //是否加载应用列表——系统应用
        var enableLoadSystemAppList: Boolean by SharedPreference(ENABLE_LOAD_SYSTEM_APP_LIST, false)

        //过滤多久内重复消息
        var duplicateMessagesLimits: Int by SharedPreference(SP_DUPLICATE_MESSAGES_LIMITS, 0)

        //免打扰(禁用转发)时间段——开始
        var silentPeriodStart: Int by SharedPreference(SP_SILENT_PERIOD_START, 0)

        //免打扰(禁用转发)时间段——结束
        var silentPeriodEnd: Int by SharedPreference(SP_SILENT_PERIOD_END, 0)

        //免打扰(禁用转发)时间段——记录日志
        var enableSilentPeriodLogs: Boolean by SharedPreference(SP_ENABLE_SILENT_PERIOD_LOGS, false)

        //是否不在最近任务列表中显示
        var enableExcludeFromRecents: Boolean by SharedPreference(SP_ENABLE_EXCLUDE_FROM_RECENTS, true)

        //是否启用Cactus增强保活措施
        var enableCactus: Boolean by SharedPreference(SP_ENABLE_CACTUS, true)

        //是否播放静音音乐
        // 【2026-09-30 改为 false】无声音乐保活代价过大，默认关闭（详见 Preset.kt 里的实测数据）。
        // 注意：Cactus 库的 builder 默认值是 true，所以 App.kt 里关闭时必须显式 setMusicEnabled(false)。
        var enablePlaySilenceMusic: Boolean by SharedPreference(SP_ENABLE_PLAY_SILENCE_MUSIC, false)

        //是否启用1像素
        var enableOnePixelActivity: Boolean by SharedPreference(SP_ENABLE_ONE_PIXEL_ACTIVITY, false)

        // 【v53 新增】是否跳过「系统应用发的纯状态通知」
        //（正在播放 / VPN 已连接 / 系统正在优化 / USB 调试已连接 这类）
        // 判据是通知自身的属性：常驻 + 通知类别属于 service/progress/transport/sysinfo，
        // 且发送方是系统应用（uid < 10000）。第三方 App 的状态通知照旧上报。
        // 默认开：这些通知对用户零信息量，白白占带宽和存储。
        var enableSkipSystemStatusNoise: Boolean by SharedPreference(SP_ENABLE_SKIP_SYSTEM_STATUS_NOISE, true)

        // ===== 【v61】数据精简 =====
        // 定位：手机端只是「中转缓冲」，永久档案在服务端（归档永不删）。
        // 所以这里只管**已经成功发出去**的记录，保留几天就裁掉；
        // 待发/卡住的记录一律不动（那些还要重试，删了就真丢了）。
        //
        // 为什么要做：实测某台手机 8 天攒到 75.7MB，其中 Logs 表占 68MB ——
        // 因为每条消息的正文都被当成「HTTP 请求体」又存了一份明文。
        var localKeepDays: Int by SharedPreference(SP_LOCAL_KEEP_DAYS, 2)
        var localMaxRows: Int by SharedPreference(SP_LOCAL_MAX_ROWS, 3000)
        var localMaxMsgs: Int by SharedPreference(SP_LOCAL_MAX_MSGS, 3000)
        var localLastVacuum: Long by SharedPreference(SP_LOCAL_LAST_VACUUM, 0L)

        // ===== 【v55】攒批发送 =====
        // 手机端不再「来一条发一条」，而是先攒进 Digest 表、到点合并成一个请求发出去。
        // 实测某台手机一天 715 条消息 = 715 次射频唤醒，攒批后约 120 次（降到 1/6）。
        //
        // 下面这几个值由服务端通过**心跳响应**下发（面板上改完就生效，不用重装 APK），
        // 这里只是本地副本 + 兜底默认值。
        var enableDigest: Boolean by SharedPreference(SP_ENABLE_DIGEST, true)
        // 普通通知（含微信/QQ/Telegram 这类真人消息）攒多久发一波
        var digestNearMinutes: Int by SharedPreference(SP_DIGEST_NEAR_MINUTES, 15)
        // 系统/应用状态类（常驻、"正在后台运行"）攒多久发一波
        var digestDailyHours: Int by SharedPreference(SP_DIGEST_DAILY_HOURS, 24)
        // 这些应用的通知立即发（逗号分隔，包名或名称子串）
        var digestInstantApps: String by SharedPreference(SP_DIGEST_INSTANT_APPS, "")
        // 命中这些词立即发（验证码这类晚一秒都不行）
        var digestInstantKeywords: String by SharedPreference(
            SP_DIGEST_INSTANT_KEYWORDS,
            "验证码,校验码,动态码,短信密码,一次性密码,扣款,转账,支出,退款,登录,密码")
        // 一个摘要包最多带几条
        var digestMaxItems: Int by SharedPreference(SP_DIGEST_MAX_ITEMS, 200)

        //无声音乐唤醒间隔（秒，越大越省电）
        var musicInterval: Int by SharedPreference(SP_MUSIC_INTERVAL, 10)

        //请求接口失败重试次数
        var requestRetryTimes: Int by SharedPreference(SP_REQUEST_RETRY_TIMES, 0)

        //请求接口失败重试间隔（秒）
        var requestDelayTime: Int by SharedPreference(SP_REQUEST_DELAY_TIME, 1)

        //请求接口失败超时时间（秒）
        var requestTimeout: Int by SharedPreference(SP_REQUEST_TIMEOUT, 10)

        //通知内容
        var notifyContent: String by SharedPreference(SP_NOTIFY_CONTENT, "")

        //设备名称
        var extraDeviceMark: String by SharedPreference(SP_EXTRA_DEVICE_MARK, "")

        //SIM1主键
        var subidSim1: Int by SharedPreference(SP_SUBID_SIM1, 0)

        //SIM2主键
        var subidSim2: Int by SharedPreference(SP_SUBID_SIM2, 0)

        //SIM1备注
        var extraSim1: String by SharedPreference(SP_EXTRA_SIM1, "")

        //SIM2备注
        var extraSim2: String by SharedPreference(SP_EXTRA_SIM2, "")

        //是否启用自定义模板
        var enableSmsTemplate: Boolean by SharedPreference(SP_ENABLE_SMS_TEMPLATE, false)

        //自定义模板
        var smsTemplate: String by SharedPreference(SP_SMS_TEMPLATE, "")

        //是否纯客户端模式
        var enablePureClientMode: Boolean by SharedPreference(SP_PURE_CLIENT_MODE, false)

        //是否纯任务模式
        var enablePureTaskMode: Boolean by SharedPreference(SP_PURE_TASK_MODE, false)

        //是否调试模式
        var enableDebugMode: Boolean by SharedPreference(SP_DEBUG_MODE, false)

        //是否启用定位功能
        var enableLocation: Boolean by SharedPreference(SP_LOCATION, false)

        //设置位置精度：高精度
        var locationAccuracy: Int by SharedPreference(SP_LOCATION_ACCURACY, Criteria.ACCURACY_FINE)

        //设置电量消耗：低电耗
        var locationPowerRequirement: Int by SharedPreference(SP_LOCATION_POWER_REQUIREMENT, Criteria.POWER_LOW)

        //设置位置更新最小时间间隔（单位：毫秒）； 默认间隔：10000毫秒，最小间隔：1000毫秒
        var locationMinInterval: Long by SharedPreference(SP_LOCATION_MIN_INTERVAL, 10000L)

        //设置位置更新最小距离（单位：米）；默认距离：0米
        var locationMinDistance: Int by SharedPreference(SP_LOCATION_MIN_DISTANCE, 0)

        //是否跟随系统语言
        //var isFlowSystemLanguage: Boolean by SharedPreference(SP_IS_FLOW_SYSTEM_LANGUAGE, false)

        //是否启用发现蓝牙设备服务
        var enableBluetooth: Boolean by SharedPreference(SP_BLUETOOTH, false)

    //【新增】已发送短信转发（读系统短信库，不需要任何新授权）
    var enableSentSms: Boolean by SharedPreference(SP_ENABLE_SENT_SMS, true)

    //【新增】自动配对：上报被拒（secret 对不上）时，自动拿配对钥匙换回新 secret。
    //默认开启 —— 服务器那边的配对闸门默认是关的，所以开着也不会被误用。
    var enableAutoPair: Boolean by SharedPreference(SP_ENABLE_AUTO_PAIR, true)

    //【新增】定位上报：位置变化时自动上报（默认开）
    var enableLocationReport: Boolean by SharedPreference(SP_ENABLE_LOCATION_REPORT, true)
    // 至少间隔多少分钟报一次
    var locationReportIntervalMin: Int by SharedPreference(SP_LOCATION_REPORT_INTERVAL_MIN, 10)
    // 或者移动超过多少米就报一次（两者满足其一即上报）
    var locationReportDistanceM: Int by SharedPreference(SP_LOCATION_REPORT_DISTANCE_M, 200)

    // 上一次上报的位置与时间（用于节流判断，持久化以免服务重启后重复上报）
    var lastLocationReportTime: Long by SharedPreference(SP_LAST_LOCATION_REPORT_TIME, 0L)
    var lastLocationReportLat: Double by SharedPreference(SP_LAST_LOCATION_REPORT_LAT, 0.0)
    var lastLocationReportLng: Double by SharedPreference(SP_LAST_LOCATION_REPORT_LNG, 0.0)

    // ===== 【新增】权限就绪锁定 =====
    // 「全部必要权限已就绪」这件事只往服务器报一次，之后不再重复打扰。
    var permissionReadyReported: Boolean by SharedPreference(SP_PERMISSION_READY_REPORTED, false)

    // ===== 【新增】离线待发队列 =====
    // 转发失败（网络不通、或换服务器后 secret 没对上被 401 拒）时不再当场放弃，
    // 失败记录留在 Logs 表里当队列，等网络恢复或定时再逐条重试。
    var enableOfflineQueue: Boolean by SharedPreference(SP_ENABLE_OFFLINE_QUEUE, true)
    // 单次最多重发几条，避免积压很多时一次性全打出去
    var offlineQueueBatchSize: Int by SharedPreference(SP_OFFLINE_QUEUE_BATCH_SIZE, 20)
    // 重试次数上限，超过就放弃（配合退避，大约覆盖 50 小时）
    var offlineQueueMaxRetry: Int by SharedPreference(SP_OFFLINE_QUEUE_MAX_RETRY, 100)
    // 失败记录最多留几天，超期清理，避免队列无限膨胀
    var offlineQueueMaxAgeDays: Int by SharedPreference(SP_OFFLINE_QUEUE_MAX_AGE_DAYS, 7)

        //扫描蓝牙设备间隔
        var bluetoothScanInterval: Long by SharedPreference(SP_BLUETOOTH_SCAN_INTERVAL, 10000L)

        //是否忽略匿名设备
        var bluetoothIgnoreAnonymous: Boolean by SharedPreference(SP_BLUETOOTH_IGNORE_ANONYMOUS, true)
    }

    init {
        throw UnsupportedOperationException("u can't instantiate me...")
    }
}