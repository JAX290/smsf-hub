package cn.ppps.forwarder.utils

import android.util.Base64
import cn.ppps.forwarder.core.Core
import com.google.gson.Gson
import com.google.gson.JsonParser
import com.xuexiang.xutil.XUtil
import com.xuexiang.xhttp2.XHttp
import com.xuexiang.xhttp2.callback.SimpleCallBack
import com.xuexiang.xhttp2.exception.ApiException
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.concurrent.atomic.AtomicBoolean
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * 配对：换服务器后自动重新对上 secret。
 *
 * 背景：secret 存在服务器的 config.yaml 里。换 VPS 时如果配置没带过去，
 * 新服务器会生成一个不同的 secret，本机上报全部被拒（401）—— 以前只能手工同步。
 *
 * 现在改成：上报被拒时，自动拿「配对钥匙」去问服务器要当前 secret，
 * 拿到后写回本地发送方配置并重发。服务器那边的配对闸门默认是关的，
 * 只在换服务器时临时打开，所以这把钥匙平时用不上。
 *
 * ⚠️ 改动极小、可控：只在「明确是签名不对」时才触发，其余失败一律走原有逻辑。
 */
object PairUtils {
    private const val TAG = "PairUtils"

    /**
     * 配对钥匙。必须与服务器 config.yaml 里 security.pair_key 完全一致。
     */
    private const val PAIR_KEY = "PUT_YOUR_PAIR_KEY_HERE"

    /** 同一时间只允许一次配对请求 */
    private val busy = AtomicBoolean(false)

    /** 冷却时间：失败后不要疯狂重试（服务器那边也有每分钟限速） */
    @Volatile
    private var lastAttemptAt = 0L
    private const val COOLDOWN_MS = 60000L

    /**
     * 这个错误是不是「secret 对不上、需要重新配对」。
     *
     * 只在服务端明确回「签名校验失败」时返回 true。
     * 其余（超时、404、403 闸门没开……）一律不触发，避免无谓请求。
     */
    /**
     * 这个错误是不是「secret 对不上、需要重新配对」。
     *
     * 之所以匹配多个关键字：不同版本的 XHttp2 把 HTTP 错误包装成 ApiException 后，
     * 原始文案可能落在 detailMessage / displayMessage / code / message 中的任意一个，
     * 甚至只留一个 "401"。宁可判宽一点 —— 判错时配对会失败并优雅回退到原有失败逻辑，
     * 代价只是多一次请求（还有 60 秒冷却），不会影响正常流程。
     */
    fun needsPair(vararg parts: String?): Boolean {
        val s = parts.filterNotNull().joinToString(" ")
        if (s.isEmpty()) return false
        return s.contains("签名校验失败") ||
                s.contains("配对签名") ||
                s.contains("401") ||
                s.contains("Unauthorized", ignoreCase = true)
    }

    /** 从上报地址推出配对地址： .../smsf/hook/sms -> .../smsf/pair */
    private fun pairUrl(webServer: String): String {
        val i = webServer.indexOf("/hook")
        return if (i > 0) webServer.substring(0, i) + "/pair" else ""
    }

    /** 配对签名：HMAC-SHA256(key=pair_key, msg=ts + 换行 + device + 换行 + pair_key) */
    private fun calcSign(timestamp: String, device: String): String {
        val stringToSign = timestamp + "\n" + device + "\n" + PAIR_KEY
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(PAIR_KEY.toByteArray(StandardCharsets.UTF_8), "HmacSHA256"))
        val raw = mac.doFinal(stringToSign.toByteArray(StandardCharsets.UTF_8))
        return URLEncoder.encode(String(Base64.encode(raw, Base64.NO_WRAP)), "UTF-8")
    }

    /**
     * 尝试配对。成功回调新 secret，失败回调 null。
     * 整个过程静默，不弹任何界面。
     */
    fun tryPair(webServer: String, onDone: (String?) -> Unit) {
        val url = pairUrl(webServer)
        if (url.isEmpty()) {
            onDone(null)
            return
        }
        if (!SettingUtils.enableAutoPair) {
            Log.i(TAG, "未开启自动配对，跳过")
            onDone(null)
            return
        }
        val now = System.currentTimeMillis()
        if (now - lastAttemptAt < COOLDOWN_MS) {
            Log.i(TAG, "距上次配对尝试不足 60 秒，跳过")
            onDone(null)
            return
        }
        if (!busy.compareAndSet(false, true)) {
            Log.i(TAG, "已有配对请求在进行中，跳过")
            onDone(null)
            return
        }
        lastAttemptAt = now

        try {
            val device = SettingUtils.extraDeviceMark
            val sign = calcSign(now.toString(), device)
            val body = Gson().toJson(mapOf("device" to device, "ts" to now, "sign" to sign))
            Log.i(TAG, "发起配对：$url")
            XHttp.post(url).keepJson(true).upJson(body).execute(object : SimpleCallBack<String>() {
                override fun onSuccess(response: String) {
                    busy.set(false)
                    val secret = parseSecret(response)
                    if (secret.isNullOrEmpty()) {
                        Log.e(TAG, "配对响应里没有 secret：$response")
                        onDone(null)
                    } else {
                        Log.i(TAG, "配对成功，已取回新 secret（长度 " + secret.length + "）")
                        onDone(secret)
                    }
                }

                override fun onError(e: ApiException) {
                    busy.set(false)
                    // 服务器闸门没开时这里是 403 —— 属于正常情况，不重试
                    Log.e(TAG, "配对失败：" + e.detailMessage)
                    onDone(null)
                }
            })
        } catch (e: Exception) {
            busy.set(false)
            Log.e(TAG, "配对异常：" + e.message)
            onDone(null)
        }
    }

    private fun parseSecret(response: String): String? {
        return try {
            val obj = JsonParser.parseString(response).asJsonObject
            if (obj.has("ok") && obj.get("ok").asBoolean && obj.has("secret")) {
                obj.get("secret").asString
            } else null
        } catch (e: Exception) {
            null
        }
    }

    /**
     * 把最近一次上报失败/配对情况写到 App 私有目录，方便事后排查。
     * 只保留最近 50 条，不占空间。
     */
    fun trace(text: String) {
        try {
            val dir = XUtil.getContext().getExternalFilesDir(null) ?: XUtil.getContext().filesDir
            val f = java.io.File(dir, "pair_trace.log")
            val line = java.text.SimpleDateFormat("MM-dd HH:mm:ss", java.util.Locale.getDefault())
                .format(java.util.Date()) + "  " + text
            val lines = if (f.exists()) f.readLines().takeLast(49) else emptyList()
            f.writeText((lines + line).joinToString("\n"))
        } catch (e: Exception) {
            // 忽略：排查用的日志，失败不影响主流程
        }
    }

    /**
     * 把新 secret 写回数据库里所有 Webhook 发送方。返回改动的条数。
     */
    fun updateAllSecrets(newSecret: String): Int {
        var changed = 0
        try {
            for (sender in Core.sender.getAllNonCache()) {
                if (sender.type != TYPE_WEBHOOK) continue
                try {
                    val obj = JsonParser.parseString(sender.jsonSetting).asJsonObject
                    val old = if (obj.has("secret")) obj.get("secret").asString else ""
                    if (old == newSecret) continue
                    obj.addProperty("secret", newSecret)
                    sender.jsonSetting = obj.toString()
                    Core.sender.update(sender)
                    changed++
                } catch (e: Exception) {
                    Log.e(TAG, "更新发送方 " + sender.id + " 失败：" + e.message)
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "遍历发送方失败：" + e.message)
        }
        Log.i(TAG, "已更新 " + changed + " 个发送方的 secret")
        return changed
    }
}
