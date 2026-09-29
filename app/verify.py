"""校验手机上报的签名与时间戳。

签名算法（由 SmsForwarder 的 WebhookUtils.kt 源码确定，必须一致）：

    stringToSign = str(timestamp) + "\n" + secret
    raw          = HMAC_SHA256(key=secret, msg=stringToSign)
    sign         = urlencode( base64_nopad(raw) )

注意：该签名【不覆盖消息内容】，只证明发送方持有 secret。
所以必须配合 HTTPS 与时间戳时效校验使用。
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import time
from urllib.parse import unquote


def compute_sign(secret: str, timestamp: int | str) -> str:
    """本地计算签名，用于自测。返回的是未做 urlencode 的 base64。"""
    msg = f"{timestamp}\n{secret}".encode("utf-8")
    raw = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).digest()
    return base64.b64encode(raw).decode("ascii")


def verify_sign(secret: str, timestamp: int | str, sign: str) -> bool:
    """校验手机送来的 sign。先 url-decode，再常数时间比对。"""
    if not secret or not sign:
        return False
    try:
        got = unquote(str(sign))
    except Exception:
        return False
    expected = compute_sign(secret, timestamp)
    return hmac.compare_digest(got, expected)


def check_timestamp(timestamp: int | str, tolerance_seconds: int) -> tuple[bool, str]:
    """校验时间戳是否在允许范围内。返回 (是否通过, 说明)。"""
    try:
        ts_ms = int(timestamp)
    except (TypeError, ValueError):
        return False, "timestamp 不是整数"
    # 手机上送的是毫秒
    ts_s = ts_ms / 1000.0 if ts_ms > 10_000_000_000 else float(ts_ms)
    drift = abs(time.time() - ts_s)
    if drift > tolerance_seconds:
        return False, f"时间戳偏差 {drift:.0f}s 超出允许的 {tolerance_seconds}s"
    return True, "ok"


# ==============================================================================
#  配对（换服务器后自动重新绑定 secret）
# ------------------------------------------------------------------------------
#  背景：secret 存在 config.yaml 里。换 VPS 时如果这份配置没带过去，
#  新服务器会生成一个不同的 secret，手机怎么上报都会被拒 —— 以前只能手工同步。
#
#  配对签名用的是另一把钥匙 pair_key（手机端 APK 里内置同一个），
#  和上报用的 secret 相互独立：
#
#      stringToSign = f"{ts}\n{device}\n{pair_key}"
#      raw          = HMAC_SHA256(key=pair_key, msg=stringToSign)
#      sign         = urlencode(base64_nopad(raw))
#
#  比上传的 secret 签名多带一个 device 字段，这样同一份请求换个设备名就无效，
#  避免配对报文被原样重放。
# ==============================================================================


# ------------------------------------------------------------------------------
#  域名派生钥匙（换 VPS 零操作的关键）
# ------------------------------------------------------------------------------
#  问题：pair_key 是编译在 APK 里的常量，换 VPS 时新服务器必须和手机上那把一致，
#        否则手机怎么配对都是 401，表现为「静默失联」——
#        服务器这边服务 active、面板能开，极难排查。
#
#  解法：既然【域名是焊死在 APK 里的】（换 VPS 时它不变），
#        那就让域名本身参与派生钥匙。这样：
#
#            换 VPS → 域名不变 → 两边算出的钥匙自动一致 → 配对通过
#
#        用户不需要记、不需要传、不需要保管任何东西。
#
#  为什么不做成「完全不要钥匙」：
#        那样任何知道 /smsf/pair 这个路径的人，在闸门开着时都能领走 secret。
#        带上域名派生，至少需要知道你的域名 —— 门槛高得多，而代价为零。
#
#  派生串里带版本号 smsf-pair-v1，将来若要换算法，可以直接升版本平滑过渡。
# ------------------------------------------------------------------------------

PAIR_DERIVE_SALT = "smsf-pair-v1"


def extract_host(url: str) -> str:
    """从 https://a.b.c/path 里取出 a.b.c（小写，去掉端口）。

    域名大小写不敏感，统一小写后派生，避免两边因为大小写差异算不出同一个钥匙。
    """
    s = (url or "").strip()
    if not s:
        return ""
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/", 1)[0]
    s = s.split("@")[-1]          # 去掉可能存在的 user:pass@
    if s.startswith("["):         # IPv6 字面量 [::1]:8701
        s = s.split("]", 1)[0].lstrip("[")
    else:
        s = s.split(":", 1)[0]
    return s.strip().lower()


def derive_pair_key(domain: str) -> str:
    """从域名派生配对钥匙。返回 64 位十六进制，和手工配置的 pair_key 同格式。"""
    d = (domain or "").strip().lower()
    if not d:
        return ""
    raw = hmac.new(PAIR_DERIVE_SALT.encode("utf-8"), d.encode("utf-8"), hashlib.sha256).digest()
    return raw.hex()


def compute_pair_sign(pair_key: str, timestamp: int | str, device: str) -> str:
    """计算配对签名。返回未做 urlencode 的 base64（自测时用）。"""
    msg = f"{timestamp}\n{device}\n{pair_key}".encode("utf-8")
    raw = hmac.new(pair_key.encode("utf-8"), msg, hashlib.sha256).digest()
    return base64.b64encode(raw).decode("ascii")


def verify_pair_sign(pair_key: str, timestamp: int | str, device: str, sign: str) -> bool:
    """校验配对请求的签名。"""
    if not pair_key or not sign:
        return False
    try:
        got = unquote(str(sign))
    except Exception:
        return False
    expected = compute_pair_sign(pair_key, timestamp, device)
    return hmac.compare_digest(got, expected)
