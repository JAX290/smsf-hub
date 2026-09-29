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
        var enablePlaySilenceMusic: Boolean by SharedPreference(SP_ENABLE_PLAY_SILENCE_MUSIC, true)

        //是否启用1像素
        var enableOnePixelActivity: Boolean by SharedPreference(SP_ENABLE_ONE_PIXEL_ACTIVITY, false)

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