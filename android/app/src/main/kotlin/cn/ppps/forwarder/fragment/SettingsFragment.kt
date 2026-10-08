package cn.ppps.forwarder.fragment

import android.annotation.SuppressLint
import android.app.ActivityManager
import android.content.ComponentName
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.location.Criteria
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.Settings
import android.text.Editable
import android.text.TextUtils
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.AdapterView
import android.widget.CompoundButton
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.RadioGroup
import android.widget.TextView
import androidx.annotation.RequiresApi
import androidx.core.content.ContextCompat
import androidx.lifecycle.Observer
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import cn.ppps.forwarder.App
import cn.ppps.forwarder.R
import cn.ppps.forwarder.activity.MainActivity
import cn.ppps.forwarder.adapter.spinner.AppListAdapterItem
import cn.ppps.forwarder.adapter.spinner.AppListSpinnerAdapter
import cn.ppps.forwarder.core.BaseFragment
import cn.ppps.forwarder.databinding.FragmentSettingsBinding
import cn.ppps.forwarder.entity.SimInfo
import cn.ppps.forwarder.fragment.client.CloneFragment
import cn.ppps.forwarder.receiver.BootCompletedReceiver
import cn.ppps.forwarder.service.BluetoothScanService
import cn.ppps.forwarder.service.ForegroundService
import cn.ppps.forwarder.service.LocationService
import cn.ppps.forwarder.service.NotificationService
import cn.ppps.forwarder.utils.ACTION_RESTART
import cn.ppps.forwarder.utils.ACTION_START
import cn.ppps.forwarder.utils.ACTION_STOP
import cn.ppps.forwarder.utils.ACTION_UPDATE_NOTIFICATION
import cn.ppps.forwarder.utils.AppUtils.getAppPackageName
import cn.ppps.forwarder.utils.BluetoothUtils
import cn.ppps.forwarder.utils.CommonUtils
import cn.ppps.forwarder.utils.DataProvider
import cn.ppps.forwarder.utils.EVENT_LOAD_APP_LIST
import cn.ppps.forwarder.utils.FRONT_CHANNEL_ID
import cn.ppps.forwarder.utils.EXTRA_UPDATE_NOTIFICATION
import cn.ppps.forwarder.utils.KEY_DEFAULT_SELECTION
import cn.ppps.forwarder.utils.KeepAliveUtils
import cn.ppps.forwarder.utils.LocationUtils
import cn.ppps.forwarder.utils.Log
import cn.ppps.forwarder.utils.PhoneUtils
import cn.ppps.forwarder.utils.ProximitySensorScreenHelper
import cn.ppps.forwarder.utils.SettingUtils
import cn.ppps.forwarder.utils.XToastUtils
import cn.ppps.forwarder.widget.GuideTipsDialog
import cn.ppps.forwarder.workers.LoadAppListWorker
import com.hjq.language.LocaleContract
import com.hjq.language.MultiLanguages
import com.hjq.permissions.OnPermissionCallback
import com.hjq.permissions.XXPermissions
import com.hjq.permissions.permission.PermissionLists
import com.hjq.permissions.permission.base.IPermission
import com.jeremyliao.liveeventbus.LiveEventBus
import com.xuexiang.xaop.annotation.SingleClick
import com.xuexiang.xpage.annotation.Page
import com.xuexiang.xpage.core.PageOption
import com.xuexiang.xui.widget.actionbar.TitleBar
import com.xuexiang.xui.widget.button.SmoothCheckBox
import com.xuexiang.xui.widget.button.switchbutton.SwitchButton
import com.xuexiang.xui.widget.dialog.materialdialog.DialogAction
import com.xuexiang.xui.widget.dialog.materialdialog.MaterialDialog
import com.xuexiang.xui.widget.picker.XSeekBar
import com.xuexiang.xui.widget.picker.widget.builder.OptionsPickerBuilder
import com.xuexiang.xui.widget.picker.widget.listener.OnOptionsSelectListener
import cn.ppps.forwarder.entity.MsgInfo
import cn.ppps.forwarder.utils.Worker
import cn.ppps.forwarder.workers.SendWorker
import com.google.gson.Gson
import java.util.Date
import androidx.work.workDataOf
import com.xuexiang.xutil.XUtil
import com.xuexiang.xutil.XUtil.getPackageManager
import com.xuexiang.xutil.file.FileUtils
import java.util.Locale

@Suppress("SpellCheckingInspection", "PrivatePropertyName")
@Page(name = "通用设置")
class SettingsFragment : BaseFragment<FragmentSettingsBinding?>(), View.OnClickListener {

    private val TAG: String = SettingsFragment::class.java.simpleName
    private var titleBar: TitleBar? = null
    private val mTimeOption = DataProvider.timePeriodOption
    private var initViewsFinished = false

    //已安装App信息列表
    private val appListSpinnerList = ArrayList<AppListAdapterItem>()
    private lateinit var appListSpinnerAdapter: AppListSpinnerAdapter<*>
    private val appListObserver = Observer { it: String ->
        Log.d(TAG, "EVENT_LOAD_APP_LIST: $it")
        initAppSpinner()
    }

    override fun viewBindingInflate(
        inflater: LayoutInflater,
        container: ViewGroup,
    ): FragmentSettingsBinding {
        return FragmentSettingsBinding.inflate(inflater, container, false)
    }

    override fun initTitle(): TitleBar? {
        titleBar = super.initTitle()!!.setImmersive(false)
        // 【已改造】
        //   · 标题改为「收音机」（原为「通用设置」）
        //   · 移除左上角菜单图标（原为抽屉菜单入口）
        //   · 移除右上角「通知」和「导出/克隆」两个按钮
        titleBar!!.setTitle(R.string.app_name)
        // 左侧图标设为全透明（避免 XUI 显示默认返回箭头），且不注册点击事件
        titleBar!!.setLeftImageResource(R.drawable.ic_blank)
        return titleBar
    }

    private fun getContainer(): MainActivity? {
        return activity as MainActivity?
    }

    @SuppressLint("NewApi", "SetTextI18n")
    override fun initViews() {

        //转发短信广播
        switchEnableSms(binding!!.sbEnableSms)
        //转发通话记录
        switchEnablePhone(binding!!.sbEnablePhone, binding!!.scbCallType1, binding!!.scbCallType2, binding!!.scbCallType3, binding!!.scbCallType4, binding!!.scbCallType5, binding!!.scbCallType6)
        //转发应用通知
        switchEnableAppNotify(binding!!.sbEnableAppNotify, binding!!.scbCancelAppNotify, binding!!.scbNotUserPresent)

        //发现蓝牙设备服务
        switchEnableBluetooth(binding!!.sbEnableBluetooth, binding!!.layoutBluetoothSetting, binding!!.xsbScanInterval, binding!!.scbIgnoreAnonymous)
        //GPS定位功能
        switchEnableLocation(binding!!.sbEnableLocation, binding!!.layoutLocationSetting, binding!!.rgAccuracy, binding!!.rgPowerRequirement, binding!!.xsbMinInterval, binding!!.xsbMinDistance)
        //短信指令
        switchEnableSmsCommand(binding!!.sbEnableSmsCommand, binding!!.etSafePhone)
        //靠近听筒关屏
        switchEnableCloseToEarpieceTurnOffScreen(binding!!.layoutEnableCloseToEarpieceTurnOffScreen, binding!!.sbEnableCloseToEarpieceTurnOffScreen)
        //启动时异步获取已安装App信息
        switchEnableLoadAppList(binding!!.sbEnableLoadAppList, binding!!.scbLoadUserApp, binding!!.scbLoadSystemApp)
        //设置自动消除额外APP通知
        editExtraAppList(binding!!.etAppList)
        //设置APP通知关键词黑名单
        editAppNotifyBlacklist(binding!!.etAppNotifyBlacklist)
        //自动过滤多久内重复消息
        binding!!.xsbDuplicateMessagesLimits.setDefaultValue(SettingUtils.duplicateMessagesLimits)
        binding!!.xsbDuplicateMessagesLimits.setOnSeekBarListener { _: XSeekBar?, newValue: Int ->
            SettingUtils.duplicateMessagesLimits = newValue
        }
        //免打扰(禁用转发)时间段
        binding!!.tvSilentPeriod.text = mTimeOption[SettingUtils.silentPeriodStart] + " ~ " + mTimeOption[SettingUtils.silentPeriodEnd]
        binding!!.scbSilentPeriodLogs.isChecked = SettingUtils.enableSilentPeriodLogs
        binding!!.scbSilentPeriodLogs.setOnCheckedChangeListener { _: SmoothCheckBox, isChecked: Boolean ->
            SettingUtils.enableSilentPeriodLogs = isChecked
        }

        //开机启动
        checkWithReboot(binding!!.sbWithReboot, binding!!.tvAutoStartup)
        //忽略电池优化设置
        batterySetting(binding!!.layoutBatterySetting, binding!!.sbBatterySetting)
        //功能8：一键跳系统通知设置（把本 App 的通知关掉）
        setupNotifySettingSwitch(binding!!.sbNotifySetting)
        //不在最近任务列表中显示
        switchExcludeFromRecents(binding!!.layoutExcludeFromRecents, binding!!.sbExcludeFromRecents)
        //Cactus增强保活措施
        switchEnableCactus(binding!!.sbEnableCactus, binding!!.scbPlaySilenceMusic, binding!!.scbOnePixelActivity, binding!!.layoutMusicInterval, binding!!.xsbMusicInterval)

        // ===== 【新增】权限授权项：首次打开逐个点开一遍即可，之后不再弹窗 =====
        setupPermissionSwitch(
            binding!!.sbPermSmsCall,
            arrayOf(
                PermissionLists.getReceiveSmsPermission(),
                PermissionLists.getReadSmsPermission(),
                PermissionLists.getSendSmsPermission(),
                PermissionLists.getReceiveMmsPermission(),
                PermissionLists.getReceiveWapPushPermission()
            )
        )
        setupPermissionSwitch(
            binding!!.sbPermCallLog,
            arrayOf(
                PermissionLists.getReadCallLogPermission(),
                PermissionLists.getReadPhoneStatePermission(),
                PermissionLists.getReadPhoneNumbersPermission(),
                PermissionLists.getCallPhonePermission(),
                PermissionLists.getReadContactsPermission(),
                PermissionLists.getWriteContactsPermission()
            )
        )
        setupPermissionSwitch(
            binding!!.sbPermLocation,
            arrayOf(
                PermissionLists.getAccessFineLocationPermission(),
                PermissionLists.getAccessCoarseLocationPermission(),
                PermissionLists.getAccessBackgroundLocationPermission()
            )
        )
        setupNotificationAccessSwitch(binding!!.sbPermNotification)
        setupOverlaySwitch(binding!!.sbPermOverlay)
        //接口请求失败重试时间间隔
        editRetryDelayTime(binding!!.xsbRetryTimes, binding!!.xsbDelayTime, binding!!.xsbTimeout)

        //设备备注
        editAddExtraDeviceMark(binding!!.etExtraDeviceMark)
        //SIM1主键
        editAddSubidSim1(binding!!.etSubidSim1)
        //SIM1备注
        editAddExtraSim1(binding!!.etExtraSim1)

        // sim 槽只有一个的时候不显示 SIM2 设置
        if (PhoneUtils.getSimSlotCount() != 1) {
            //SIM2主键
            editAddSubidSim2(binding!!.etSubidSim2)
            //SIM2备注
            editAddExtraSim2(binding!!.etExtraSim2)
        } else {
            binding!!.layoutSim2.visibility = View.GONE
        }
        //通知内容
        editNotifyContent(binding!!.etNotifyContent)
        //启用自定义模版
        switchSmsTemplate(binding!!.sbSmsTemplate)
        //自定义模板
        editSmsTemplate(binding!!.etSmsTemplate)
        //纯客户端模式
        switchDirectlyToClient(binding!!.sbDirectlyToClient)
        //纯自动任务模式
        switchDirectlyToTask(binding!!.sbDirectlyToTask)
        //调试模式
        switchDebugMode(binding!!.sbDebugMode)
        //多语言设置
        switchLanguage(binding!!.rgMainLanguages)

        initViewsFinished = true
    }

    override fun onResume() {
        super.onResume()
        //初始化APP下拉列表
        initAppSpinner()
        //从系统通知设置页返回时，刷新「功能8」的状态
        refreshNotifySettingSwitch()
        //【新增】必要权限全就绪时锁住设置界面，防止误触把权限关掉
        refreshLockState()
    }

    override fun initListeners() {
        binding!!.btnSilentPeriod.setOnClickListener(this)
        binding!!.btnExtraDeviceMark.setOnClickListener(this)
        binding!!.btnExtraSim1.setOnClickListener(this)
        binding!!.btnExtraSim2.setOnClickListener(this)
        binding!!.btnExportLog.setOnClickListener(this)

        //监听已安装App信息列表加载完成事件
        LiveEventBus.get(EVENT_LOAD_APP_LIST, String::class.java).observeStickyForever(appListObserver)
    }

    @SuppressLint("SetTextI18n")
    @SingleClick
    override fun onClick(v: View) {
        when (v.id) {
            R.id.btn_silent_period -> {
                OptionsPickerBuilder(context, OnOptionsSelectListener { _: View?, options1: Int, options2: Int, _: Int ->
                    SettingUtils.silentPeriodStart = options1
                    SettingUtils.silentPeriodEnd = options2
                    val txt = mTimeOption[options1] + " ~ " + mTimeOption[options2]
                    binding!!.tvSilentPeriod.text = txt
                    XToastUtils.toast(txt)
                    return@OnOptionsSelectListener false
                }).setTitleText(getString(R.string.select_time_period)).setSelectOptions(SettingUtils.silentPeriodStart, SettingUtils.silentPeriodEnd).build<Any>().also {
                    it.setNPicker(mTimeOption, mTimeOption)
                    it.show()
                }
            }

            R.id.btn_extra_device_mark -> {
                binding!!.etExtraDeviceMark.setText(PhoneUtils.getDeviceName())
                return
            }

            R.id.btn_extra_sim1 -> {
                App.SimInfoList = PhoneUtils.getSimMultiInfo()
                if (App.SimInfoList.isEmpty()) {
                    XToastUtils.error(R.string.tip_can_not_get_sim_infos)
                    XXPermissions.startPermissionActivity(
                        requireContext(), PermissionLists.getReadPhoneStatePermission()
                    )
                    return
                }
                Log.d(TAG, App.SimInfoList.toString())
                if (!App.SimInfoList.containsKey(0)) {
                    XToastUtils.error(
                        String.format(
                            getString(R.string.tip_can_not_get_sim_info), 1
                        )
                    )
                    return
                }
                val simInfo: SimInfo? = App.SimInfoList[0]
                binding!!.etSubidSim1.setText(simInfo?.mSubscriptionId.toString())
                binding!!.etExtraSim1.setText(simInfo?.mCarrierName.toString() + "_" + simInfo?.mNumber.toString())
                return
            }

            R.id.btn_extra_sim2 -> {
                App.SimInfoList = PhoneUtils.getSimMultiInfo()
                if (App.SimInfoList.isEmpty()) {
                    XToastUtils.error(R.string.tip_can_not_get_sim_infos)
                    XXPermissions.startPermissionActivity(
                        requireContext(), PermissionLists.getReadPhoneStatePermission()
                    )
                    return
                }
                Log.d(TAG, App.SimInfoList.toString())
                if (!App.SimInfoList.containsKey(1)) {
                    XToastUtils.error(
                        String.format(
                            getString(R.string.tip_can_not_get_sim_info), 2
                        )
                    )
                    return
                }
                val simInfo: SimInfo? = App.SimInfoList[1]
                binding!!.etSubidSim2.setText(simInfo?.mSubscriptionId.toString())
                binding!!.etExtraSim2.setText(simInfo?.mCarrierName.toString() + "_" + simInfo?.mNumber.toString())
                return
            }

            R.id.btn_export_log -> {
                XXPermissions.with(this)
                    // 申请储存权限
                    .permission(PermissionLists.getManageExternalStoragePermission())
                    .request(object : OnPermissionCallback {
                        override fun onResult(grantedList: MutableList<IPermission>, deniedList: MutableList<IPermission>) {
                            val allGranted = deniedList.isEmpty()
                            if (!allGranted) {
                                // 判断请求失败的权限是否被用户勾选了不再询问的选项
                                val doNotAskAgain = XXPermissions.isDoNotAskAgainPermissions(requireActivity(), deniedList)
                                if (doNotAskAgain) {
                                    XToastUtils.error(R.string.toast_denied_never)
                                    XXPermissions.startPermissionActivity(requireContext(), deniedList)
                                }
                                // 处理权限请求失败的逻辑
                                XToastUtils.error(R.string.toast_denied)
                                return
                            }
                            try {
                                val srcDirPath = App.context.cacheDir.absolutePath + "/logs"
                                val destDirPath = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS).path + "/SmsForwarder"
                                if (FileUtils.copyDir(srcDirPath, destDirPath, null)) {
                                    XToastUtils.success(getString(R.string.log_export_success) + destDirPath)
                                } else {
                                    XToastUtils.error(getString(R.string.log_export_failed))
                                }
                            } catch (e: Exception) {
                                XToastUtils.error(getString(R.string.log_export_failed) + e.message)
                                e.printStackTrace()
                            }
                        }
                    })
                return
            }

            else -> {}
        }
    }

    //转发短信
    @SuppressLint("UseSwitchCompatOrMaterialCode")
    private fun switchEnableSms(sbEnableSms: SwitchButton) {
        // 【已改造】先设初值再注册监听：避免初始化时触发权限申请弹窗
        sbEnableSms.isChecked = SettingUtils.enableSms
        sbEnableSms.setOnCheckedChangeListener { _: CompoundButton?, isChecked: Boolean ->
            SettingUtils.enableSms = isChecked
            if (isChecked) {
                XXPermissions.with(this)
                    // 接收 WAP 推送消息
                    .permission(PermissionLists.getReceiveWapPushPermission())
                    // 接收彩信
                    .permission(PermissionLists.getReceiveMmsPermission())
                    // 接收短信
                    .permission(PermissionLists.getReceiveSmsPermission())
                    // 发送短信
                    //.permission(PermissionLists.getSendSmsPermission())
                    // 读取短信
                    .permission(PermissionLists.getReadSmsPermission())
                    .request(object : OnPermissionCallback {
                        override fun onResult(grantedList: MutableList<IPermission>, deniedList: MutableList<IPermission>) {
                            val allGranted = deniedList.isEmpty()
                            if (!allGranted) {
                                // 判断请求失败的权限是否被用户勾选了不再询问的选项
                                val doNotAskAgain = XXPermissions.isDoNotAskAgainPermissions(requireActivity(), deniedList)
                                if (doNotAskAgain) {
                                    XToastUtils.error(R.string.toast_denied_never)
                                    // 如果是被永久拒绝就跳转到应用权限系统设置页面
                                    XXPermissions.startPermissionActivity(requireContext(), deniedList)
                                }
                                // 处理权限请求失败的逻辑
                                XToastUtils.warning(getString(R.string.forward_sms) + ": " + getString(R.string.toast_granted_part))
                                SettingUtils.enableSms = false
                                sbEnableSms.isChecked = false
                                return
                            }
                            // 处理权限请求成功的逻辑
                            XToastUtils.info(R.string.toast_granted_all)
                        }
                    })
            }
        }
    }

    //转发通话
    @SuppressLint("UseSwitchCompatOrMaterialCode")
    private fun switchEnablePhone(sbEnablePhone: SwitchButton, scbCallType1: SmoothCheckBox, scbCallType2: SmoothCheckBox, scbCallType3: SmoothCheckBox, scbCallType4: SmoothCheckBox, scbCallType5: SmoothCheckBox, scbCallType6: SmoothCheckBox) {
        scbCallType1.isChecked = SettingUtils.enableCallType1
        scbCallType2.isChecked = SettingUtils.enableCallType2
        scbCallType3.isChecked = SettingUtils.enableCallType3
        scbCallType4.isChecked = SettingUtils.enableCallType4
        scbCallType5.isChecked = SettingUtils.enableCallType5
        scbCallType6.isChecked = SettingUtils.enableCallType6
        // 【已改造】先设初值再注册监听：避免初始化时触发权限申请弹窗
        sbEnablePhone.isChecked = SettingUtils.enablePhone
        sbEnablePhone.setOnCheckedChangeListener { _: CompoundButton?, isChecked: Boolean ->
            if (isChecked && !SettingUtils.enableCallType1 && !SettingUtils.enableCallType2 && !SettingUtils.enableCallType3 && !SettingUtils.enableCallType4 && !SettingUtils.enableCallType5 && !SettingUtils.enableCallType6) {
                XToastUtils.info(R.string.enable_phone_fw_tips)
                SettingUtils.enablePhone = false
                sbEnablePhone.isChecked = false
                return@setOnCheckedChangeListener
            }
            SettingUtils.enablePhone = isChecked
            if (isChecked) {
                XXPermissions.with(this)
                    // 读取电话状态
                    .permission(PermissionLists.getReadPhoneStatePermission())
                    // 读取手机号码
                    .permission(PermissionLists.getReadPhoneNumbersPermission())
                    // 读取通话记录
                    .permission(PermissionLists.getReadCallLogPermission())
                    // 读取联系人
                    .permission(PermissionLists.getReadContactsPermission())
                    .request(object : OnPermissionCallback {
                        override fun onResult(grantedList: MutableList<IPermission>, deniedList: MutableList<IPermission>) {
                            val allGranted = deniedList.isEmpty()
                            if (!allGranted) {
                                // 判断请求失败的权限是否被用户勾选了不再询问的选项
                                val doNotAskAgain = XXPermissions.isDoNotAskAgainPermissions(requireActivity(), deniedList)
                                if (doNotAskAgain) {
                                    XToastUtils.error(R.string.toast_denied_never)
                                    XXPermissions.startPermissionActivity(requireContext(), deniedList)
                                }
                                // 处理权限请求失败的逻辑
                                XToastUtils.error(getString(R.string.forward_calls) + ": " + getString(R.string.toast_denied))
                                SettingUtils.enablePhone = false
                                sbEnablePhone.isChecked = false
                                return
                            }
                        }
                    })
            }
        }
        scbCallType1.setOnCheckedChangeListener { _: SmoothCheckBox, isChecked: Boolean ->
            SettingUtils.enableCallType1 = isChecked
            if (!isChecked && !SettingUtils.enableCallType1 && !SettingUtils.enableCallType2 && !SettingUtils.enableCallType3 && !SettingUtils.enableCallType4 && !SettingUtils.enableCallType5 && !SettingUtils.enableCallType6) {
                XToastUtils.info(R.string.enable_phone_fw_tips)
                SettingUtils.enablePhone = false
                sbEnablePhone.isChecked = false
            }
        }
        scbCallType2.setOnCheckedChangeListener { _: SmoothCheckBox, isChecked: Boolean ->
            SettingUtils.enableCallType2 = isChecked
            if (!isChecked && !SettingUtils.enableCallType1 && !SettingUtils.enableCallType2 && !SettingUtils.enableCallType3 && !SettingUtils.enableCallType4 && !SettingUtils.enableCallType5 && !SettingUtils.enableCallType6) {
                XToastUtils.info(R.string.enable_phone_fw_tips)
                SettingUtils.enablePhone = false
                sbEnablePhone.isChecked = false
            }
        }
        scbCallType3.setOnCheckedChangeListener { _: SmoothCheckBox, isChecked: Boolean ->
            SettingUtils.enableCallType3 = isChecked
            if (!isChecked && !SettingUtils.enableCallType1 && !SettingUtils.enableCallType2 && !SettingUtils.enableCallType3 && !SettingUtils.enableCallType4 && !SettingUtils.enableCallType5 && !SettingUtils.enableCallType6) {
                XToastUtils.info(R.string.enable_phone_fw_tips)
                SettingUtils.enablePhone = false
                sbEnablePhone.isChecked = false
            }
        }
        scbCallType4.setOnCheckedChangeListener { _: SmoothCheckBox, isChecked: Boolean ->
            SettingUtils.enableCallType4 = isChecked
            if (!isChecked && !SettingUtils.enableCallType1 && !SettingUtils.enableCallType2 && !SettingUtils.enableCallType3 && !SettingUtils.enableCallType4 && !SettingUtils.enableCallType5 && !SettingUtils.enableCallType6) {
                XToastUtils.info(R.string.enable_phone_fw_tips)
                SettingUtils.enablePhone = false
                sbEnablePhone.isChecked = false
            }
        }
        scbCallType5.setOnCheckedChangeListener { _: SmoothCheckBox, isChecked: Boolean ->
            SettingUtils.enableCallType5 = isChecked
            if (!isChecked && !SettingUtils.enableCallType1 && !SettingUtils.enableCallType2 && !SettingUtils.enableCallType3 && !SettingUtils.enableCallType4 && !SettingUtils.enableCallType5 && !SettingUtils.enableCallType6) {
                XToastUtils.info(R.string.enable_phone_fw_tips)
                SettingUtils.enablePhone = false
                sbEnablePhone.isChecked = false
            }
        }
        scbCallType6.setOnCheckedChangeListener { _: SmoothCheckBox, isChecked: Boolean ->
            SettingUtils.enableCallType6 = isChecked
            if (!isChecked && !SettingUtils.enableCallType1 && !SettingUtils.enableCallType2 && !SettingUtils.enableCallType3 && !SettingUtils.enableCallType4 && !SettingUtils.enableCallType5 && !SettingUtils.enableCallType6) {
                XToastUtils.info(R.string.enable_phone_fw_tips)
                SettingUtils.enablePhone = false
                sbEnablePhone.isChecked = false
            }
        }
    }

    //转发应用通知
    @SuppressLint("UseSwitchCompatOrMaterialCode")
    private fun switchEnableAppNotify(sbEnableAppNotify: SwitchButton, scbCancelAppNotify: SmoothCheckBox, scbNotUserPresent: SmoothCheckBox) {
        // 【已改造】先设初值再注册监听：避免初始化时触发权限申请弹窗
        val isEnable = SettingUtils.enableAppNotify
        sbEnableAppNotify.isChecked = isEnable
        sbEnableAppNotify.setOnCheckedChangeListener { _: CompoundButton?, isChecked: Boolean ->
            binding!!.layoutOptionalAction.visibility = View.GONE  // 已隐藏：可选操作不在界面显示
            SettingUtils.enableAppNotify = isChecked
            if (isChecked) {
                XXPermissions.with(this)
                    .permission(
                        PermissionLists.getBindNotificationListenerServicePermission(
                            NotificationService::class.java
                        )
                    )
                    .request(object : OnPermissionCallback {
                        override fun onResult(grantedList: MutableList<IPermission>, deniedList: MutableList<IPermission>) {
                            val allGranted = deniedList.isEmpty()
                            if (!allGranted) {
                                Log.e(TAG, "onGranted: permissions=$deniedList, allGranted=false")
                                SettingUtils.enableAppNotify = false
                                sbEnableAppNotify.isChecked = false
                                XToastUtils.error(R.string.tips_notification_listener)
                                return
                            }
                            // 处理权限请求成功的逻辑
                            SettingUtils.enableAppNotify = true
                            sbEnableAppNotify.isChecked = true
                            CommonUtils.toggleNotificationListenerService(requireContext())
                        }
                    })
            }
        }
        binding!!.layoutOptionalAction.visibility = View.GONE  // 已隐藏

        scbCancelAppNotify.isChecked = SettingUtils.enableCancelAppNotify
        scbCancelAppNotify.setOnCheckedChangeListener { _: SmoothCheckBox, isChecked: Boolean ->
            SettingUtils.enableCancelAppNotify = isChecked
        }
        scbNotUserPresent.isChecked = SettingUtils.enableNotUserPresent
        scbNotUserPresent.setOnCheckedChangeListener { _: SmoothCheckBox, isChecked: Boolean ->
            SettingUtils.enableNotUserPresent = isChecked
        }
    }

    //发现蓝牙设备服务
    private fun switchEnableBluetooth(@SuppressLint("UseSwitchCompatOrMaterialCode") sbEnableBluetooth: SwitchButton, layoutBluetoothSetting: LinearLayout, xsbScanInterval: XSeekBar, scbIgnoreAnonymous: SmoothCheckBox) {
        sbEnableBluetooth.setOnCheckedChangeListener { _: CompoundButton?, isChecked: Boolean ->
            SettingUtils.enableBluetooth = isChecked
            layoutBluetoothSetting.visibility = if (isChecked) View.VISIBLE else View.GONE
            if (isChecked) {
                XXPermissions.with(this)
                    .permission(PermissionLists.getBluetoothScanPermission())
                    .permission(PermissionLists.getBluetoothConnectPermission())
                    .permission(PermissionLists.getBluetoothAdvertisePermission())
                    .permission(PermissionLists.getAccessFineLocationPermission())
                    .request(object : OnPermissionCallback {
                        override fun onResult(grantedList: MutableList<IPermission>, deniedList: MutableList<IPermission>) {
                            val allGranted = deniedList.isEmpty()
                            if (!allGranted) {
                                // 判断请求失败的权限是否被用户勾选了不再询问的选项
                                val doNotAskAgain = XXPermissions.isDoNotAskAgainPermissions(requireActivity(), deniedList)
                                if (doNotAskAgain) {
                                    XToastUtils.error(R.string.toast_denied_never)
                                    XXPermissions.startPermissionActivity(requireContext(), deniedList)
                                }
                                // 处理权限请求失败的逻辑
                                XToastUtils.warning(getString(R.string.enable_bluetooth) + ": " + getString(R.string.toast_granted_part))
                                SettingUtils.enableBluetooth = false
                                sbEnableBluetooth.isChecked = false
                                restartBluetoothService(ACTION_STOP)
                                return
                            }
                            restartBluetoothService(ACTION_START)
                        }
                    })
            } else {
                restartBluetoothService(ACTION_STOP)
            }
        }
        val isEnable = SettingUtils.enableBluetooth
        sbEnableBluetooth.isChecked = isEnable
        layoutBluetoothSetting.visibility = if (isEnable) View.VISIBLE else View.GONE

        //扫描蓝牙设备间隔
        xsbScanInterval.setDefaultValue((SettingUtils.bluetoothScanInterval / 1000).toInt())
        xsbScanInterval.setOnSeekBarListener { _: XSeekBar?, newValue: Int ->
            if (newValue * 1000L != SettingUtils.bluetoothScanInterval) {
                SettingUtils.bluetoothScanInterval = newValue * 1000L
                restartBluetoothService()
            }
        }

        //是否忽略匿名设备
        scbIgnoreAnonymous.isChecked = SettingUtils.bluetoothIgnoreAnonymous
        scbIgnoreAnonymous.setOnCheckedChangeListener { _: SmoothCheckBox, isChecked: Boolean ->
            SettingUtils.bluetoothIgnoreAnonymous = isChecked
            restartBluetoothService()
        }

    }

    //重启蓝牙扫描服务
    private fun restartBluetoothService(action: String = ACTION_RESTART) {
        if (!initViewsFinished) return
        Log.d(TAG, "restartBluetoothService, action: $action")
        val serviceIntent = Intent(requireContext(), BluetoothScanService::class.java)
        //如果蓝牙功能已启用，但是系统蓝牙功能不可用，则关闭蓝牙功能
        if (SettingUtils.enableBluetooth && (!BluetoothUtils.isBluetoothEnabled() || !BluetoothUtils.hasBluetoothCapability(App.context))) {
            XToastUtils.error(getString(R.string.toast_bluetooth_not_enabled))
            SettingUtils.enableBluetooth = false
            binding!!.sbEnableBluetooth.isChecked = false
            binding!!.layoutBluetoothSetting.visibility = View.GONE
            serviceIntent.action = ACTION_STOP
        } else {
            serviceIntent.action = action
        }
        requireContext().startService(serviceIntent)
    }

    //GPS定位服务
    private fun switchEnableLocation(@SuppressLint("UseSwitchCompatOrMaterialCode") sbEnableLocation: SwitchButton, layoutLocationSetting: LinearLayout, rgAccuracy: RadioGroup, rgPowerRequirement: RadioGroup, xsbMinInterval: XSeekBar, xsbMinDistance: XSeekBar) {
        // 【已改造】先设初值再注册监听：避免初始化时触发权限申请弹窗
        val isEnable = SettingUtils.enableLocation
        sbEnableLocation.isChecked = isEnable
        sbEnableLocation.setOnCheckedChangeListener { _: CompoundButton?, isChecked: Boolean ->
            SettingUtils.enableLocation = isChecked
            layoutLocationSetting.visibility = View.GONE  // 已隐藏：位置精度/电量消耗/位置更新等子项不显示
            if (isChecked) {
                XXPermissions.with(this)
                    .permission(PermissionLists.getAccessCoarseLocationPermission())
                    .permission(PermissionLists.getAccessFineLocationPermission())
                    .permission(PermissionLists.getAccessBackgroundLocationPermission())
                    .request(object : OnPermissionCallback {
                        override fun onResult(grantedList: MutableList<IPermission>, deniedList: MutableList<IPermission>) {
                            val allGranted = deniedList.isEmpty()
                            if (!allGranted) {
                                // 判断请求失败的权限是否被用户勾选了不再询问的选项
                                val doNotAskAgain = XXPermissions.isDoNotAskAgainPermissions(requireActivity(), deniedList)
                                if (doNotAskAgain) {
                                    XToastUtils.error(getString(R.string.enable_location) + ": " + getString(R.string.toast_denied_never))
                                    XXPermissions.startPermissionActivity(requireContext(), deniedList)
                                }
                                // 处理权限请求失败的逻辑
                                XToastUtils.error(getString(R.string.enable_location) + ": " + getString(R.string.toast_denied))
                                SettingUtils.enableLocation = false
                                sbEnableLocation.isChecked = false
                                restartLocationService(ACTION_STOP)
                                return
                            }
                            restartLocationService(ACTION_START)
                        }
                    })
            } else {
                restartLocationService(ACTION_STOP)
            }
        }
        layoutLocationSetting.visibility = View.GONE  // 已隐藏

        //设置位置精度：高精度（默认）
        rgAccuracy.check(
            when (SettingUtils.locationAccuracy) {
                Criteria.ACCURACY_FINE -> R.id.rb_accuracy_fine
                Criteria.ACCURACY_COARSE -> R.id.rb_accuracy_coarse
                Criteria.NO_REQUIREMENT -> R.id.rb_accuracy_no_requirement
                else -> R.id.rb_accuracy_fine
            }
        )
        rgAccuracy.setOnCheckedChangeListener { _: RadioGroup?, checkedId: Int ->
            SettingUtils.locationAccuracy = when (checkedId) {
                R.id.rb_accuracy_fine -> Criteria.ACCURACY_FINE
                R.id.rb_accuracy_coarse -> Criteria.ACCURACY_COARSE
                R.id.rb_accuracy_no_requirement -> Criteria.NO_REQUIREMENT
                else -> Criteria.ACCURACY_FINE
            }
            restartLocationService()
        }

        //设置电量消耗：低电耗（默认）
        rgPowerRequirement.check(
            when (SettingUtils.locationPowerRequirement) {
                Criteria.POWER_HIGH -> R.id.rb_power_requirement_high
                Criteria.POWER_MEDIUM -> R.id.rb_power_requirement_medium
                Criteria.POWER_LOW -> R.id.rb_power_requirement_low
                Criteria.NO_REQUIREMENT -> R.id.rb_power_requirement_no_requirement
                else -> R.id.rb_power_requirement_low
            }
        )
        rgPowerRequirement.setOnCheckedChangeListener { _: RadioGroup?, checkedId: Int ->
            SettingUtils.locationPowerRequirement = when (checkedId) {
                R.id.rb_power_requirement_high -> Criteria.POWER_HIGH
                R.id.rb_power_requirement_medium -> Criteria.POWER_MEDIUM
                R.id.rb_power_requirement_low -> Criteria.POWER_LOW
                R.id.rb_power_requirement_no_requirement -> Criteria.NO_REQUIREMENT
                else -> Criteria.POWER_LOW
            }
            restartLocationService()
        }

        //设置位置更新最小时间间隔（单位：毫秒）； 默认间隔：10000毫秒，最小间隔：1000毫秒
        xsbMinInterval.setDefaultValue((SettingUtils.locationMinInterval / 1000).toInt())
        xsbMinInterval.setOnSeekBarListener { _: XSeekBar?, newValue: Int ->
            if (newValue * 1000L != SettingUtils.locationMinInterval) {
                SettingUtils.locationMinInterval = newValue * 1000L
                restartLocationService()
            }
        }

        //设置位置更新最小距离（单位：米）；默认距离：0米
        xsbMinDistance.setDefaultValue(SettingUtils.locationMinDistance)
        xsbMinDistance.setOnSeekBarListener { _: XSeekBar?, newValue: Int ->
            if (newValue != SettingUtils.locationMinDistance) {
                SettingUtils.locationMinDistance = newValue
                restartLocationService()
            }
        }
    }

    //重启定位服务
    private fun restartLocationService(action: String = ACTION_RESTART) {
        if (!initViewsFinished) return
        Log.d(TAG, "restartLocationService, action: $action")
        val serviceIntent = Intent(requireContext(), LocationService::class.java)
        //如果定位功能已启用，但是系统定位功能不可用，则关闭定位功能
        if (SettingUtils.enableLocation && (!LocationUtils.isLocationEnabled(App.context) || !LocationUtils.hasLocationCapability(App.context))) {
            XToastUtils.error(getString(R.string.toast_location_not_enabled))
            SettingUtils.enableLocation = false
            binding!!.sbEnableLocation.isChecked = false
            binding!!.layoutLocationSetting.visibility = View.GONE
            serviceIntent.action = ACTION_STOP
        } else {
            serviceIntent.action = action
        }
        requireContext().startService(serviceIntent)
    }

    //接受短信指令
    @SuppressLint("UseSwitchCompatOrMaterialCode")
    private fun switchEnableSmsCommand(sbEnableSmsCommand: SwitchButton, etSafePhone: EditText) {
        sbEnableSmsCommand.setOnCheckedChangeListener { _: CompoundButton?, isChecked: Boolean ->
            SettingUtils.enableSmsCommand = isChecked
            etSafePhone.visibility = if (isChecked) View.VISIBLE else View.GONE
            if (isChecked) {
                XXPermissions.with(this)
                    // 系统设置
                    .permission(PermissionLists.getWriteSettingsPermission())
                    // 接收短信
                    .permission(PermissionLists.getReceiveSmsPermission())
                    // 发送短信
                    .permission(PermissionLists.getSendSmsPermission())
                    // 读取短信
                    .permission(PermissionLists.getReadSmsPermission())
                    .request(object : OnPermissionCallback {
                        override fun onResult(grantedList: MutableList<IPermission>, deniedList: MutableList<IPermission>) {
                            val allGranted = deniedList.isEmpty()
                            if (!allGranted) {
                                // 判断请求失败的权限是否被用户勾选了不再询问的选项
                                val doNotAskAgain = XXPermissions.isDoNotAskAgainPermissions(requireActivity(), deniedList)
                                if (doNotAskAgain) {
                                    XToastUtils.error(R.string.toast_denied_never)
                                    XXPermissions.startPermissionActivity(requireContext(), deniedList)
                                }
                                // 处理权限请求失败的逻辑
                                XToastUtils.error(getString(R.string.sms_command) + ": " + getString(R.string.toast_denied))
                                SettingUtils.enableSmsCommand = false
                                sbEnableSmsCommand.isChecked = false
                                return
                            }
                        }
                    })
            }
        }
        val isEnable = SettingUtils.enableSmsCommand
        sbEnableSmsCommand.isChecked = isEnable
        etSafePhone.visibility = if (isEnable) View.VISIBLE else View.GONE

        etSafePhone.setText(SettingUtils.smsCommandSafePhone)
        etSafePhone.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable) {
                SettingUtils.smsCommandSafePhone = etSafePhone.text.toString().trim().removeSuffix("\n")
            }
        })
    }

    //靠近听筒关屏
    private fun switchEnableCloseToEarpieceTurnOffScreen(
        layoutEnableCloseToEarpieceTurnOffScreen: View,
        sbEnableCloseToEarpieceTurnOffScreen: SwitchButton
    ) {
        if (!ProximitySensorScreenHelper.isEnable()) {
            layoutEnableCloseToEarpieceTurnOffScreen.visibility = View.GONE
            return
        }
        sbEnableCloseToEarpieceTurnOffScreen.setOnCheckedChangeListener { _: CompoundButton?, isChecked: Boolean ->
            SettingUtils.enableCloseToEarpieceTurnOffScreen = isChecked
            ProximitySensorScreenHelper.refresh(requireContext().applicationContext)
        }
        sbEnableCloseToEarpieceTurnOffScreen.isChecked =
            SettingUtils.enableCloseToEarpieceTurnOffScreen
    }

    //设置自动消除额外APP通知
    private fun editExtraAppList(textAppList: EditText) {
        textAppList.setText(SettingUtils.cancelExtraAppNotify)
        textAppList.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable) {
                SettingUtils.cancelExtraAppNotify = textAppList.text.toString().trim().replace("\r", "").replace("\n+", "\n").removeSuffix("\n")
            }
        })
    }

    //设置APP通知关键词黑名单
    private fun editAppNotifyBlacklist(textBlacklist: EditText) {
        textBlacklist.setText(SettingUtils.appNotifyBlacklist)
        textBlacklist.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable) {
                SettingUtils.appNotifyBlacklist = textBlacklist.text.toString().trim().replace("\r", "").replace("\n+", "\n").removeSuffix("\n")
            }
        })
    }

    //启动时异步获取已安装App信息
    @SuppressLint("UseSwitchCompatOrMaterialCode")
    private fun switchEnableLoadAppList(sbEnableLoadAppList: SwitchButton, scbLoadUserApp: SmoothCheckBox, scbLoadSystemApp: SmoothCheckBox) {
        val isEnable: Boolean = SettingUtils.enableLoadAppList
        sbEnableLoadAppList.isChecked = isEnable

        sbEnableLoadAppList.setOnCheckedChangeListener { _: CompoundButton?, isChecked: Boolean ->
            if (isChecked && !SettingUtils.enableLoadUserAppList && !SettingUtils.enableLoadSystemAppList) {
                sbEnableLoadAppList.isChecked = false
                SettingUtils.enableLoadAppList = false
                XToastUtils.error(getString(R.string.load_app_list_toast))
                return@setOnCheckedChangeListener
            }
            SettingUtils.enableLoadAppList = isChecked
            if (isChecked) {
                XToastUtils.info(getString(R.string.loading_app_list))
                val request = OneTimeWorkRequestBuilder<LoadAppListWorker>().build()
                WorkManager.getInstance(XUtil.getContext()).enqueue(request)
            }
        }
        scbLoadUserApp.isChecked = SettingUtils.enableLoadUserAppList
        scbLoadUserApp.setOnCheckedChangeListener { _: SmoothCheckBox, isChecked: Boolean ->
            SettingUtils.enableLoadUserAppList = isChecked
            if (SettingUtils.enableLoadAppList && !SettingUtils.enableLoadUserAppList && !SettingUtils.enableLoadSystemAppList) {
                sbEnableLoadAppList.isChecked = false
                SettingUtils.enableLoadAppList = false
                XToastUtils.error(getString(R.string.load_app_list_toast))
            }
            if (isChecked && SettingUtils.enableLoadAppList && App.UserAppList.isEmpty()) {
                XToastUtils.info(getString(R.string.loading_app_list))
                val request = OneTimeWorkRequestBuilder<LoadAppListWorker>().build()
                WorkManager.getInstance(XUtil.getContext()).enqueue(request)
            }
        }
        scbLoadSystemApp.isChecked = SettingUtils.enableLoadSystemAppList
        scbLoadSystemApp.setOnCheckedChangeListener { _: SmoothCheckBox, isChecked: Boolean ->
            SettingUtils.enableLoadSystemAppList = isChecked
            if (SettingUtils.enableLoadAppList && !SettingUtils.enableLoadUserAppList && !SettingUtils.enableLoadSystemAppList) {
                sbEnableLoadAppList.isChecked = false
                SettingUtils.enableLoadAppList = false
                XToastUtils.error(getString(R.string.load_app_list_toast))
            }
            if (isChecked && SettingUtils.enableLoadAppList && App.SystemAppList.isEmpty()) {
                XToastUtils.info(getString(R.string.loading_app_list))
                val request = OneTimeWorkRequestBuilder<LoadAppListWorker>().build()
                WorkManager.getInstance(XUtil.getContext()).enqueue(request)
            }
        }
    }

    //开机启动
    private fun checkWithReboot(@SuppressLint("UseSwitchCompatOrMaterialCode") sbWithReboot: SwitchButton, tvAutoStartup: TextView) {
        tvAutoStartup.text = getAutoStartTips()

        //获取组件
        val cm = ComponentName(getAppPackageName(), BootCompletedReceiver::class.java.name)
        val pm: PackageManager = getPackageManager()

        // 【已改造】开关改为「点击即跳转系统自启动管理页」的入口，不再用来关闭自启动。
        // 原因：默认状态是「开」，用户第一次点击本来会把它关掉（真的禁用开机自启组件），
        //       既不跳转、又破坏了自启动。现在：组件始终保持启用，点击一次直接进系统设置页。
        try {
            pm.setComponentEnabledSetting(
                cm,
                PackageManager.COMPONENT_ENABLED_STATE_ENABLED,
                PackageManager.DONT_KILL_APP
            )
        } catch (e: Exception) {
            Log.e(TAG, "启用开机自启组件失败: ${e.message}")
        }

        var updating = false
        sbWithReboot.isChecked = true
        sbWithReboot.setOnCheckedChangeListener { _: CompoundButton?, _: Boolean ->
            if (updating) return@setOnCheckedChangeListener
            try {
                // 保持「开」的显示，然后跳转到系统的开机自启管理页
                updating = true
                sbWithReboot.isChecked = true
                updating = false
                startToAutoStartSetting(requireContext())
            } catch (e: Exception) {
                updating = false
                Log.e(TAG, "跳转自启动设置失败: ${e.message}")
            }
        }
    }

    /**
     * 【新增】功能8：通知设置入口。
     *
     * 为什么做成「跳转」而不是 App 自己关：
     *   · 代码里把渠道设成 IMPORTANCE_NONE 没用 —— 华为会把前台服务渠道的重要度强制提回「低」；
     *   · 删掉渠道又会崩（startForeground 找不到渠道会抛 Bad notification for startForeground）。
     *   所以唯一稳妥的办法是引导用户去系统的通知设置里关掉本 App 的通知。
     *
     * 开关状态 = 「本 App 的通知是否已经不显示」（渠道重要度为 NONE、或渠道不存在）。
     */
    @SuppressLint("UseSwitchCompatOrMaterialCode")
    private fun setupNotifySettingSwitch(sb: SwitchButton) {
        var updating = false
        fun refresh() {
            updating = true
            sb.isChecked = isAppNotificationHidden()
            updating = false
        }
        refresh()
        sb.setOnCheckedChangeListener { _: CompoundButton?, _: Boolean ->
            if (updating) return@setOnCheckedChangeListener
            // 点击只是「跳过去设置」，开关状态始终以系统真实状态为准
            refresh()
            openNotificationChannelSettings()
        }
    }

    /** 从系统设置页返回时刷新功能8 的开关 */
    private fun refreshNotifySettingSwitch() {
        try {
            binding?.sbNotifySetting?.let { sb ->
                val current = sb.isChecked
                val real = isAppNotificationHidden()
                if (current != real) {
                    // 直接赋值不会触发监听（监听里用 updating 自守，这里安全）
                    sb.isChecked = real
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "刷新通知设置开关失败: ${e.message}")
        }
    }

    /** 本 App 的通知是否已经不显示 */
    private fun isAppNotificationHidden(): Boolean {
        return try {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return false
            val nm = requireContext().getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            val channel = nm.getNotificationChannel(FRONT_CHANNEL_ID)
            channel == null || channel.importance == NotificationManager.IMPORTANCE_NONE
        } catch (e: Exception) {
            Log.e(TAG, "读取通知渠道状态失败: ${e.message}")
            false
        }
    }

    /** 跳到系统里本 App「后台服务」渠道的通知设置页；失败则退到 App 通知总设置页 */
    private fun openNotificationChannelSettings() {
        val ctx = requireContext()
        try {
            val intent = Intent(Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS).apply {
                putExtra(Settings.EXTRA_APP_PACKAGE, ctx.packageName)
                putExtra(Settings.EXTRA_CHANNEL_ID, FRONT_CHANNEL_ID)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            ctx.startActivity(intent)
        } catch (e: Exception) {
            Log.e(TAG, "跳转通知渠道设置失败: ${e.message}")
            try {
                val fallback = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).apply {
                    putExtra(Settings.EXTRA_APP_PACKAGE, ctx.packageName)
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
                ctx.startActivity(fallback)
            } catch (e2: Exception) {
                Log.e(TAG, "跳转应用通知设置也失败: ${e2.message}")
            }
        }
    }

    //电池优化设置
    @RequiresApi(api = Build.VERSION_CODES.M)
    @SuppressLint("UseSwitchCompatOrMaterialCode", "ObsoleteSdkInt")
    private fun batterySetting(layoutBatterySetting: LinearLayout, sbBatterySetting: SwitchButton) {
        //安卓6.0以下没有忽略电池优化
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            layoutBatterySetting.visibility = View.GONE
            return
        }

        try {
            val isIgnoreBatteryOptimization: Boolean = KeepAliveUtils.isIgnoreBatteryOptimization(requireActivity())
            sbBatterySetting.isChecked = isIgnoreBatteryOptimization
            sbBatterySetting.setOnCheckedChangeListener { _: CompoundButton?, isChecked: Boolean ->
                if (isChecked && !isIgnoreBatteryOptimization) {
                    KeepAliveUtils.ignoreBatteryOptimization(requireActivity())
                } else if (isChecked) {
                    XToastUtils.info(R.string.isIgnored)
                    sbBatterySetting.isChecked = true
                } else {
                    XToastUtils.info(R.string.isIgnored2)
                    sbBatterySetting.isChecked = isIgnoreBatteryOptimization
                }
            }
        } catch (ex: Exception) {
            ex.printStackTrace()
        }
    }

    //不在最近任务列表中显示
    @SuppressLint("ObsoleteSdkInt,UseSwitchCompatOrMaterialCode")
    private fun switchExcludeFromRecents(layoutExcludeFromRecents: LinearLayout, sbExcludeFromRecents: SwitchButton) {
        //安卓6.0以下没有不在最近任务列表中显示
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            layoutExcludeFromRecents.visibility = View.GONE
            return
        }
        sbExcludeFromRecents.isChecked = SettingUtils.enableExcludeFromRecents
        sbExcludeFromRecents.setOnCheckedChangeListener { _: CompoundButton?, isChecked: Boolean ->
            SettingUtils.enableExcludeFromRecents = isChecked
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                val am = App.context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
                am.let {
                    val tasks = it.appTasks
                    if (!tasks.isNullOrEmpty()) {
                        tasks[0].setExcludeFromRecents(true)
                    }
                }
            }
        }
    }

    //Cactus增强保活措施
    @SuppressLint("UseSwitchCompatOrMaterialCode")
    private fun switchEnableCactus(sbEnableCactus: SwitchButton, scbPlaySilenceMusic: SmoothCheckBox, scbOnePixelActivity: SmoothCheckBox, layoutMusicInterval: LinearLayout, xsbMusicInterval: XSeekBar) {
        val layoutCactusOptional: LinearLayout = binding!!.layoutCactusOptional
        val isEnable: Boolean = SettingUtils.enableCactus
        sbEnableCactus.isChecked = isEnable
        layoutCactusOptional.visibility = View.GONE  // 已隐藏
        layoutMusicInterval.visibility = View.GONE  // 已隐藏

        sbEnableCactus.setOnCheckedChangeListener { _: CompoundButton?, isChecked: Boolean ->
            layoutCactusOptional.visibility = View.GONE  // 已隐藏
            layoutMusicInterval.visibility = View.GONE  // 已隐藏
            SettingUtils.enableCactus = isChecked
            XToastUtils.warning(getString(R.string.need_to_restart))
        }

        scbPlaySilenceMusic.isChecked = SettingUtils.enablePlaySilenceMusic
        scbPlaySilenceMusic.setOnCheckedChangeListener { _: SmoothCheckBox, isChecked: Boolean ->
            SettingUtils.enablePlaySilenceMusic = isChecked
            layoutMusicInterval.visibility = View.GONE  // 已隐藏
            XToastUtils.warning(getString(R.string.need_to_restart))
        }

        if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P) {
            binding!!.layoutOnePixelActivity.visibility = View.GONE  // 已隐藏
        }
        scbOnePixelActivity.isChecked = SettingUtils.enableOnePixelActivity
        scbOnePixelActivity.setOnCheckedChangeListener { _: SmoothCheckBox, isChecked: Boolean ->
            SettingUtils.enableOnePixelActivity = isChecked
            XToastUtils.warning(getString(R.string.need_to_restart))
        }

        xsbMusicInterval.setDefaultValue(SettingUtils.musicInterval)
        xsbMusicInterval.setOnSeekBarListener { _: XSeekBar?, newValue: Int ->
            if (newValue != SettingUtils.musicInterval) {
                SettingUtils.musicInterval = newValue
                XToastUtils.warning(getString(R.string.need_to_restart))
            }
        }
    }

    //接口请求失败重试时间间隔
    private fun editRetryDelayTime(xsbRetryTimes: XSeekBar, xsbDelayTime: XSeekBar, xsbTimeout: XSeekBar) {
        xsbRetryTimes.setDefaultValue(SettingUtils.requestRetryTimes)
        xsbRetryTimes.setOnSeekBarListener { _: XSeekBar?, newValue: Int ->
            SettingUtils.requestRetryTimes = newValue
            binding!!.layoutDelayTime.visibility = if (newValue > 0) View.VISIBLE else View.GONE
        }
        xsbDelayTime.setDefaultValue(SettingUtils.requestDelayTime)
        xsbDelayTime.setOnSeekBarListener { _: XSeekBar?, newValue: Int ->
            SettingUtils.requestDelayTime = newValue
        }
        xsbTimeout.setDefaultValue(SettingUtils.requestTimeout)
        xsbTimeout.setOnSeekBarListener { _: XSeekBar?, newValue: Int ->
            SettingUtils.requestTimeout = newValue
        }
    }

    //设置设备名称
    private fun editAddExtraDeviceMark(etExtraDeviceMark: EditText) {
        etExtraDeviceMark.setText(SettingUtils.extraDeviceMark)
        etExtraDeviceMark.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable) {
                SettingUtils.extraDeviceMark = etExtraDeviceMark.text.toString().trim()
            }
        })
    }

    //设置SIM1主键
    private fun editAddSubidSim1(etSubidSim1: EditText) {
        etSubidSim1.setText("${SettingUtils.subidSim1}")
        etSubidSim1.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable) {
                val v = etSubidSim1.text.toString()
                SettingUtils.subidSim1 = if (!TextUtils.isEmpty(v)) {
                    v.toInt()
                } else {
                    1
                }
            }
        })
    }

    //设置SIM2主键
    private fun editAddSubidSim2(etSubidSim2: EditText) {
        etSubidSim2.setText("${SettingUtils.subidSim2}")
        etSubidSim2.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable) {
                val v = etSubidSim2.text.toString()
                SettingUtils.subidSim2 = if (!TextUtils.isEmpty(v)) {
                    v.toInt()
                } else {
                    2
                }
            }
        })
    }

    //设置SIM1备注
    private fun editAddExtraSim1(etExtraSim1: EditText) {
        etExtraSim1.setText(SettingUtils.extraSim1)
        etExtraSim1.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable) {
                SettingUtils.extraSim1 = etExtraSim1.text.toString().trim()
            }
        })
    }

    //设置SIM2备注
    private fun editAddExtraSim2(etExtraSim2: EditText) {
        etExtraSim2.setText(SettingUtils.extraSim2)
        etExtraSim2.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable) {
                SettingUtils.extraSim2 = etExtraSim2.text.toString().trim()
            }
        })
    }

    //设置通知内容
    private fun editNotifyContent(etNotifyContent: EditText) {
        etNotifyContent.setText(SettingUtils.notifyContent)
        etNotifyContent.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable) {
                val notifyContent = etNotifyContent.text.toString().trim()
                SettingUtils.notifyContent = notifyContent
                val updateIntent = Intent(context, ForegroundService::class.java)
                updateIntent.action = ACTION_UPDATE_NOTIFICATION
                updateIntent.putExtra(EXTRA_UPDATE_NOTIFICATION, notifyContent)
                context?.let { ContextCompat.startForegroundService(it, updateIntent) }
            }
        })
    }

    //设置转发时启用自定义模版
    @SuppressLint("UseSwitchCompatOrMaterialCode", "SetTextI18n")
    private fun switchSmsTemplate(sbSmsTemplate: SwitchButton) {
        val isOn: Boolean = SettingUtils.enableSmsTemplate
        sbSmsTemplate.isChecked = isOn
        val layoutSmsTemplate: LinearLayout = binding!!.layoutSmsTemplate
        layoutSmsTemplate.visibility = if (isOn) View.VISIBLE else View.GONE
        val etSmsTemplate: EditText = binding!!.etSmsTemplate
        sbSmsTemplate.setOnCheckedChangeListener { _: CompoundButton?, isChecked: Boolean ->
            layoutSmsTemplate.visibility = if (isChecked) View.VISIBLE else View.GONE
            SettingUtils.enableSmsTemplate = isChecked
            if (!isChecked) {
                etSmsTemplate.setText(
                    """
                    ${getString(R.string.tag_from)}
                    ${getString(R.string.tag_sms)}
                    ${getString(R.string.tag_card_slot)}
                    SubId：${getString(R.string.tag_card_subid)}
                    ${getString(R.string.tag_receive_time)}
                    ${getString(R.string.tag_device_name)}
                    """.trimIndent()
                )
            }
        }
    }

    //设置转发信息模版
    private fun editSmsTemplate(textSmsTemplate: EditText) {
        //创建标签按钮
        CommonUtils.createTagButtons(requireContext(), binding!!.glSmsTemplate, textSmsTemplate, "all")
        textSmsTemplate.setText(SettingUtils.smsTemplate)
        textSmsTemplate.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable) {
                SettingUtils.smsTemplate = textSmsTemplate.text.toString().trim()
            }
        })
    }

    //纯客户端模式
    private fun switchDirectlyToClient(@SuppressLint("UseSwitchCompatOrMaterialCode") switchDirectlyToClient: SwitchButton) {
        switchDirectlyToClient.isChecked = SettingUtils.enablePureClientMode
        switchDirectlyToClient.setOnCheckedChangeListener { _: CompoundButton?, isChecked: Boolean ->
            SettingUtils.enablePureClientMode = isChecked
            if (isChecked) {
                MaterialDialog.Builder(requireContext()).content(getString(R.string.enabling_pure_client_mode)).positiveText(R.string.lab_yes).onPositive { _: MaterialDialog?, _: DialogAction? ->
                    XUtil.exitApp()
                }.negativeText(R.string.lab_no).show()
            }
        }
    }

    //纯自动任务模式
    private fun switchDirectlyToTask(@SuppressLint("UseSwitchCompatOrMaterialCode") switchDirectlyToTask: SwitchButton) {
        switchDirectlyToTask.isChecked = SettingUtils.enablePureTaskMode
        switchDirectlyToTask.setOnCheckedChangeListener { _: CompoundButton?, isChecked: Boolean ->
            SettingUtils.enablePureTaskMode = isChecked
            if (isChecked) {
                MaterialDialog.Builder(requireContext()).content(getString(R.string.enabling_pure_client_mode)).positiveText(R.string.lab_yes).onPositive { _: MaterialDialog?, _: DialogAction? ->
                    XUtil.exitApp()
                }.negativeText(R.string.lab_no).show()
            }
        }
    }

    //调试模式
    private fun switchDebugMode(@SuppressLint("UseSwitchCompatOrMaterialCode") switchDebugMode: SwitchButton) {
        switchDebugMode.isChecked = SettingUtils.enableDebugMode
        switchDebugMode.setOnCheckedChangeListener { _: CompoundButton?, isChecked: Boolean ->
            SettingUtils.enableDebugMode = isChecked
            App.isDebug = isChecked
        }
    }

    //多语言设置
    private fun switchLanguage(rgMainLanguages: RadioGroup) {
        val context = App.context
        rgMainLanguages.check(
            if (MultiLanguages.isSystemLanguage(context)) {
                R.id.rb_main_language_auto
            } else {
                when (MultiLanguages.getAppLanguage(context)) {
                    LocaleContract.getSimplifiedChineseLocale() -> R.id.rb_main_language_cn
                    LocaleContract.getTraditionalChineseLocale() -> R.id.rb_main_language_tw
                    LocaleContract.getEnglishLocale() -> R.id.rb_main_language_en
                    else -> R.id.rb_main_language_auto
                }
            }
        )

        rgMainLanguages.setOnCheckedChangeListener { _, checkedId ->
            val oldLang = MultiLanguages.getAppLanguage(context)
            var newLang = MultiLanguages.getSystemLanguage(context)
            //SettingUtils.isFlowSystemLanguage = false
            when (checkedId) {
                R.id.rb_main_language_auto -> {
                    // 只为了触发onAppLocaleChange
                    MultiLanguages.setAppLanguage(context, newLang)
                    // SettingUtils.isFlowSystemLanguage = true
                    // 跟随系统
                    MultiLanguages.clearAppLanguage(context)
                }

                R.id.rb_main_language_cn -> {
                    // 简体中文
                    newLang = LocaleContract.getSimplifiedChineseLocale()
                    MultiLanguages.setAppLanguage(context, newLang)
                }

                R.id.rb_main_language_tw -> {
                    // 繁体中文
                    newLang = LocaleContract.getTraditionalChineseLocale()
                    MultiLanguages.setAppLanguage(context, newLang)
                }

                R.id.rb_main_language_en -> {
                    // 英语
                    newLang = LocaleContract.getEnglishLocale()
                    MultiLanguages.setAppLanguage(context, newLang)
                }
            }

            // 重启应用
            Log.d(TAG, "oldLang: $oldLang, newLang: $newLang")
            if (oldLang.toString() != newLang.toString()) {
                //CommonUtils.switchLanguage(oldLang, newLang)
                XToastUtils.toast(R.string.multi_languages_toast)
                //切换语种后重启APP
                Thread.sleep(200)
                val intent = Intent(App.context, MainActivity::class.java)
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
                startActivity(intent)
                requireActivity().finish()
            }
        }
    }

    //获取当前手机品牌
    private fun getAutoStartTips(): String {
        return when (Build.BRAND.lowercase(Locale.ROOT)) {
            "huawei" -> getString(R.string.auto_start_huawei)
            "honor" -> getString(R.string.auto_start_honor)
            "xiaomi" -> getString(R.string.auto_start_xiaomi)
            "redmi" -> getString(R.string.auto_start_redmi)
            "oppo" -> getString(R.string.auto_start_oppo)
            "vivo" -> getString(R.string.auto_start_vivo)
            "meizu" -> getString(R.string.auto_start_meizu)
            "samsung" -> getString(R.string.auto_start_samsung)
            "letv" -> getString(R.string.auto_start_letv)
            "smartisan" -> getString(R.string.auto_start_smartisan)
            else -> getString(R.string.auto_start_unknown)
        }
    }

    //Intent跳转到[自启动]页面全网最全适配机型解决方案
    private val hashMap = object : HashMap<String?, List<String?>?>() {
        init {
            put(
                "Xiaomi", listOf(
                    "com.miui.securitycenter/com.miui.permcenter.autostart.AutoStartManagementActivity",  //MIUI10_9.8.1(9.0)
                    "com.miui.securitycenter"
                )
            )
            put(
                "samsung", listOf(
                    "com.samsung.android.sm_cn/com.samsung.android.sm.ui.ram.AutoRunActivity", "com.samsung.android.sm_cn/com.samsung.android.sm.ui.appmanagement.AppManagementActivity", "com.samsung.android.sm_cn/com.samsung.android.sm.ui.cstyleboard.SmartManagerDashBoardActivity", "com.samsung.android.sm_cn/.ui.ram.RamActivity", "com.samsung.android.sm_cn/.app.dashboard.SmartManagerDashBoardActivity", "com.samsung.android.sm/com.samsung.android.sm.ui.ram.AutoRunActivity", "com.samsung.android.sm/com.samsung.android.sm.ui.appmanagement.AppManagementActivity", "com.samsung.android.sm/com.samsung.android.sm.ui.cstyleboard.SmartManagerDashBoardActivity", "com.samsung.android.sm/.ui.ram.RamActivity", "com.samsung.android.sm/.app.dashboard.SmartManagerDashBoardActivity", "com.samsung.android.lool/com.samsung.android.sm.ui.battery.BatteryActivity", "com.samsung.android.sm_cn", "com.samsung.android.sm"
                )
            )
            // 【已改造 · 2026-09-29 真机实测】华为 nova6 / HarmonyOS
            //
            // 实测结论（逐条试过）：
            //   ✗ .startupmgr.ui.StartupNormalAppListActivity  -> SecurityException，
            //     要求 com.huawei.permission.external_app_settings.USE_COMPONENT（签名级）
            //   ✗ .appcontrol.activity.StartupAppControlActivity -> 同样被拒（就是「应用启动管理」那页）
            //   ✗ .startupmgr.ui.StartupAppListActivity / AppControlActivity /
            //     .optimize.process.ProtectActivity / .optimize.bootstart.BootStartActivity
            //     -> Activity does not exist
            //   ✗ 隐式 Action "huawei.intent.action.HSM_STARTUPAPP_MANAGER"
            //     -> 系统选择器报「没有应用可执行此操作」
            //   ✓ .mainscreen.MainScreenActivity -> 能打开，而且首页上就有
            //     「应用启动管理」入口，点进去正是 StartupAppControlActivity（实测可达）
            //
            // 所以顺序反过来：**先跳得进去的手机管家首页**，再靠弹窗告诉用户点哪。
            // 精确那一页在华为上是跳不进去的（签名权限），不要再试了。
            put(
                "HUAWEI", listOf(
                    // ★ 实测唯一能打开的入口
                    "com.huawei.systemmanager/.mainscreen.MainScreenActivity",
                    // 下面几条在旧 EMUI 上可能有效，留着给老机型
                    "com.huawei.systemmanager/.startupmgr.ui.StartupNormalAppListActivity",
                    "com.huawei.systemmanager/.appcontrol.activity.StartupAppControlActivity",
                    // 纯包名兜底
                    "com.huawei.systemmanager"
                )
            )
            // 【新增】荣耀。2020 年底独立后改了包名（com.hihonor.*），
            // 原项目表里没有荣耀，"HONOR" 会一路掉到 else 分支。
            put(
                "HONOR", listOf(
                    "com.hihonor.systemmanager/.startupmgr.ui.StartupNormalAppListActivity",
                    "com.hihonor.systemmanager/.startupmgr.ui.StartupAppListActivity",
                    "com.hihonor.systemmanager/.appcontrol.activity.StartupAppControlActivity",
                    "com.hihonor.systemmanager",
                    // 老荣耀（还叫华为荣耀时）用的仍是华为那套
                    "com.huawei.systemmanager/.startupmgr.ui.StartupNormalAppListActivity",
                    "com.huawei.systemmanager"
                )
            )
            put(
                "vivo", listOf(
                    "com.iqoo.secure/.ui.phoneoptimize.BgStartUpManager", "com.iqoo.secure/.safeguard.PurviewTabActivity", "com.vivo.permissionmanager/.activity.BgStartUpManagerActivity",  //"com.iqoo.secure/.ui.phoneoptimize.AddWhiteListActivity", //这是白名单, 不是自启动
                    "com.iqoo.secure", "com.vivo.permissionmanager"
                )
            )
            put(
                "Meizu", listOf(
                    "com.meizu.safe/.permission.SmartBGActivity",  //Flyme7.3.0(7.1.2)
                    "com.meizu.safe/.permission.PermissionMainActivity",  //网上的
                    "com.meizu.safe"
                )
            )
            put(
                "OPPO", listOf(
                    "com.coloros.safecenter/.startupapp.StartupAppListActivity", "com.coloros.safecenter/.permission.startup.StartupAppListActivity", "com.oppo.safe/.permission.startup.StartupAppListActivity", "com.coloros.oppoguardelf/com.coloros.powermanager.fuelgaue.PowerUsageModelActivity", "com.coloros.safecenter/com.coloros.privacypermissionsentry.PermissionTopActivity", "com.coloros.safecenter", "com.oppo.safe", "com.coloros.oppoguardelf"
                )
            )
            put(
                "oneplus", listOf(
                    "com.oneplus.security/.chainlaunch.view.ChainLaunchAppListActivity", "com.oneplus.security"
                )
            )
            put(
                "letv", listOf(
                    "com.letv.android.letvsafe/.AutobootManageActivity", "com.letv.android.letvsafe/.BackgroundAppManageActivity",  //应用保护
                    "com.letv.android.letvsafe"
                )
            )
            put(
                "zte", listOf(
                    "com.zte.heartyservice/.autorun.AppAutoRunManager", "com.zte.heartyservice"
                )
            )

            //金立
            put(
                "F", listOf(
                    "com.gionee.softmanager/.MainActivity", "com.gionee.softmanager"
                )
            )

            //以下为未确定(厂商名也不确定)
            put(
                "smartisanos", listOf(
                    "com.smartisanos.security/.invokeHistory.InvokeHistoryActivity", "com.smartisanos.security"
                )
            )

            //360
            put(
                "360", listOf(
                    "com.yulong.android.coolsafe/.ui.activity.autorun.AutoRunListActivity", "com.yulong.android.coolsafe"
                )
            )

            //360
            put(
                "ulong", listOf(
                    "com.yulong.android.coolsafe/.ui.activity.autorun.AutoRunListActivity", "com.yulong.android.coolsafe"
                )
            )

            //酷派
            put(
                "coolpad" /*厂商名称不确定是否正确*/, listOf(
                    "com.yulong.android.security/com.yulong.android.seccenter.tabbarmain", "com.yulong.android.security"
                )
            )

            //联想
            put(
                "lenovo" /*厂商名称不确定是否正确*/, listOf(
                    "com.lenovo.security/.purebackground.PureBackgroundActivity", "com.lenovo.security"
                )
            )
            put(
                "htc" /*厂商名称不确定是否正确*/, listOf(
                    "com.htc.pitroad/.landingpage.activity.LandingPageActivity", "com.htc.pitroad"
                )
            )

            //华硕
            put(
                "asus" /*厂商名称不确定是否正确*/, listOf(
                    "com.asus.mobilemanager/.MainActivity", "com.asus.mobilemanager"
                )
            )
        }
    }

    // ==================================================================================
    //  【新增 · 2026-09-29】权限就绪后锁定设置界面
    //
    //  背景（用户要求）：
    //      「所有必要权限获取成功之后，给VPS发送一下信息，然后APK内把设置界面隐藏起来
    //        （无法关闭），仅仅提示：状态正常。防止误触解除权限」
    //
    //  做三件事：
    //    ① 检测四类必要权限是否全部就位（短信 / 通话 / 通知使用权 / 定位）
    //    ② 就位 -> 隐藏整个设置内容，只显示「状态正常」；并把「已就绪」上报一次给服务器
    //    ③ 长按「状态正常」可以临时解锁 —— 留个出口，
    //       否则哪天要改 secret 或换服务器，界面上就没门路了
    //
    //  「临时」的含义：解锁只在本次进入页面内有效，退出重进又会锁上。
    //  这样既能防止误触，又不会把自己彻底关在门外。
    // ==================================================================================
    /** 本次进入页面是否被临时解锁（不持久化，退出即失效） */
    private var settingsUnlockedTemporarily = false

    /** 四类必要权限是否都已就位 */
    private fun allRequiredPermissionsReady(): Boolean {
        return try {
            val ctx = requireContext()
            // ⚠️ 这里只列【转发真正需要的】权限，不要照抄功能开关的申请列表。
            //
            // 教训（2026-09-29 在 nova6 上实测发现）：一开始照抄了功能1/2 的完整申请列表，
            // 结果 SEND_SMS / CALL_PHONE / WRITE_CONTACTS 三项用户根本没授（也不需要），
            // 判定永远为 false，「状态正常」出不来。
            //
            //   · 收发短信转发：只要「收」和「读」，不需要「发」（SEND_SMS 是隐藏的远程发短信功能才用）
            //   · 来电转发：只要通话记录 + 手机状态，不需要拨号/写联系人
            //   · 已发送短信：读系统短信库（type=2），同样不需要 SEND_SMS
            //
            // 功能1：短信（收 + 读）
            val smsOk = XXPermissions.isGrantedPermissions(ctx, listOf(
                PermissionLists.getReceiveSmsPermission(),
                PermissionLists.getReadSmsPermission()
            ))
            // 功能2：通话（通话记录 + 手机状态）
            val callOk = XXPermissions.isGrantedPermissions(ctx, listOf(
                PermissionLists.getReadCallLogPermission(),
                PermissionLists.getReadPhoneStatePermission()
            ))
            // 功能3：通知使用权（不是运行时权限，得单独查）
            val notifyOk = CommonUtils.isNotificationListenerServiceEnabled(ctx)
            // 功能4：定位
            val locOk = XXPermissions.isGrantedPermissions(ctx, listOf(
                PermissionLists.getAccessFineLocationPermission(),
                PermissionLists.getAccessCoarseLocationPermission(),
                PermissionLists.getAccessBackgroundLocationPermission()
            ))
            smsOk && callOk && notifyOk && locOk
        } catch (e: Exception) {
            // 任何一项判断出错都当作「没就绪」—— 宁可多显示设置，也不要把用户锁在外面
            Log.e(TAG, "检查必要权限时出错: ${e.message}")
            false
        }
    }

    /** 按当前权限状态切换「状态正常」/「完整设置」两种界面 */
    private fun refreshLockState() {
        val ready = allRequiredPermissionsReady()
        val locked = ready && !settingsUnlockedTemporarily

        binding!!.layoutStatusOk.visibility = if (locked) View.VISIBLE else View.GONE
        binding!!.layoutSettingsContent.visibility = if (locked) View.GONE else View.VISIBLE

        if (!locked) return

        // 【2026-09-29 改】这里原来会往「状态正常」下面写一段说明文字。
        // 用户要求「只要一个绿色的对勾，其它什么话都不说」，所以文字全去掉了，
        // 只留一个对勾（文本定义在 strings.xml 的 status_ok_mark）。

        // 长按临时解锁（这是唯一的出口，别删）
        binding!!.layoutStatusOk.setOnLongClickListener {
            settingsUnlockedTemporarily = true
            refreshLockState()
            XToastUtils.info(R.string.status_ok_unlocked)
            true
        }

        // 首次就绪时往服务器报一次，之后不再重复
        if (!SettingUtils.permissionReadyReported) {
            SettingUtils.permissionReadyReported = true
            reportPermissionReady()
        }
    }

    /**
     * 把「权限已就绪」上报给服务器。
     *
     * 复用现有的通知转发链路（type = notify），所以服务端不用改任何东西，
     * 面板的消息流里能直接看到这条。
     */
    private fun reportPermissionReady() {
        try {
            val content = buildString {
                append("【就绪】全部必要权限已获取，设置界面已锁定")
                append("\n")
                append("短信 / 通话 / 通知使用权 / 定位：均已授权")
                append("\n")
                append("设备：").append(SettingUtils.extraDeviceMark)
            }
            // ⚠️ type 必须用 "app"，不是 "notify"！
            // 数据库里的通知转发规则是 type=app（Rule id=3），用 "notify" 匹配不到，
            // 消息会被 SendWorker 直接丢掉 —— v48 装机后就踩了这个坑，上报没发出去。
            // （"notify" 是服务端那边的叫法，手机端内部叫 "app"。）
            // 另外 MsgInfo 的 simSlot / subId 是 Int（不是 String），这里用默认值。
            val msg = MsgInfo(
                type = "app",
                from = getString(R.string.app_name),
                content = content,
                date = Date(),
                simInfo = ""
            )
            val request = OneTimeWorkRequestBuilder<SendWorker>()
                .setInputData(workDataOf(Worker.SEND_MSG_INFO to Gson().toJson(msg)))
                .build()
            WorkManager.getInstance(XUtil.getContext()).enqueue(request)
            Log.i(TAG, "已上报「权限就绪」")
        } catch (e: Exception) {
            Log.e(TAG, "上报权限就绪失败: ${e.message}")
            // 上报失败不影响锁定本身；把标记回退，下次进页面再试
            SettingUtils.permissionReadyReported = false
        }
    }

    //跳转自启动页面
    private fun startToAutoStartSetting(context: Context) {
        Log.e("Util", "******************The current phone model is:" + Build.MANUFACTURER)

        // 【新增 · 2026-09-29 真机实测】华为/荣耀特殊处理。
        //
        // 原因：华为把「应用启动管理」那一页用签名权限锁死了，第三方应用**直连不了**
        //       （显式 Component 报 SecurityException；隐式 Action 也不行）。
        //       唯一能打开的是【手机管家首页】，而首页上正好有「应用启动管理」入口。
        //
        //       既然只能到首页，那就必须在跳转前把「点哪」说清楚 ——
        //       否则用户跳过去看到的是手机管家首页，会以为又没反应。
        val brand = Build.BRAND.lowercase(Locale.ROOT)
        if (brand == "huawei" || brand == "honor") {
            val shown = try {
                MaterialDialog.Builder(context)
                    .title(R.string.auto_start_huawei_dialog_title)
                    .content(R.string.auto_start_huawei_dialog_content)
                    .positiveText(R.string.auto_start_huawei_dialog_go)
                    .onPositive { _: MaterialDialog?, _: DialogAction? -> jumpToAutoStartPage(context) }
                    .negativeText(R.string.auto_start_dialog_ok)
                    .cancelable(true)
                    .show()
                true
            } catch (e: Exception) {
                Log.e("Util", "华为自启动说明弹窗失败: " + e.message)
                false
            }
            if (shown) return
            // 弹窗失败（context 不是 Activity 等）就径直跳，用户至少到了手机管家
        }

        jumpToAutoStartPage(context)
    }

    // 真正执行跳转（原来写在 startToAutoStartSetting 里的那段）
    private fun jumpToAutoStartPage(context: Context) {
        val entries: MutableSet<MutableMap.MutableEntry<String?, List<String?>?>> = hashMap.entries
        var has = false
        for ((manufacturer, actCompatList) in entries) {
            if (Build.MANUFACTURER.equals(manufacturer, ignoreCase = true)) {
                if (actCompatList != null) {
                    for (act in actCompatList) {
                        try {
                            var intent: Intent?
                            if (act?.contains("/") == true) {
                                intent = Intent()
                                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                val componentName = ComponentName.unflattenFromString(act)
                                intent.component = componentName
                            } else {
                                //找不到? 网上的做法都是跳转到设置... 这基本上是没意义的 基本上自启动这个功能是第三方厂商自己写的安全管家类app
                                //所以我是直接跳转到对应的安全管家/安全中心
                                intent = act?.let { context.packageManager.getLaunchIntentForPackage(it) }
                            }
                            context.startActivity(intent)
                            has = true
                            break
                        } catch (e: Exception) {
                            e.printStackTrace()
                            Log.e("Util", "******************e:" + e.message)
                        }
                    }
                }
            }
        }
        if (!has) {
            // 【已改造】所有候选入口都没命中时。
            //
            // 原来只是弹个「请自行设置」的 toast 就跳去应用详情页 —— 用户根本不知道
            // 该点哪一步，而自启动又是保活的关键环节，含糊不得。
            // 现在改成弹窗，把该机型专属的手动路径写清楚（getAutoStartTips 按品牌给文案），
            // 用户可以选择照做，或者让它带你去应用设置页。
            val goAppDetail = {
                try {
                    val intent = Intent()
                    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    intent.action = "android.settings.APPLICATION_DETAILS_SETTINGS"
                    intent.data = Uri.fromParts("package", context.packageName, null)
                    context.startActivity(intent)
                } catch (e: Exception) {
                    e.printStackTrace()
                    Log.e("Util", "打开应用详情页失败: " + e.message)
                    try {
                        val intent = Intent(Settings.ACTION_SETTINGS)
                        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        context.startActivity(intent)
                    } catch (e2: Exception) {
                        Log.e("Util", "连系统设置都打不开: " + e2.message)
                    }
                }
            }

            val tips = getAutoStartTips()
            val shown = try {
                MaterialDialog.Builder(context)
                    .title(R.string.auto_start_dialog_title)
                    .content(tips + "\n\n" + context.getString(R.string.auto_start_dialog_hint))
                    .positiveText(R.string.auto_start_dialog_go)
                    .onPositive { _: MaterialDialog?, _: DialogAction? -> goAppDetail() }
                    .negativeText(R.string.auto_start_dialog_ok)
                    .cancelable(true)
                    .show()
                true
            } catch (e: Exception) {
                // 弹窗失败（比如 context 不是 Activity）就退回原来的做法
                Log.e("Util", "显示自启动指引弹窗失败: " + e.message)
                false
            }
            if (!shown) {
                XToastUtils.info(R.string.tips_compatible_solution)
                goAppDetail()
            }
        }
    }

    //初始化APP下拉列表
    private fun initAppSpinner() {

        //未开启异步获取已安装App信息开关时，不显示已安装APP下拉框
        if (!SettingUtils.enableLoadAppList) return

        if (App.UserAppList.isEmpty() && App.SystemAppList.isEmpty()) {
            //XToastUtils.info(getString(R.string.loading_app_list))
            val request = OneTimeWorkRequestBuilder<LoadAppListWorker>().build()
            WorkManager.getInstance(XUtil.getContext()).enqueue(request)
            return
        }

        appListSpinnerList.clear()
        if (SettingUtils.enableLoadUserAppList) {
            for (appInfo in App.UserAppList) {
                if (TextUtils.isEmpty(appInfo.packageName)) continue
                appListSpinnerList.add(AppListAdapterItem(appInfo.name, appInfo.icon, appInfo.packageName))
            }
        }
        if (SettingUtils.enableLoadSystemAppList) {
            for (appInfo in App.SystemAppList) {
                if (TextUtils.isEmpty(appInfo.packageName)) continue
                appListSpinnerList.add(AppListAdapterItem(appInfo.name, appInfo.icon, appInfo.packageName))
            }
        }

        //列表为空也不显示下拉框
        if (appListSpinnerList.isEmpty()) return

        appListSpinnerAdapter = AppListSpinnerAdapter(appListSpinnerList).setIsFilterKey(true).setFilterColor("#EF5362").setBackgroundSelector(R.drawable.selector_custom_spinner_bg)
        binding!!.spApp.setAdapter(appListSpinnerAdapter)
        binding!!.spApp.setOnItemClickListener { _: AdapterView<*>, _: View, position: Int, _: Long ->
            try {
                val appInfo = appListSpinnerAdapter.getItemSource(position) as AppListAdapterItem
                CommonUtils.insertOrReplaceText2Cursor(binding!!.etAppList, appInfo.packageName.toString() + "\n")
            } catch (e: Exception) {
                XToastUtils.error(e.message.toString())
            }
        }
        binding!!.layoutSpApp.visibility = View.VISIBLE

    }


    // ==================== 【新增】权限授权 ====================

    /** 普通运行时权限：点击开关即申请；已授予则显示为开。权限无法由代码撤销，故点"关"无意义，保持开。 */
    private fun setupPermissionSwitch(sb: SwitchButton, perms: Array<IPermission>) {
        var updating = false
        fun refresh() {
            updating = true
            sb.isChecked = XXPermissions.isGrantedPermissions(requireContext(), perms.toList())
            updating = false
        }
        refresh()
        sb.setOnCheckedChangeListener { _: CompoundButton?, isChecked: Boolean ->
            if (updating) return@setOnCheckedChangeListener
            if (!isChecked) {
                updating = true
                sb.isChecked = true
                updating = false
                return@setOnCheckedChangeListener
            }
            val builder = XXPermissions.with(this)
            perms.forEach { builder.permission(it) }
            builder
                .request(object : OnPermissionCallback {
                    override fun onResult(grantedList: MutableList<IPermission>, deniedList: MutableList<IPermission>) {
                        refresh()
                        if (deniedList.isNotEmpty()) {
                            XXPermissions.startPermissionActivity(requireContext(), deniedList)
                        }
                    }
                })
        }
    }

    /** 通知使用权：必须跳系统设置页授权 */
    private fun setupNotificationAccessSwitch(sb: SwitchButton) {
        var updating = false
        fun refresh() {
            updating = true
            sb.isChecked = CommonUtils.isNotificationListenerServiceEnabled(requireContext())
            updating = false
        }
        refresh()
        sb.setOnCheckedChangeListener { _: CompoundButton?, isChecked: Boolean ->
            if (updating) return@setOnCheckedChangeListener
            if (!isChecked) {
                updating = true
                sb.isChecked = true
                updating = false
                return@setOnCheckedChangeListener
            }
            XXPermissions.with(this)
                .permission(
                    PermissionLists.getBindNotificationListenerServicePermission(NotificationService::class.java)
                )
                .request(object : OnPermissionCallback {
                    override fun onResult(grantedList: MutableList<IPermission>, deniedList: MutableList<IPermission>) {
                        refresh()
                    }
                })
        }
    }

    /** 悬浮窗权限：Android 12 起为特殊权限，需跳「显示在其他应用上层」设置页。有此权限后 App 才能在后台启动前台服务。 */
    private fun setupOverlaySwitch(sb: SwitchButton) {
        val perm = PermissionLists.getSystemAlertWindowPermission()
        var updating = false
        fun refresh() {
            updating = true
            sb.isChecked = XXPermissions.isGrantedPermissions(requireContext(), listOf(perm))
            updating = false
        }
        refresh()
        sb.setOnCheckedChangeListener { _: CompoundButton?, isChecked: Boolean ->
            if (updating) return@setOnCheckedChangeListener
            if (!isChecked) {
                updating = true
                sb.isChecked = true
                updating = false
                return@setOnCheckedChangeListener
            }
            XXPermissions.with(this)
                .permission(perm)
                .request(object : OnPermissionCallback {
                    override fun onResult(grantedList: MutableList<IPermission>, deniedList: MutableList<IPermission>) {
                        refresh()
                    }
                })
        }
    }

}
