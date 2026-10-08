"""消息分级（tier）与信息提取。

## 为什么要有这个

用户的原话：
> 各种软件的信息通知（真正通知用户的）是重要的（各种用户发来的、服务通知等等）

也就是说要区分的**不是"哪个 App"**，而是**"这条通知是不是真在通知用户"**：
- 真在通知用户：有人发消息、银行扣款、验证码、快递到了、来电 → **重要**
- 只是应用/系统在自报状态：音乐正在播放、VPN 已连接、系统正在优化、
  "短信正在后台运行"、"正在获取服务信息" → **噪音**

实测（2026-10-07 小米14，10 小时 1500 条）里 **90% 是后者**，
把面板的消息窗口挤成了 3.4 小时，真正要看的微信只有 84 条。

## 分级

| tier | 名称 | 处理 |
|---|---|---|
| 4 | 关键 | 推送 + 置顶（短信/来电/验证码/扣款…）|
| 3 | 重要 | 推送（真人消息：微信/QQ/Telegram…）|
| 2 | 普通 | 只归档不推送 |
| 1 | 次要 | 面板默认折叠 |
| 0 | 噪音 | 面板默认折叠，归档只留一行摘要 |

## 判定顺序（先命中先返回）

1. **手机端上报的通知属性**（最可靠，v53 起）
   手机端在 content 末尾追加一行 `NAT|cat=msg|ong=0|imp=3|grp=0`
   （沿用心跳 `HBT|` 的思路：WebhookUtils 会把正文套进模板，
   结构化字段会被打散，用这种可正则捞取的行格式最稳）
   - `ong=1`（常驻通知）→ 噪音
   - `cat=`（Android 通知类别）→ 查表
   - `grp=1`（群组摘要）→ 至少降一级
   - `imp=`（渠道重要度 0-5）
2. **消息类型**：短信/来电 → 关键；已发送 → 重要；定位 → 次要
3. **应用清单**：噪音应用 → 噪音；重要应用 → 重要
4. **关键词**：重要关键词 → 关键；噪音关键词 → 噪音
5. 兜底 → 普通

所有清单都能在 config.yaml 的 `priority:` 段里改，面板表单也能改。
"""
from __future__ import annotations

import re

from .models import Incoming

TIER_LABEL = {4: "关键", 3: "重要", 2: "普通", 1: "次要", 0: "噪音"}
TIER_CSS = {4: "t4", 3: "t3", 2: "t2", 1: "t1", 0: "t0"}

# ---------------------------------------------------------------- 手机端属性行

# NAT|cat=msg|ong=0|imp=3|grp=0
NAT_RE = re.compile(r"NAT\|([^\r\n]*)")


def parse_nat(content: str) -> dict:
    """从正文里捞出通知属性行，返回 {'cat':..,'ong':..,'imp':..,'grp':..}。"""
    m = NAT_RE.search(content or "")
    if not m:
        return {}
    out = {}
    for item in m.group(1).split("|"):
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        out[k.strip().lower()] = v.strip()
    return out


# Android Notification.CATEGORY_* -> tier
CATEGORY_TIER = {
    "call": 4, "missed_call": 4, "alarm": 4, "event": 4, "reminder": 4,
    "msg": 3, "message": 3, "email": 3, "social": 3,
    "promo": 2, "recommendation": 2, "news": 2, "status": 2,
    "service": 1, "progress": 1, "system": 1, "error": 3,
    "transport": 0, "navigation": 0, "workout": 0, "stopwatch": 0,
    "location_sharing": 0, "sysinfo": 0,
}

# ---------------------------------------------------------------- 默认清单

DEFAULT_IMPORTANT_APPS = [
    # 即时通讯（真人在发消息）
    "com.tencent.mm", "微信", "wechat",
    "com.tencent.mobileqq", "qq", "com.tencent.tim",
    "com.tencent.wework", "企业微信", "com.alibaba.android.rimet", "钉钉",
    "com.ss.android.lark", "飞书", "lark",
    "org.telegram.messenger", "telegram", "org.telegram.plus",
    "com.whatsapp", "org.thoughtcrime.securesms", "signal",
    "com.facebook.orca", "messenger", "com.instagram.android",
    # 银行/支付/政务
    "com.eg.android.alipaygphone", "支付宝", "com.tencent.mm.plugin", "云闪付",
    "com.unionpay", "com.icbc", "com.chinamworld.main",
]

DEFAULT_NOISE_APPS = [
    # 实测里最常见的那批"系统/工具自报状态"
    "com.android.mms",                       # "短信正在后台运行/可能导致系统卡顿"
    "com.xiaomi.simactivate.service",        # "正在获取服务信息"
    "com.mi.health",                         # "睡眠服务后台运行中"
    "com.miui.tsmclient",                    # "小米智能卡正在运行中"
    "com.xiaomi.finddevice",                 # 查找设备状态
    "com.xiaomi.market",                     # 应用市场更新提示
    "com.miui.cloudbackup",
    "com.xiaomi.mirror",
    "com.xiaomi.mi_connect_service",
    "com.android.providers.contacts",
    "com.android.vending",
    "com.android.incallui",                  # 通话界面（通话记录另有专门通道）
    "com.android.systemui",
    "com.android.deskclock",                 # 闹钟状态（事件本身另有提醒）
    # 工具类状态
    "com.follow.clash", "com.github.kr328.clash", "clash",
    "com.tailscale.ipn", "com.luna.music", "com.miui.player",
    "com.netease.cloudmusic", "com.tencent.qqmusic",
    "com.android.settings", "com.miui.securitycenter", "com.huawei.systemmanager",
]

DEFAULT_IMPORTANT_KEYWORDS = [
    "验证码", "校验码", "动态码", "短信密码", "一次性密码",
    "扣款", "转账", "支出", "收入", "退款", "收款", "还款", "账单", "消费", "到账",
    "快递", "取件", "驿站", "已签收", "派送",
    "预约", "挂号", "航班", "登机", "车次", "晚点", "检票",
    "订单", "发货", "已送达", "外卖", "配送",
    "登录", "密码", "中签", "摇号", "到期", "逾期", "提醒还款",
]

DEFAULT_NOISE_KEYWORDS = [
    "正在后台运行", "后台运行中", "正在运行中", "正在获取", "正在同步", "同步中",
    "可能导致系统卡顿", "降低待机时间", "点按关闭",
    "睡眠服务", "正在播放", "已连接", "已断开", "正在充电", "充电中",
    "点击查看更多选项", "点击可停用", "正在扫描", "正在优化", "优化中",
    "无通知", "常驻通知", "正在使用定位", "正在使用麦克风", "正在使用相机",
]

# ---------------------------------------------------------------- 运行期规则


class Priority:
    """分级规则。启动时从 config.yaml 的 priority: 段读，可热加载。"""

    def __init__(self, cfg=None):
        cfg = cfg or {}

        def _list(key, default):
            """支持两种写法：YAML 列表，或逗号分隔的字符串（面板表单用这种）。

            留空 = 用内置默认清单（这样面板上不必把几十个包名都铺出来）。
            """
            v = cfg.get(key)
            if v is None:
                return list(default)
            if isinstance(v, (list, tuple, set)):
                items = [str(x).strip() for x in v if str(x).strip()]
            else:
                s = str(v).replace("，", ",").replace("；", ",").replace(";", ",")
                items = [p.strip() for p in s.split(",") if p.strip()]
            return items or list(default)

        self.enable = bool(cfg.get("enable", True))
        self.important_apps = [x.lower() for x in _list("important_apps", DEFAULT_IMPORTANT_APPS)]
        self.noise_apps = [x.lower() for x in _list("noise_apps", DEFAULT_NOISE_APPS)]
        self.important_keywords = _list("important_keywords", DEFAULT_IMPORTANT_KEYWORDS)
        self.noise_keywords = _list("noise_keywords", DEFAULT_NOISE_KEYWORDS)
        self.min_push_tier = int(cfg.get("min_push_tier", 3) or 3)

    # -- 工具 --

    @staticmethod
    def _hit_any(needles, haystacks) -> str:
        """返回命中的那个词（便于面板显示原因），没命中返回空串。"""
        hay = [str(h or "").lower() for h in haystacks if h]
        for n in needles:
            nl = str(n).lower()
            if nl and any(nl in h for h in hay):
                return n
        return ""

    def classify(self, msg: Incoming) -> tuple[int, str]:
        """返回 (tier, 原因)。原因用于面板上显示"为什么被判定成噪音"。"""
        if not self.enable:
            return 2, "分级已关闭"

        content = msg.content or ""
        attrs = parse_nat(content)

        # ---- 1) 手机端上报的通知属性（最可靠） ----
        if attrs:
            ong = attrs.get("ong")
            if ong == "1":
                return 0, "常驻通知（系统/应用状态）"
            cat = (attrs.get("cat") or "").lower()
            if cat and cat in CATEGORY_TIER:
                tier = CATEGORY_TIER[cat]
                reason = f"通知类别={cat}"
                # 【重要】命中关键关键词的要**升级**为「关键」：
                # 验证码/扣款这类短信，很多 ROM 会以 category=msg 的通知发出来，
                # 只按类别看会停在「重要」，但用户要的是置顶（实测踩过）。
                kw = self._hit_any(self.important_keywords, [msg.title, content])
                if kw and tier < 4:
                    return 4, f"命中关键关键词「{kw}」（通知类别={cat}）"
                grp = attrs.get("grp")
                if grp == "1" and tier >= 2:
                    tier -= 1
                    reason += "（群组摘要降一级）"
                if "imp" in attrs:
                    reason += f"，渠道重要度={attrs.get('imp')}"
                return tier, reason
            if "imp" in attrs:
                try:
                    imp = int(attrs["imp"])
                except ValueError:
                    imp = -1
                if imp == 0:
                    return 0, "通知渠道被关闭（重要度 0）"
                if imp == 1:
                    return 1, f"通知渠道重要度低（{imp}）"
                if imp >= 3 and not attrs.get("cat"):
                    return 3, f"通知渠道重要度高（{imp}）"

        # ---- 2) 消息类型 ----
        if msg.type in ("sms", "call"):
            return 4, "短信/来电"
        if msg.type == "sent":
            return 3, "已发送短信"
        if msg.type == "location":
            return 1, "定位状态"
        if msg.type != "notify":
            return 2, "其它类型"

        # ---- 3) 关键关键词优先于应用清单 ----
        # 为什么要放在应用清单前面：验证码/扣款这类短信，很多 ROM 会由
        # 系统短信组件（com.android.mms，本身在噪音清单里）发一条通知出来。
        # 若先按包名判噪音，就会把真正的验证码误伤成噪音（实测踩过）。
        hay = [msg.title, content]
        kw = self._hit_any(self.important_keywords, hay)
        if kw:
            return 4, f"命中关键关键词「{kw}」"

        # ---- 4) 噪音应用 / 噪音关键词 ----
        app_raw = (msg.app or "")
        # 通知上报时包名可能被塞在 sender 里
        cand_apps = [app_raw, msg.sender]
        hit = self._hit_any(self.noise_apps, cand_apps)
        if hit:
            return 0, f"噪音应用（{hit}）"

        kw = self._hit_any(self.noise_keywords, hay)
        if kw:
            return 0, f"命中噪音关键词「{kw}」"

        # ---- 5) 重要应用 ----
        hit = self._hit_any(self.important_apps, cand_apps)
        if hit:
            return 3, f"重要应用（{hit}）"

        # ---- 6) 兜底 ----
        return 2, "普通通知"


# ---------------------------------------------------------------- 信息提取

_UID_LINE = re.compile(r"^\s*UID\s*[:：]\s*\d+\s*$", re.I)
_TS_LINE = re.compile(r"^\s*\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\s*$")
_DEVID_LINE = re.compile(r"^\s*SF-[0-9A-Fa-f]{6,16}\s*$")
_NAT_LINE = re.compile(r"^\s*NAT\|")
_HBT_LINE = re.compile(r"^\s*HBT\|")
_TITLE_LINE = re.compile(r"^\s*【(.+?)】\s*$")

# 验证码：4-8 位数字（允许中间有空格或连字符）
_CODE_RE = re.compile(r"(?<!\d)(\d{4,8})(?!\d)")
_CODE_HINT = ("验证码", "校验码", "动态码", "短信密码", "一次性密码", "code", "otp")
_AMOUNT_RE = re.compile(r"([¥￥$]\s?\d[\d,]*(?:\.\d{1,2})?|\d[\d,]*(?:\.\d{1,2})?\s?元)")
_URL_RE = re.compile(r"https?://[^\s，。；、）)】\]]+")


def extract(msg: Incoming) -> dict:
    """把手机端那套冗余模板拆成结构化字段。

    手机端模板长这样（实测）：
        com.luna.music            ← 包名，和 app 字段重复
        Lestley Pierce, ...       ← 真正的正文
        UID：10069                ← 没用
        2026-10-07 20:35:28       ← 没用（time 字段已有）
        SF-BFDE5FB748             ← 没用（device 字段已有）

    所以这里把 UID/时间/设备ID/包名重复行都丢掉，只留标题+正文，
    再顺手把验证码、金额、链接捞出来。
    """
    raw = (msg.content or "")
    lines = [ln.rstrip() for ln in raw.splitlines()]
    keep: list[str] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if _UID_LINE.match(s) or _TS_LINE.match(s) or _DEVID_LINE.match(s):
            continue
        if _NAT_LINE.match(s) or _HBT_LINE.match(s):
            continue
        # 手机端模板第一行常常是包名，与 app 字段重复
        if not keep and msg.app and s == msg.app.strip():
            continue
        if not keep and re.fullmatch(r"[a-zA-Z][\w.]{3,}", s) and "." in s:
            continue          # 形如 com.xxx.yyy 的包名
        keep.append(s)

    title = ""
    if keep:
        m = _TITLE_LINE.match(keep[0])
        if m:
            title = m.group(1).strip()
            keep = keep[1:]
    if not title:
        title = msg.title or ""
    body = "\n".join(keep).strip()

    code = ""
    blob = f"{title}\n{body}"
    if any(h in blob.lower() for h in _CODE_HINT):
        codes = _CODE_RE.findall(blob)
        # 优先 6 位（国内验证码常见），其次第一个
        code = next((c for c in codes if len(c) == 6), codes[0] if codes else "")

    amounts = _AMOUNT_RE.findall(blob)
    links = _URL_RE.findall(blob)

    summary = (body or title).replace("\n", " ").strip()
    if len(summary) > 60:
        summary = summary[:60] + "…"

    return {
        "title": title,
        "body": body,
        "summary": summary,
        "code": code,
        "amounts": amounts[:3],
        "links": links[:3],
    }


# ---------------------------------------------------------------- 模块级单例

_RULES = Priority()


def configure(cfg) -> Priority:
    """启动时 / 改完配置后调用，重建规则。"""
    global _RULES
    raw = {}
    if cfg is not None:
        try:
            raw = dict(cfg.get("priority", {}) or {})
        except Exception:
            raw = {}
    _RULES = Priority(raw)
    return _RULES


def rules() -> Priority:
    return _RULES


def classify(msg: Incoming) -> tuple[int, str]:
    return _RULES.classify(msg)
