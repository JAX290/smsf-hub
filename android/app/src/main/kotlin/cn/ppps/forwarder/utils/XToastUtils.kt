package cn.ppps.forwarder.utils

import android.annotation.SuppressLint
import androidx.annotation.MainThread
import androidx.annotation.StringRes
import com.xuexiang.xui.XUI
import com.xuexiang.xui.widget.toast.XToast

/**
 * xtoast 工具类
 *
 * 【已改造】全局静默。
 * 本版本要求：除「通用设置」界面外，不弹出任何窗口。
 * 因此这里保留全部方法签名（全项目 400+ 处调用无需改动），
 * 但方法体不再真正弹出 Toast —— 直接 return。
 *
 * 如需恢复提示，把 SILENT 改成 false 即可。
 *
 * @author xuexiang
 * @since 2019-06-30 19:04
 */
class XToastUtils private constructor() {
    @SuppressLint("CheckResult")
    companion object {
        /** 全局静默开关：true = 不显示任何 Toast */
        private const val SILENT = true

        //======普通土司=======//
        @MainThread
        fun toast(message: CharSequence) { if (SILENT) return; XToast.normal(XUI.getContext(), message).show() }

        @MainThread
        fun toast(@StringRes message: Int) { if (SILENT) return; XToast.normal(XUI.getContext(), message).show() }

        @MainThread
        fun toast(message: CharSequence, duration: Int) { if (SILENT) return; XToast.normal(XUI.getContext(), message, duration).show() }

        @MainThread
        fun toast(@StringRes message: Int, duration: Int) { if (SILENT) return; XToast.normal(XUI.getContext(), message, duration).show() }

        //======错误【红色】=======//
        @MainThread
        fun error(throwable: Throwable) { if (SILENT) return; XToast.error(XUI.getContext(), throwable.message!!).show() }

        @MainThread
        fun error(message: CharSequence) { if (SILENT) return; XToast.error(XUI.getContext(), message).show() }

        @MainThread
        fun error(@StringRes message: Int) { if (SILENT) return; XToast.error(XUI.getContext(), message).show() }

        @MainThread
        fun error(message: CharSequence, duration: Int) { if (SILENT) return; XToast.error(XUI.getContext(), message, duration).show() }

        @MainThread
        fun error(@StringRes message: Int, duration: Int) { if (SILENT) return; XToast.error(XUI.getContext(), message, duration).show() }

        //======成功【绿色】=======//
        @MainThread
        fun success(message: CharSequence) { if (SILENT) return; XToast.success(XUI.getContext(), message).show() }

        @MainThread
        fun success(@StringRes message: Int) { if (SILENT) return; XToast.success(XUI.getContext(), message).show() }

        @MainThread
        fun success(message: CharSequence, duration: Int) { if (SILENT) return; XToast.success(XUI.getContext(), message, duration).show() }

        @MainThread
        fun success(@StringRes message: Int, duration: Int) { if (SILENT) return; XToast.success(XUI.getContext(), message, duration).show() }

        //======信息【蓝色】=======//
        @MainThread
        fun info(message: CharSequence) { if (SILENT) return; XToast.info(XUI.getContext(), message).show() }

        @MainThread
        fun info(@StringRes message: Int) { if (SILENT) return; XToast.info(XUI.getContext(), message).show() }

        @MainThread
        fun info(message: CharSequence, duration: Int) { if (SILENT) return; XToast.info(XUI.getContext(), message, duration).show() }

        @MainThread
        fun info(@StringRes message: Int, duration: Int) { if (SILENT) return; XToast.info(XUI.getContext(), message, duration).show() }

        //=======警告【黄色】======//
        @MainThread
        fun warning(message: CharSequence) { if (SILENT) return; XToast.warning(XUI.getContext(), message).show() }

        @MainThread
        fun warning(@StringRes message: Int) { if (SILENT) return; XToast.warning(XUI.getContext(), message).show() }

        @MainThread
        fun warning(message: CharSequence, duration: Int) { if (SILENT) return; XToast.warning(XUI.getContext(), message, duration).show() }

        @MainThread
        fun warning(@StringRes message: Int, duration: Int) { if (SILENT) return; XToast.warning(XUI.getContext(), message, duration).show() }

        init {
            XToast.Config.get()
                .setAlpha(200)
                .allowQueue(false)
        }
    }

    init {
        throw UnsupportedOperationException("u can't instantiate me...")
    }
}
