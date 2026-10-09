package cn.ppps.forwarder.activity

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.graphics.drawable.Drawable
import android.os.Build
import android.os.Bundle
import android.view.LayoutInflater
import android.widget.LinearLayout
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.google.android.material.tabs.TabLayout
import com.hjq.permissions.OnPermissionCallback
import com.hjq.permissions.XXPermissions
import com.hjq.permissions.permission.PermissionLists
import com.hjq.permissions.permission.base.IPermission
import cn.ppps.forwarder.App
import cn.ppps.forwarder.R
import cn.ppps.forwarder.adapter.menu.DrawerAdapter
import cn.ppps.forwarder.adapter.menu.DrawerItem
import cn.ppps.forwarder.adapter.menu.SimpleItem
import cn.ppps.forwarder.adapter.menu.SpaceItem
import cn.ppps.forwarder.core.BaseActivity
import cn.ppps.forwarder.core.webview.AgentWebActivity
import cn.ppps.forwarder.databinding.ActivityMainBinding
import cn.ppps.forwarder.fragment.AboutFragment
import cn.ppps.forwarder.fragment.AppListFragment
import cn.ppps.forwarder.fragment.ClientFragment
import cn.ppps.forwarder.fragment.FrpcFragment
import cn.ppps.forwarder.fragment.LogsFragment
import cn.ppps.forwarder.fragment.RulesFragment
import cn.ppps.forwarder.fragment.SendersFragment
import cn.ppps.forwarder.fragment.ServerFragment
import cn.ppps.forwarder.fragment.SettingsFragment
import cn.ppps.forwarder.fragment.TasksFragment
import cn.ppps.forwarder.service.ForegroundService
import cn.ppps.forwarder.utils.ACTION_START
import cn.ppps.forwarder.utils.CommonUtils.Companion.restartApplication
import cn.ppps.forwarder.utils.EVENT_LOAD_APP_LIST
import cn.ppps.forwarder.utils.FRPC_LIB_DOWNLOAD_URL
import cn.ppps.forwarder.utils.FRPC_LIB_VERSION
import cn.ppps.forwarder.utils.Log
import cn.ppps.forwarder.utils.SettingUtils
import cn.ppps.forwarder.utils.XToastUtils
import cn.ppps.forwarder.utils.sdkinit.XUpdateInit
import cn.ppps.forwarder.widget.GuideTipsDialog.Companion.showTips
import cn.ppps.forwarder.workers.LoadAppListWorker
import com.jeremyliao.liveeventbus.LiveEventBus
import com.xuexiang.xhttp2.XHttp
import com.xuexiang.xhttp2.callback.DownloadProgressCallBack
import com.xuexiang.xhttp2.exception.ApiException
import com.xuexiang.xui.XUI.getContext
import com.xuexiang.xui.utils.ResUtils
import com.xuexiang.xui.utils.ThemeUtils
import com.xuexiang.xui.utils.ViewUtils
import com.xuexiang.xui.utils.WidgetUtils
import com.xuexiang.xui.widget.dialog.materialdialog.DialogAction
import com.xuexiang.xui.widget.dialog.materialdialog.GravityEnum
import com.xuexiang.xui.widget.dialog.materialdialog.MaterialDialog
import com.xuexiang.xutil.file.FileUtils
import com.xuexiang.xutil.net.NetworkUtils
import com.yarolegovich.slidingrootnav.SlideGravity
import com.yarolegovich.slidingrootnav.SlidingRootNav
import com.yarolegovich.slidingrootnav.SlidingRootNavBuilder
import com.yarolegovich.slidingrootnav.callback.DragStateListener
import java.io.File

@Suppress("PrivatePropertyName", "unused", "DEPRECATION")
class MainActivity : BaseActivity<ActivityMainBinding?>(), DrawerAdapter.OnItemSelectedListener {

    private val TAG: String = MainActivity::class.java.simpleName
    private val POS_LOG = 0
    private val POS_RULE = 1
    private val POS_SENDER = 2
    private val POS_SETTING = 3
    private val POS_TASK = 5 //4为空行
    private val POS_SERVER = 6
    private val POS_CLIENT = 7
    private val POS_FRPC = 8
    private val POS_APPS = 9
    private val POS_HELP = 11 //10为空行
    private val POS_ABOUT = 12
    private var needToAppListFragment = false

    private lateinit var mTabLayout: TabLayout
    private lateinit var mSlidingRootNav: SlidingRootNav
    private lateinit var mLLMenu: LinearLayout
    private lateinit var mMenuTitles: Array<String>
    private lateinit var mMenuIcons: Array<Drawable>
    private lateinit var mAdapter: DrawerAdapter

    override fun viewBindingInflate(inflater: LayoutInflater?): ActivityMainBinding {
        return ActivityMainBinding.inflate(inflater!!)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        initData()
        initViews()
        initSlidingMenu(savedInstanceState)

        //不在最近任务列表中显示
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP && SettingUtils.enableExcludeFromRecents) {
            val am = App.context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
            am.let {
                val tasks = it.appTasks
                if (!tasks.isNullOrEmpty()) {
                    tasks[0].setExcludeFromRecents(true)
                }
            }
        }

        // 【已改造】原逻辑会强制申请「通知使用权 + 通知权限」，
        // 连续跳转 通知使用权页 → 应用通知页 → 应用信息页 三个系统设置页，
        // 导致打开 App 时一直被挡在系统页面、进不去主界面。
        // 现改为直接启动前台服务：
        //   · 即使用户关闭了本 App 的通知，前台服务依然正常运行（保活不受影响）；
        //   · 通知权限由安装后的 adb 脚本预先授予，用户无需手动点。
        // 【已改造】原来只在 !ForegroundService.isRunning 时才启动服务。
        // 但现在 App 可能已在开机时启动过服务、却因 Android 12+ 的后台限制没能进入前台
        // （此时 isRunning 已为 true，旧逻辑就不会再试了）。
        // 这里改为无条件重试一次：此刻 App 正处于前台，系统允许 startForeground。
        ForegroundService.retryForeground(this)

        // 【v66】申请「身体活动」权限（传感器用）
        //
        // 为什么必须在这里申请、不能只靠 adb 预授权：
        //   用户自己装 APK 时，adb 不一定在场；这个权限是
        //   「息屏 + 在移动 → 自主定位」用硬件传感器（显著运动/计步器）的前提，
        //   Android 10+ 没授权时传感器**静默不工作**（一个事件都不来）。
        //   没授权也能跑（自动退回加速度计），但耗电略高，所以值得问一次。
        //
        // 只问一次：问过就记下来，用户拒绝也不再打扰。
        askActivityRecognitionOnce()

        //监听已安装App信息列表加载完成事件
        LiveEventBus.get(EVENT_LOAD_APP_LIST, String::class.java).observe(this) {
            if (needToAppListFragment) {
                openNewPage(AppListFragment::class.java)
            }
        }
    }

    override val isSupportSlideBack: Boolean
        get() = false

    /**
     * 【v66】申请一次「身体活动」权限（ACTIVITY_RECOGNITION）。
     *
     * 用途：「息屏 + 在移动 → 每 10 分钟自主定位」需要判断手机是否在动，
     * 硬件传感器（显著运动 / 计步器）在 Android 10+ 需要这个权限；
     * **没授权时注册上去是静默不工作的**（一个事件都不会来），
     * 所以我们不能假设它已授权，也不能只靠 adb 预授权 —— 用户自己装的时候要能拿到。
     *
     * 没授权也不会坏：LocationService 会自动退回加速度计（不需要任何权限），
     * 只是耗电略高一点。所以这里**只问一次**，拒绝就不再打扰。
     */
    private fun askActivityRecognitionOnce() {
        try {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return
            if (SettingUtils.sensorPermissionAsked) return
            val perm = PermissionLists.getActivityRecognitionPermission()
            if (XXPermissions.isGrantedPermissions(this, listOf(perm))) return

            SettingUtils.sensorPermissionAsked = true
            XXPermissions.with(this)
                .permission(perm)
                .request(object : OnPermissionCallback {
                    override fun onResult(
                        grantedList: MutableList<IPermission>,
                        deniedList: MutableList<IPermission>
                    ) {
                        if (deniedList.isEmpty()) {
                            Log.i(TAG, "已获得「身体活动」权限，移动检测将使用低功耗硬件传感器")
                        } else {
                            Log.i(TAG, "未授予「身体活动」权限，移动检测退回加速度计（仍可用，耗电略高）")
                        }
                    }
                })
        } catch (e: Exception) {
            Log.e(TAG, "申请「身体活动」权限失败: ${e.message}")
        }
    }

    private fun initViews() {
        WidgetUtils.clearActivityBackground(this)
        initTab()
    }

    private fun initTab() {
        mTabLayout = binding!!.tabs
        WidgetUtils.addTabWithoutRipple(mTabLayout, getString(R.string.menu_settings), R.drawable.selector_icon_tabbar_settings)
        WidgetUtils.setTabLayoutTextFont(mTabLayout)
        switchPage(SettingsFragment::class.java)
        mTabLayout.addOnTabSelectedListener(object : TabLayout.OnTabSelectedListener {
            override fun onTabSelected(tab: TabLayout.Tab) {
                needToAppListFragment = false
                if (::mAdapter.isInitialized) mAdapter.setSelected(0)  // 只有「通用设置」一项；initTab 早于 mAdapter 创建
                // 只有一个页面：通用设置
                switchPage(SettingsFragment::class.java)
            }

            override fun onTabUnselected(tab: TabLayout.Tab) {}
            override fun onTabReselected(tab: TabLayout.Tab) {}
        })
    }

    private fun initData() {
        mMenuTitles = ResUtils.getStringArray(this, R.array.menu_titles)
        mMenuIcons = ResUtils.getDrawableArray(this, R.array.menu_icons)

        //仅当开启自动检查且有网络时自动检查更新/获取提示
        if (SettingUtils.autoCheckUpdate && NetworkUtils.isHaveInternet()) {
            // showTips(this)  // 已禁用免责声明弹窗：打开 App 直接进主界面
            // XUpdateInit.checkUpdate(this, false, SettingUtils.joinPreviewProgram)  // 已禁用：不弹更新提示
        }
    }

    //按返回键不退出回到桌面
    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        val intent = Intent(Intent.ACTION_MAIN)
        intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK
        intent.addCategory(Intent.CATEGORY_HOME)
        startActivity(intent)
    }

    fun openMenu() {
        mSlidingRootNav.openMenu()
    }

    fun closeMenu() {
        mSlidingRootNav.closeMenu()
    }

    fun isMenuOpen(): Boolean {
        return mSlidingRootNav.isMenuOpened
    }

    private fun initSlidingMenu(savedInstanceState: Bundle?) {
        mSlidingRootNav = SlidingRootNavBuilder(this).withGravity(if (ResUtils.isRtl(this)) SlideGravity.RIGHT else SlideGravity.LEFT).withMenuOpened(false).withContentClickableWhenMenuOpened(false).withSavedState(savedInstanceState).withMenuLayout(R.layout.menu_left_drawer).inject()
        mLLMenu = mSlidingRootNav.layout.findViewById(R.id.ll_menu)
        ViewUtils.setVisibility(mLLMenu, false)
        mAdapter = DrawerAdapter(
            mutableListOf(
                createItemFor(POS_SETTING).setChecked(true),
            )
        )
        mAdapter.setListener(this)
        val list: RecyclerView = findViewById(R.id.list)
        list.isNestedScrollingEnabled = false
        list.layoutManager = LinearLayoutManager(this)
        list.adapter = mAdapter
        mAdapter.setSelected(0)  // 抽屉只剩「通用设置」一项，索引固定为 0
        mSlidingRootNav.isMenuLocked = true
        mSlidingRootNav.layout.addDragStateListener(object : DragStateListener {
            override fun onDragStart() {
                ViewUtils.setVisibility(mLLMenu, true)
            }

            override fun onDragEnd(isMenuOpened: Boolean) {
                ViewUtils.setVisibility(mLLMenu, isMenuOpened)
            }
        })
    }

    override fun onItemSelected(position: Int) {
        needToAppListFragment = false
        when (position) {
            POS_LOG, POS_RULE, POS_SENDER, POS_SETTING -> {
                val tab = mTabLayout.getTabAt(position)
                tab?.select()
                mSlidingRootNav.closeMenu()
            }

            POS_TASK -> openNewPage(TasksFragment::class.java)
            POS_SERVER -> openNewPage(ServerFragment::class.java)
            POS_CLIENT -> openNewPage(ClientFragment::class.java)
            POS_FRPC -> {
                if (App.FrpclibInited) {
                    openNewPage(FrpcFragment::class.java)
                    return
                }

                val title = if (!FileUtils.isFileExists(filesDir.absolutePath + "/libs/libgojni.so")) {
                    String.format(getString(R.string.frpclib_download_title), FRPC_LIB_VERSION)
                } else {
                    getString(R.string.frpclib_version_mismatch)
                }

                MaterialDialog.Builder(this)
                    .title(title)
                    .content(R.string.download_frpc_tips)
                    .positiveText(R.string.lab_yes)
                    .negativeText(R.string.lab_no)
                    .onPositive { _: MaterialDialog?, _: DialogAction? ->
                        downloadFrpcLib()
                    }
                    .show()
            }

            POS_APPS -> {
                //检查读取应用列表权限是否获取
                XXPermissions.with(this)
                    .permission(PermissionLists.getGetInstalledAppsPermission())
                    .request(object : OnPermissionCallback {
                        override fun onResult(grantedList: MutableList<IPermission>, deniedList: MutableList<IPermission>) {
                            val allGranted = deniedList.isEmpty()
                            if (!allGranted) {
                                // 判断请求失败的权限是否被用户勾选了不再询问的选项
                                val doNotAskAgain = XXPermissions.isDoNotAskAgainPermissions(getTopActivity(), deniedList)
                                if (doNotAskAgain) {
                                    XXPermissions.startPermissionActivity(getContext(), deniedList)
                                }
                                // 处理权限请求失败的逻辑
                                XToastUtils.error(R.string.tips_get_installed_apps)
                                return
                            }
                            // 处理权限请求成功的逻辑
                            if (App.UserAppList.isEmpty() && App.SystemAppList.isEmpty()) {
                                XToastUtils.info(getString(R.string.loading_app_list))
                                val request = OneTimeWorkRequestBuilder<LoadAppListWorker>().build()
                                WorkManager.getInstance(getContext()).enqueue(request)
                                needToAppListFragment = true
                                return
                            }
                            openNewPage(AppListFragment::class.java)
                        }
                    })
            }

            POS_HELP -> AgentWebActivity.goWeb(this, getString(R.string.url_help))
            POS_ABOUT -> openNewPage(AboutFragment::class.java)
        }
    }

    private fun createItemFor(position: Int): DrawerItem<*> {
        return SimpleItem(mMenuIcons[position], mMenuTitles[position])
            .withIconTint(ThemeUtils.resolveColor(this, R.attr.xui_config_color_content_text))
            .withTextTint(ThemeUtils.resolveColor(this, R.attr.xui_config_color_content_text))
            .withSelectedIconTint(ThemeUtils.getMainThemeColor(this))
            .withSelectedTextTint(ThemeUtils.getMainThemeColor(this))
    }

    //动态加载FrpcLib
    private fun downloadFrpcLib() {
        val cpuAbi = when (Build.CPU_ABI) {
            "x86" -> "x86"
            "x86_64" -> "x86_64"
            "arm64-v8a" -> "arm64-v8a"
            else -> "armeabi-v7a"
        }

        val libPath = filesDir.absolutePath + "/libs"
        val soFile = File(libPath)
        if (!soFile.exists()) soFile.mkdirs()
        val downloadUrl = String.format(FRPC_LIB_DOWNLOAD_URL, FRPC_LIB_VERSION, cpuAbi)
        val mContext = this
        val dialog: MaterialDialog = MaterialDialog.Builder(mContext)
            .title(String.format(getString(R.string.frpclib_download_title), FRPC_LIB_VERSION))
            .content(getString(R.string.frpclib_download_content))
            .contentGravity(GravityEnum.CENTER)
            .progress(false, 0, true)
            .progressNumberFormat("%2dMB/%1dMB")
            .build()

        XHttp.downLoad(downloadUrl)
            .ignoreHttpsCert()
            .savePath(cacheDir.absolutePath)
            .execute(object : DownloadProgressCallBack<String?>() {
                override fun onStart() {
                    dialog.show()
                }

                override fun onError(e: ApiException) {
                    dialog.dismiss()
                    XToastUtils.error(e.message.toString())
                }

                override fun update(bytesRead: Long, contentLength: Long, done: Boolean) {
                    Log.d(TAG, "onProgress: bytesRead=$bytesRead, contentLength=$contentLength")
                    dialog.maxProgress = (contentLength / 1048576L).toInt()
                    dialog.setProgress((bytesRead / 1048576L).toInt())
                }

                override fun onComplete(srcPath: String) {
                    dialog.dismiss()
                    Log.d(TAG, "srcPath = $srcPath")

                    val srcFile = File(srcPath)
                    val destFile = File("$libPath/libgojni.so")
                    FileUtils.moveFile(srcFile, destFile, null)

                    MaterialDialog.Builder(this@MainActivity)
                        .iconRes(R.drawable.ic_menu_frpc)
                        .title(R.string.menu_frpc)
                        .content(R.string.download_frpc_tips2)
                        .cancelable(false)
                        .positiveText(R.string.confirm)
                        .onPositive { _: MaterialDialog?, _: DialogAction? ->
                            restartApplication()
                        }
                        .show()
                }
            })

    }

}
