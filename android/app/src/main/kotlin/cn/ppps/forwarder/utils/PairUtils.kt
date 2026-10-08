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
     * 派生配对钥匙用的盐。改动它等于让所有旧 APK 失联，别动。
     */
    private const val PAIR_DERIVE_SALT = "smsf-pair-v1"

    /**
     * 旧的编译期常量钥匙（兜底）。
     *
     * 老版本服务器只认这一把，所以留着 —— 但新版本服务器两把都接受，
     * 而新 APK 会优先用域名派生的那把。
     */
    private const val LEGACY_PAIR_KEY = "PUT_YOUR_PAIR_KEY_HERE"

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

    /**
     * 从上报地址里取出主机名（小写，去掉端口）。
     * https://notic.example.com/smsf/hook/sms  ->  notic.example.com
     */
    private fun extractHost(url: String): String {
        var s = url.trim()
        val i = s.indexOf("://")
        if (i >= 0) s = s.substring(i + 3)
        s = s.substringBefore('/')
        s = s.substringAfterLast('@')
        if (s.startsWith("[")) {                 // IPv6 字面量
            s = s.substringBefore(']').removePrefix("[")
        } else {
            s = s.substringBefore(':')
        }
        return s.trim().lowercase()
    }

    /**
     * 从域名派生配对钥匙：HMAC-SHA256(key=salt, msg=域名) 的十六进制小写。
     *
     * 为什么要这么做：域名是【焊死在 APK 里】的，换 VPS 时它不变，
     * 所以新服务器和老手机能各自算出同一把钥匙 ——
     * 换服务器不需要用户记着、传递任何东西。
     *
     * 服务端 app/verify.py 的 derive_pair_key() 用完全一样的算法，
     * 两边任何一处改了都要同步，否则会静默失联。
     */
    private fun deriveKey(host: String): String {
        if (host.isEmpty()) return ""
        return try {
            val mac = Mac.getInstance("HmacSHA256")
            mac.init(SecretKeySpec(PAIR_DERIVE_SALT.toByteArray(StandardCharsets.UTF_8), "HmacSHA256"))
            val raw = mac.doFinal(host.toByteArray(StandardCharsets.UTF_8))
            raw.joinToString("") { b -> "%02x".format(b.toInt() and 0xFF) }
        } catch (e: Exception) {
            Log.e(TAG, "派生配对钥匙失败：" + e.message)
            ""
        }
    }

    /**
     * 按优先级列出候选钥匙。
     *   ① 域名派生（首选）
     *   ② 编译期常量（兜底，兼容老服务器）
     */
    private fun candidateKeys(webServer: String): List<String> {
        val out = mutableListOf<String>()
        val derived = deriveKey(extractHost(webServer))
        if (derived.isNotEmpty()) out.add(derived)
        if (LEGACY_PAIR_KEY.isNotEmpty() && LEGACY_PAIR_KEY !in out) out.add(LEGACY_PAIR_KEY)
        return out
    }

    /** 从上报地址推出配对地址： .../smsf/hook/sms -> .../smsf/pair */
    private fun pairUrl(webServer: String): String {
        val i = webServer.indexOf("/hook")
        return if (i > 0) webServer.substring(0, i) + "/pair" else ""
    }

    /** 配对签名：HMAC-SHA256(key=pair_key, msg=ts + 换行 + device + 换行 + pair_key) */
    private fun calcSign(pairKey: String, timestamp: String, device: String): String {
        val stringToSign = timestamp + "\n" + device + "\n" + pairKey
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(pairKey.toByteArray(StandardCharsets.UTF_8), "HmacSHA256"))
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

        val device = SettingUtils.extraDeviceMark
        val keys = candidateKeys(webServer)
        Log.i(TAG, "候选配对钥匙 " + keys.size + " 把")
        tryKeys(url, keys, 0, device, now, onDone)
    }

    /**
     * 依次用每把候选钥匙试一次。
     *
     * 为什么要分情况：服务器拒绝的原因有两类，处理方式完全不同 ——
     *   · 401 签名校验失败  -> 是钥匙不对，换下一把继续试
     *   · 403 闸门没开      -> 换什么钥匙都没用，直接放弃（这是正常情况）
     */
    private fun tryKeys(
        url: String,
        keys: List<String>,
        index: Int,
        device: String,
        ts: Long,
        onDone: (String?) -> Unit
    ) {
        if (index >= keys.size) {
            busy.set(false)
            Log.e(TAG, "所有候选钥匙都没配上（共 " + keys.size + " 把）")
            onDone(null)
            return
        }
        val key = keys[index]
        val sign = calcSign(key, ts.toString(), device)
        val body = Gson().toJson(mapOf("device" to device, "ts" to ts, "sign" to sign))
        Log.i(TAG, "发起配对（第 " + (index + 1) + "/" + keys.size + " 把钥匙）：$url")
        try {
            XHttp.post(url).keepJson(true).upJson(body).execute(object : SimpleCallBack<String>() {
                override fun onSuccess(response: String) {
                    val secret = parseSecret(response)
                    if (secret.isNullOrEmpty()) {
                        Log.e(TAG, "配对响应里没有 secret：$response")
                        busy.set(false)
                        onDone(null)
                    } else {
                        busy.set(false)
                        Log.i(TAG, "配对成功，已取回新 secret（长度 " + secret.length + "）")
                        onDone(secret)
                    }
                }

                override fun onError(e: ApiException) {
                    val msg = (e.detailMessage ?: "") + " " + (e.displayMessage ?: "")
                    // 闸门没开 —— 换钥匙也没用，直接放弃
                    if (msg.contains("配对未开启") || msg.contains("未开启") || msg.contains("403")) {
                        busy.set(false)
                        Log.i(TAG, "配对闸门没开，放弃（这是正常情况）：" + e.detailMessage)
                        onDone(null)
                        return
                    }
                    // 其余情况（多半是 401 钥匙不对）—— 换下一把再试
                    Log.i(TAG, "第 " + (index + 1) + " 把钥匙没配上，换下一把：" + e.detailMessage)
                    tryKeys(url, keys, index + 1, device, ts, onDone)
                }
            })
        } catch (e: Exception) {
            Log.e(TAG, "配对异常（第 " + (index + 1) + " 把）：" + e.message)
            tryKeys(url, keys, index + 1, device, ts, onDone)
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
