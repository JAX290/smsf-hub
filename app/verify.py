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
