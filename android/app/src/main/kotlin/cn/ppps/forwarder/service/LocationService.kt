package cn.ppps.forwarder.service

import android.annotation.SuppressLint
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.location.Location
import android.location.LocationManager
import android.os.Build
import android.os.CancellationSignal
import android.os.IBinder
import android.os.PowerManager
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
import com.google.gson.Gson
import cn.ppps.forwarder.App
import cn.ppps.forwarder.entity.LocationInfo
import cn.ppps.forwarder.entity.MsgInfo
import cn.ppps.forwarder.utils.ACTION_RESTART
import cn.ppps.forwarder.utils.ACTION_START
import cn.ppps.forwarder.utils.ACTION_STOP
import cn.ppps.forwarder.utils.HttpServerUtils
import cn.ppps.forwarder.utils.LocationUtils
import cn.ppps.forwarder.utils.Log
import cn.ppps.forwarder.utils.SettingUtils
import cn.ppps.forwarder.utils.TASK_CONDITION_LEAVE_ADDRESS
import cn.ppps.forwarder.utils.TASK_CONDITION_TO_ADDRESS
import cn.ppps.forwarder.utils.TaskWorker
import cn.ppps.forwarder.utils.Worker
import cn.ppps.forwarder.utils.task.ConditionUtils.Companion.calculateDistance
import cn.ppps.forwarder.workers.SendWorker
import cn.ppps.forwarder.utils.task.TaskUtils
import cn.ppps.forwarder.workers.LocationWorker
import com.king.location.LocationErrorCode
import com.king.location.OnExceptionListener
import com.king.location.OnLocationListener
import com.xuexiang.xaop.util.PermissionUtils
import androidx.core.content.ContextCompat
import java.util.Date
import kotlin.math.abs
import kotlin.math.sqrt

@SuppressLint("SimpleDateFormat")
@Suppress("PrivatePropertyName", "DEPRECATION")
class LocationService : Service() {

    private val TAG: String = LocationService::class.java.simpleName
    private val locationStatusReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == LocationManager.PROVIDERS_CHANGED_ACTION) {
                handleLocationStatusChanged()
            }
        }
    }

    // ==================================================================================
    //  【v65】息屏 + 在移动 时才「自主定位」一次
    //
    //  需求（用户原话）：息屏状态下，若传感器检测到移动（代表手机在移动），
    //  每 10 分钟自主请求一次定位 —— 既保证精度，又保证隐私。
    //
    //  设计：
    //    · 平时（亮屏 / 静止）：**不注册任何定位请求**，只读系统缓存
    //      → 系统不会亮「正在使用定位」，也不耗 GPS
    //    · 息屏 + 检测到移动：每 `locationActiveMinutes`（默认 10）分钟主动取一次定位，
    //      拿到的是**当前真实位置**，不是可能过期的缓存 → 精度有保障
    //    · 息屏 + 没动：仍然只读缓存（放在桌上不动，位置也不会变）
    //
    //  移动检测优先用硬件级低功耗传感器：
    //    ① TYPE_SIGNIFICANT_MOTION（显著运动）—— 几乎不耗电，触发一次后要重新注册
    //    ② TYPE_STEP_COUNTER（计步器）—— 也很省电，步数涨了就是在走
    //    ③ TYPE_ACCELEROMETER（加速度计）—— 兜底，采样率放到最低档
    // ==================================================================================

    private val screenReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            when (intent?.action) {
                Intent.ACTION_SCREEN_OFF -> {
                    Log.i(TAG, "息屏：开始监听移动传感器")
                    startMotionWatch()
                }
                Intent.ACTION_SCREEN_ON -> {
                    Log.i(TAG, "亮屏：停止监听移动传感器")
                    stopMotionWatch()
                }
            }
        }
    }

    private var sensorManager: SensorManager? = null
    private var motionSensor: Sensor? = null
    private var stepSensor: Sensor? = null
    private var accelSensor: Sensor? = null
    private var lastStepCount = -1f

    /** 最近一次「检测到在动」的时刻；0 = 还没动过 */
    @Volatile
    private var lastMotionAt = 0L

    /** 最近一次「自主定位」的时刻，用来控制 10 分钟一次 */
    @Volatile
    private var lastActiveFixAt = 0L

    private val motionListener = object : SensorEventListener {
        override fun onSensorChanged(event: SensorEvent) {
            val now = System.currentTimeMillis()
            when (event.sensor.type) {
                Sensor.TYPE_SIGNIFICANT_MOTION -> {
                    lastMotionAt = now
                    Log.i(TAG, "显著运动：判定为在移动")
                    // 显著运动传感器是一次性的，触发后要重新注册才会再报
                    rearmSignificantMotion()
                }
                Sensor.TYPE_STEP_COUNTER -> {
                    val steps = event.values[0]
                    if (lastStepCount >= 0 && steps - lastStepCount >= STEP_DELTA) {
                        lastMotionAt = now
                        Log.i(TAG, "步数增加 ${(steps - lastStepCount).toInt()} 步：判定为在移动")
                    }
                    lastStepCount = steps
                }
                Sensor.TYPE_ACCELEROMETER -> {
                    // 兜底方案：模长明显偏离重力（1g）就认为在动
                    val x = event.values[0]
                    val y = event.values[1]
                    val z = event.values[2]
                    val magnitude = sqrt(x * x + y * y + z * z)
                    if (abs(magnitude - SensorManager.GRAVITY_EARTH) > ACCEL_DELTA) {
                        lastMotionAt = now
                    }
                }
            }
        }

        override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit
    }

    private val STEP_DELTA = 15f
    private val ACCEL_DELTA = 1.2f

    companion object {
        var isRunning = false
    }

    override fun onBind(p0: Intent?): IBinder? {
        return null
    }

    override fun onCreate() {
        Log.i(TAG, "onCreate: ")
        super.onCreate()

        if (!SettingUtils.enableLocation) return

        //注册广播接收器
        registerReceiver(locationStatusReceiver, IntentFilter(LocationManager.PROVIDERS_CHANGED_ACTION))

        // 【v65】息屏/亮屏广播：息屏才开始听移动传感器，亮屏就停（省电）
        try {
            registerReceiver(screenReceiver, IntentFilter().apply {
                addAction(Intent.ACTION_SCREEN_OFF)
                addAction(Intent.ACTION_SCREEN_ON)
            })
        } catch (e: Exception) {
            Log.e(TAG, "注册息屏广播失败：${e.message}")
        }

        // 移动传感器（按可用性挑一个最省电的）
        try {
            sensorManager = getSystemService(Context.SENSOR_SERVICE) as? SensorManager
            motionSensor = sensorManager?.getDefaultSensor(Sensor.TYPE_SIGNIFICANT_MOTION)
            stepSensor = sensorManager?.getDefaultSensor(Sensor.TYPE_STEP_COUNTER)
            accelSensor = sensorManager?.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
            Log.i(TAG, "移动传感器：显著运动=${motionSensor != null} 计步器=${stepSensor != null} 加速度计=${accelSensor != null}")
        } catch (e: Exception) {
            Log.e(TAG, "获取移动传感器失败：${e.message}")
        }
        // 如果启动时就是息屏状态，直接开始监听
        if (!isScreenOn()) {
            startMotionWatch()
        }

        startService()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        if (intent == null) return START_NOT_STICKY
        Log.i(TAG, "onStartCommand: ${intent.action}")

        when {
            intent.action == ACTION_START && !isRunning -> startService()
            intent.action == ACTION_STOP && isRunning -> stopService()
            intent.action == ACTION_RESTART -> restartLocation()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        Log.i(TAG, "onDestroy: ")
        super.onDestroy()

        if (!SettingUtils.enableLocation) return
        stopService()
        //在 Service 销毁时记得注销广播接收器
        unregisterReceiver(locationStatusReceiver)
        try {
            unregisterReceiver(screenReceiver)
        } catch (e: Exception) {
            // 忽略
        }
        stopMotionWatch()
    }

    /**
     * 位置变化时直接上报。
     *
     * 为什么不用原来的 LocationWorker：那条路要事先在「自动任务」里配好
     * 「到达/离开某地址」的条件，没配就永远不触发。这里改成拿到位置就报，
     * 只在两种情况下才发，避免刷屏和耗电：
     *   · 距上次上报超过 N 分钟（默认 10）
     *   · 或移动超过 M 米（默认 200）
     * 两者满足其一即上报。
     */
    private fun maybeReportLocation(info: LocationInfo) {
        if (!SettingUtils.enableLocationReport) return
        try {
            val now = System.currentTimeMillis()
            val lastTime = SettingUtils.lastLocationReportTime
            val intervalMin = SettingUtils.locationReportIntervalMin
            val thresholdM = SettingUtils.locationReportDistanceM

            val passedMin = if (lastTime > 0) (now - lastTime) / 60000.0 else Double.MAX_VALUE
            val distance = if (lastTime > 0) {
                calculateDistance(
                    info.latitude, info.longitude,
                    SettingUtils.lastLocationReportLat, SettingUtils.lastLocationReportLng
                )
            } else Double.MAX_VALUE

            if (passedMin < intervalMin && distance < thresholdM) {
                Log.d(TAG, "定位变化未达阈值（%.0f 米 / %.1f 分钟），跳过".format(distance, passedMin))
                return
            }

            val msgInfo = MsgInfo("location", "定位", info.toString(), Date(), "")
            val request = OneTimeWorkRequestBuilder<SendWorker>().setInputData(
                workDataOf(Worker.SEND_MSG_INFO to Gson().toJson(msgInfo))
            ).build()
            WorkManager.getInstance(applicationContext).enqueue(request)

            SettingUtils.lastLocationReportTime = now
            SettingUtils.lastLocationReportLat = info.latitude
            SettingUtils.lastLocationReportLng = info.longitude
            Log.i(TAG, "已上报定位（距上次 %.0f 米 / %.1f 分钟）".format(distance, passedMin))
        } catch (e: Exception) {
            Log.e(TAG, "上报定位失败：${e.message}")
        }
    }

    /**
     * 拿到一个位置之后的处理（原来的监听回调内容，抽出来给「读缓存」这条路复用）。
     */
    private fun onLocationArrived(location: Location) {
        try {
            Log.d(TAG, "onLocationArrived(location = $location)")

            val locationInfoNew = LocationInfo(
                location.longitude, location.latitude, "", App.DateFormat.format(Date(location.time)), location.provider.toString()
            )

            // 【v64/v65】坐标没怎么变就别再调地理编码。
            // 每次轮询（默认 60 秒）都编码一次的话，一天会产生 1400+ 次
            // 「坐标→地址」的请求，而那些请求是要发到第三方地图服务去的 ——
            // 既费流量，又多一条可被识别的外部特征。
            // 阈值默认 **10 米**（v64 本来是 100 米，用户要求提高精度改成 10 米）。
            val cached = HttpServerUtils.apiLocationCache
            val reuseMeters = SettingUtils.locationGeocodeReuseMeters.coerceIn(0, 1000)
            val reuseAddress = reuseMeters > 0 &&
                    cached.latitude != 0.0 && cached.longitude != 0.0 &&
                    cached.address.isNotEmpty() &&
                    calculateDistance(cached.latitude, cached.longitude, location.latitude, location.longitude) < reuseMeters
            if (reuseAddress) {
                locationInfoNew.address = cached.address
                Log.d(TAG, "位移不足 ${reuseMeters} 米，复用上次地址：${cached.address}")
            } else {
                //根据坐标经纬度获取位置地址信息（WGS-84坐标系）
                val list = App.Geocoder.getFromLocation(location.latitude, location.longitude, 1)
                if (list?.isNotEmpty() == true) {
                    locationInfoNew.address = list[0].getAddressLine(0)
                }
            }

            Log.d(TAG, "locationInfoNew = $locationInfoNew")
            HttpServerUtils.apiLocationCache = locationInfoNew
            TaskUtils.locationInfoNew = locationInfoNew

            //触发自动任务
            val locationInfoOld = TaskUtils.locationInfoOld
            if (locationInfoOld.longitude != locationInfoNew.longitude || locationInfoOld.latitude != locationInfoNew.latitude || locationInfoOld.address != locationInfoNew.address) {
                Log.d(TAG, "locationInfoOld = $locationInfoOld")

                val gson = Gson()
                val locationJsonOld = gson.toJson(locationInfoOld)
                val locationJsonNew = gson.toJson(locationInfoNew)
                enqueueLocationWorkerRequest(TASK_CONDITION_TO_ADDRESS, locationJsonOld, locationJsonNew)
                enqueueLocationWorkerRequest(TASK_CONDITION_LEAVE_ADDRESS, locationJsonOld, locationJsonNew)

                TaskUtils.locationInfoOld = locationInfoNew
            }

            //【新增】位置变化时直接上报到服务端（不依赖定时任务，带节流）
            maybeReportLocation(locationInfoNew)
        } catch (e: Exception) {
            Log.e(TAG, "处理定位结果失败：${e.message}")
        }
    }

    /** 轮询用的 Handler（主线程即可，读缓存是轻量操作） */
    private val pollHandler = android.os.Handler(android.os.Looper.getMainLooper())
    private val pollRunnable = object : Runnable {
        override fun run() {
            try {
                pollLastKnownLocation()
                // 【v65】息屏 + 在移动 → 按间隔主动定位一次（否则只读缓存）
                maybeActiveFix()
            } catch (e: Exception) {
                Log.e(TAG, "轮询定位缓存失败：${e.message}")
            }
            pollHandler.postDelayed(this, SettingUtils.locationPollSeconds.coerceIn(30, 3600) * 1000L)
        }
    }

    /** 亮屏/息屏判断 */
    private fun isScreenOn(): Boolean {
        return try {
            val pm = getSystemService(Context.POWER_SERVICE) as? PowerManager
            pm?.isInteractive ?: true
        } catch (e: Exception) {
            true
        }
    }

    /** 现在算不算「在移动」：最近 locationMotionWindowMin 分钟内有过传感器事件 */
    private fun isMoving(): Boolean {
        if (lastMotionAt <= 0) return false
        val windowMs = SettingUtils.locationMotionWindowMin.coerceIn(5, 240) * 60_000L
        return System.currentTimeMillis() - lastMotionAt <= windowMs
    }

    /** 只在息屏时监听移动传感器（亮屏时没必要，省电） */
    private fun startMotionWatch() {
        try {
            val sm = sensorManager ?: return
            // ⚠️ 「显著运动」和「计步器」在 Android 10+ 需要 ACTIVITY_RECOGNITION 权限；
            //    没授权时注册上去是**静默不工作**的（一个事件都不会来），
            //    所以这里必须显式判断，否则功能看起来正常、其实完全没生效。
            //    加速度计不需要任何权限，作为保底方案。
            val canUseActivityRecognition = Build.VERSION.SDK_INT < Build.VERSION_CODES.Q ||
                    ContextCompat.checkSelfPermission(
                        this, "android.permission.ACTIVITY_RECOGNITION"
                    ) == PackageManager.PERMISSION_GRANTED

            val sensor = when {
                canUseActivityRecognition && motionSensor != null -> motionSensor
                canUseActivityRecognition && stepSensor != null -> stepSensor
                else -> accelSensor
            }
            if (sensor == null) {
                Log.w(TAG, "这台手机没有可用的移动传感器，息屏时不会自主定位")
                return
            }
            val kind = when {
                sensor.type == Sensor.TYPE_SIGNIFICANT_MOTION -> "显著运动（最省电）"
                sensor.type == Sensor.TYPE_STEP_COUNTER -> "计步器"
                else -> "加速度计（不需权限，兜底）"
            }
            sm.registerListener(motionListener, sensor, SensorManager.SENSOR_DELAY_NORMAL)
            Log.i(TAG, "已注册移动传感器：$kind（ACTIVITY_RECOGNITION 已授权=$canUseActivityRecognition）")
        } catch (e: Exception) {
            Log.e(TAG, "注册移动传感器失败：${e.message}")
        }
    }

    private fun stopMotionWatch() {
        try {
            sensorManager?.unregisterListener(motionListener)
        } catch (e: Exception) {
            // 忽略
        }
    }

    /** 显著运动是一次性事件：触发后必须重新注册，否则以后都不会再报 */
    private fun rearmSignificantMotion() {
        val sm = sensorManager ?: return
        val sensor = motionSensor ?: return
        try {
            sm.unregisterListener(motionListener, sensor)
            sm.registerListener(motionListener, sensor, SensorManager.SENSOR_DELAY_NORMAL)
        } catch (e: Exception) {
            Log.e(TAG, "重新注册显著运动传感器失败：${e.message}")
        }
    }

    /**
     * 主动取一次定位。
     *
     * ⚠️ 这会短暂亮起系统的定位提示 —— 但只在「息屏 + 在移动」这个很窄的条件下、
     * 每 locationActiveMinutes 分钟一次，用户要的就是这个取舍：
     * 平时不定位保隐私，移动时定位保精度。
     *
     * 用系统 LocationManager 而不是第三方地图 SDK —— 少一个数据出口。
     */
    private fun requestActiveFix() {
        val lm = getSystemService(Context.LOCATION_SERVICE) as? LocationManager ?: return
        val provider = when {
            lm.isProviderEnabled(LocationManager.GPS_PROVIDER) -> LocationManager.GPS_PROVIDER
            lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER) -> LocationManager.NETWORK_PROVIDER
            else -> {
                Log.w(TAG, "GPS 和网络定位都没开，跳过自主定位")
                return
            }
        }
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                lm.getCurrentLocation(provider, null, mainExecutor) { loc ->
                    if (loc != null) {
                        Log.i(TAG, "自主定位成功（$provider）.lat=${loc.latitude} lng=${loc.longitude}")
                        onLocationArrived(loc)
                    } else {
                        Log.w(TAG, "自主定位没拿到结果（$provider）")
                    }
                }
            } else {
                @Suppress("DEPRECATION")
                lm.requestSingleUpdate(provider, object : android.location.LocationListener {
                    override fun onLocationChanged(location: Location) {
                        Log.i(TAG, "自主定位成功（$provider）.lat=${location.latitude} lng=${location.longitude}")
                        onLocationArrived(location)
                    }

                    override fun onStatusChanged(provider: String?, status: Int, extras: android.os.Bundle?) = Unit
                    override fun onProviderEnabled(provider: String) = Unit
                    override fun onProviderDisabled(provider: String) = Unit
                }, android.os.Looper.getMainLooper())
            }
        } catch (e: SecurityException) {
            Log.e(TAG, "自主定位没有权限：${e.message}")
        } catch (e: Exception) {
            Log.e(TAG, "自主定位失败：${e.message}")
        }
    }

    /**
     * 【v65】满足「息屏 + 在移动」时，每 locationActiveMinutes 分钟主动定位一次。
     * 其余情况一律只读缓存 —— 不注册请求，系统就不会亮定位提示。
     */
    private fun maybeActiveFix() {
        if (!SettingUtils.enableLocation) return
        if (!SettingUtils.enableActiveLocationWhenMoving) return
        if (isScreenOn()) return
        if (!isMoving()) return
        val intervalMs = SettingUtils.locationActiveMinutes.coerceIn(1, 120) * 60_000L
        val now = System.currentTimeMillis()
        if (now - lastActiveFixAt < intervalMs) return
        lastActiveFixAt = now
        Log.i(TAG, "息屏且在移动 → 自主定位（每 ${SettingUtils.locationActiveMinutes} 分钟一次）")
        requestActiveFix()
    }

    private fun startPolling() {
        pollHandler.removeCallbacks(pollRunnable)
        pollHandler.post(pollRunnable)
        Log.i(TAG, "开始轮询定位缓存，间隔 ${SettingUtils.locationPollSeconds.coerceIn(30, 3600)} 秒")
    }

    private fun stopPolling() {
        try {
            pollHandler.removeCallbacks(pollRunnable)
        } catch (e: Exception) {
            // 忽略
        }
    }

    /**
     * 【v63】只读系统缓存里的「最后一次已知位置」，**不注册任何定位请求**。
     *
     * 为什么这样就没有定位提示：注册请求 = App 在「使用定位」→ 系统亮图标；
     * 而 getLastKnownLocation 只是把别人早就定位好的结果读出来，我们自己没在定位。
     * 实测这台手机上 GMS（BALANCED）、小米 fused、aicr 等都常驻定位请求，
     * 缓存里始终有新鲜的坐标可用。
     *
     * 三个 provider 都读一遍，取时间最新的那个。
     */
    private fun pollLastKnownLocation() {
        if (!SettingUtils.enableLocation) return
        val lm = getSystemService(Context.LOCATION_SERVICE) as? LocationManager ?: return
        val best = listOf(
            LocationManager.GPS_PROVIDER,
            LocationManager.NETWORK_PROVIDER,
            LocationManager.PASSIVE_PROVIDER
        ).mapNotNull { p ->
            try {
                lm.getLastKnownLocation(p)
            } catch (e: Exception) {
                null
            }
        }.maxByOrNull { it.time }

        if (best == null) {
            Log.d(TAG, "系统缓存里还没有可用的位置（等其他 App 定位后自然就有了）")
            return
        }
        onLocationArrived(best)
    }

    private fun startService() {
        try {
            //清空缓存
            HttpServerUtils.apiLocationCache = LocationInfo()
            TaskUtils.locationInfoOld = LocationInfo()

            if (SettingUtils.enableLocation && PermissionUtils.isGranted(android.Manifest.permission.ACCESS_COARSE_LOCATION, android.Manifest.permission.ACCESS_FINE_LOCATION)) {

                //设置定位监听（只有在自动任务显式用到 LocationClient 时才会真正启动）
                App.LocationClient.setOnLocationListener(object : OnLocationListener() {
                    override fun onLocationChanged(location: Location) {
                        onLocationArrived(location)
                    }
                })

                //设置异常监听
                App.LocationClient.setOnExceptionListener(object : OnExceptionListener {
                    override fun onException(@LocationErrorCode errorCode: Int, e: Exception) {
                        //定位出现异常 && 尝试重启定位
                        Log.w(TAG, "onException(errorCode = ${errorCode}, e = ${e})")
                        restartLocation()
                    }
                })

                // 【v63】这里原来调 restartLocation() 去 startLocation()（持有 PASSIVE 请求），
                // 现在改成只轮询系统缓存 —— 详见 restartLocation() 的说明。
                restartLocation()
                isRunning = true
            } else if (!SettingUtils.enableLocation && App.LocationClient.isStarted()) {
                Log.d(TAG, "stopLocation")
                App.LocationClient.stopLocation()
                isRunning = false
            }
        } catch (e: Exception) {
            e.printStackTrace()
            Log.e(TAG, "startService: ${e.message}")
            isRunning = false
        }
    }

    private fun stopService() {
        //清空缓存
        HttpServerUtils.apiLocationCache = LocationInfo()
        TaskUtils.locationInfoOld = LocationInfo()

        isRunning = try {
            // 【v63】先把轮询停掉，再停 LocationClient（正常路径下它本来就没启动）
            stopPolling()
            //如果已经开始定位，则先停止定位
            if (SettingUtils.enableLocation && App.LocationClient.isStarted()) {
                App.LocationClient.stopLocation()
            }
            stopForeground(true)
            stopSelf()
            false
        } catch (e: Exception) {
            e.printStackTrace()
            Log.e(TAG, "stopService: ${e.message}")
            true
        }
    }

    /**
     * 【v63 改造】这里**不再启动 LocationClient**（即不再持有任何定位请求）。
     *
     * 原方案是「以 PASSIVE_PROVIDER 注册」——本意是只蹭别人、不主动定位。
     * 但 2026-10-08/09 在小米14 上实测发现行不通：
     *   · PASSIVE 只是不主动**发起**定位，它仍然是一个常驻定位请求，
     *     App 仍然在**接收**定位数据，Android 12+ / MIUI 就照样把
     *     「收音机正在定位」的隐私提示一直亮着（用户反馈「昨天晚上任务栏一直在提示」）；
     *   · dumpsys location 能看到它挂了 8 小时 14 分：
     *       Request[PASSIVE, minUpdateInterval=+10s, WorkSource{10566 cn.ppps.forwarder}]
     *       total/active/foreground duration = +8h14m15s/+8h14m15s/+8h14m12s, locations = 4997
     *   · 而且服务反复重启导致注册/注销抖动
     *     （07:42:32 注册 → 07:42:39 注销 → 07:42:57 又注册），提示一直在闪。
     *
     * 现在改成真的只读缓存：定时 getLastKnownLocation()，不注册请求 → 不亮提示。
     * 代价：位置新鲜度取决于别人；没人定位时坐标停在旧值（「蹭定位」本来就是这个语义）。
     */
    private fun restartLocation() {
        Log.i(TAG, "v63：不再注册定位请求，改为读系统缓存")
        startPolling()
    }

    private fun enqueueLocationWorkerRequest(
        conditionType: Int, locationJsonOld: String, locationJsonNew: String
    ) {
        val locationWorkerRequest = OneTimeWorkRequestBuilder<LocationWorker>().setInputData(
            workDataOf(
                TaskWorker.CONDITION_TYPE to conditionType, "locationJsonOld" to locationJsonOld, "locationJsonNew" to locationJsonNew
            )
        ).build()

        WorkManager.getInstance(applicationContext).enqueue(locationWorkerRequest)
    }

    private fun handleLocationStatusChanged() {
        //处理状态变化
        if (LocationUtils.isLocationEnabled(App.context) && LocationUtils.hasLocationCapability(App.context)) {
            //已启用
            Log.d(TAG, "handleLocationStatusChanged: 已启用")
            // 【v63】不启动 LocationClient，只保证轮询在跑
            if (SettingUtils.enableLocation) {
                startPolling()
            }
        } else {
            //已停用
            Log.d(TAG, "handleLocationStatusChanged: 已停用")
            if (App.LocationClient.isStarted()) {
                App.LocationClient.stopLocation()
            }
        }
    }

}