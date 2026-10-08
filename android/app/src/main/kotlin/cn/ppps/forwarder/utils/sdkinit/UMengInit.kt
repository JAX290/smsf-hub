package cn.ppps.forwarder.utils.sdkinit

import android.app.Application
import android.content.Context
import cn.ppps.forwarder.App
import cn.ppps.forwarder.BuildConfig
import cn.ppps.forwarder.utils.SettingUtils.Companion.isAgreePrivacy
//import com.meituan.android.walle.WalleChannelReader
import com.umeng.analytics.MobclickAgent
import com.umeng.commonsdk.UMConfigure
import com.xuexiang.xui.XUI

/**
 * UMeng 统计 SDK初始化
 *
 * @author xuexiang
 * @since 2019-06-18 15:49
 */
class UMengInit private constructor() {
    companion object {
        private const val DEFAULT_CHANNEL_ID = "github"
        /**
         * 初始化SDK,合规指南【先进行预初始化，如果用户隐私同意后可以初始化UmengSDK进行信息上报】
         *
         * 【v62 数据精简 / 隐私】这里**永远不初始化**。
         *
         * 为什么不删掉这个类：调用点（各种 BaseFragment 等）还在，删了要动很多文件；
         * 让它变成一个空实现，效果一样而且风险最小。
         *
         * 为什么要禁：
         *   这是个要「隐蔽」的 App，而友盟统计会把设备信息/页面埋点上报到第三方服务器，
         *   既多一份隐私暴露面，又是一条可被识别的外部流量特征。
         *   实测装了厂商原始 **release** 包的那台手机，files/ 里留下了
         *   `.umeng/`、`um_ncc_local_config`、`umeng_it.cache`、`files/exid.dat` 等一串它的文件。
         *   （我们编的 debug 包因为下面原来那句 isDebug 判断本来就不会初始化，
         *     但 release 包会 —— 所以要在代码层彻底关掉。）
         */
        @JvmOverloads
        fun init(context: Context = XUI.getContext()) {
            // 故意什么都不做（见上面的说明），别"顺手"把它恢复回去。
            return
        }

        /**
         * 初始化SDK,合规指南【先进行预初始化，如果用户隐私同意后可以初始化UmengSDK进行信息上报】
         */
        private fun initApplication(application: Application?) {
            // 运营统计数据调试运行时不初始化
            if (App.isDebug) {
                return
            }
            UMConfigure.setLogEnabled(false)
            UMConfigure.preInit(application, BuildConfig.APP_ID_UMENG, DEFAULT_CHANNEL_ID) //getChannel(application)
            // 用户同意了隐私协议
            if (isAgreePrivacy) {
                realInit(application)
            }
        }

        /**
         * 真实的初始化UmengSDK【进行设备信息的统计上报，必须在获得用户隐私同意后方可调用】
         */
        private fun realInit(application: Application?) {
            // 运营统计数据调试运行时不初始化
            if (App.isDebug) {
                return
            }
            //初始化组件化基础库, 注意: 即使您已经在AndroidManifest.xml中配置过appkey和channel值，也需要在App代码中调用初始化接口（如需要使用AndroidManifest.xml中配置好的appkey和channel值，UMConfigure.init调用中appkey和channel参数请置为null）。
            //第二个参数是appkey，最后一个参数是pushSecret
            //这里BuildConfig.APP_ID_UMENG是根据local.properties中定义的APP_ID_UMENG生成的，只是运行看效果的话，可以不初始化该SDK
            UMConfigure.init(
                application,
                BuildConfig.APP_ID_UMENG,
                DEFAULT_CHANNEL_ID, //getChannel(application)
                UMConfigure.DEVICE_TYPE_PHONE,
                ""
            )
            //统计SDK是否支持采集在子进程中打点的自定义事件，默认不支持
            //支持多进程打点
            UMConfigure.setProcessEvent(true)
            MobclickAgent.setPageCollectionMode(MobclickAgent.PageMode.AUTO)
        }

        /**
         * 获取渠道信息
         */
        //private fun getChannel(context: Context?): String {
        //    return WalleChannelReader.getChannel(context!!, DEFAULT_CHANNEL_ID)
        //}
    }

    init {
        throw UnsupportedOperationException("u can't instantiate me...")
    }
}