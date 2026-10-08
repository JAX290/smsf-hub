"""上报消息的数据模型。"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# 手机端固定输出的设备 ID，形如 SF-B7AEFBF931
DEVICE_ID_RE = re.compile(r"SF-[0-9A-Fa-f]{6,16}")

# 消息类型 -> 中文目录名
TYPE_DIR = {
    "sent": "已发送",
    "sms": "短信",
    "call": "来电",
    "notify": "APP通知",
    "location": "定位",
}

TYPE_LABEL = {
    "sent": "已发送",
    "sms": "短信",
    "call": "来电",
    "notify": "通知",
    "location": "定位",
}


@dataclass
class Incoming:
    """一条手机上报的消息（归一化之后）。"""
    type: str = "sms"              # sms / call / notify
    sender: str = ""               # 发件人号码 / 来电号码
    app: str = ""                  # APP通知时的应用名
    title: str = ""                # 站点/短信标题
    content: str = ""              # 正文
    device: str = ""               # 设备备注
    app_version: str = ""
    sim: str = ""
    ts: int = 0                    # 毫秒时间戳
    # 消息分级：4 关键 / 3 重要 / 2 普通 / 1 次要 / 0 噪音；-1 表示还没算
    # 由 classify.Priority 填充，面板和推送渠道都用它做过滤。
    tier: int = -1
    tier_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def when(self) -> datetime:
        ts = self.ts or int(datetime.now().timestamp() * 1000)
        return datetime.fromtimestamp(ts / 1000.0)

    def subject(self, rule: str) -> str:
        """按配置决定归档目录里的『主题』。返回空串表示不再分一层。"""
        if rule == "none":
            return ""
        if rule == "app":
            return self.app or self.title or "未知应用"
        # 默认按发件人
        return self.sender or self.app or "未知来源"

    @property
    def device_key(self) -> str:
        """归档用的设备标识。

        优先取稳定的设备 ID（形如 SF-B7AEFBF931）—— 它在手机端模板里固定输出，
        不会因为用户后来改了「设备备注」而变化。取不到才退回备注。

        为什么不直接用 device 字段：那是用户可改的备注，历史上出现过同一台手机
        先后叫过「手机2」和「红米」，拿它当目录名会把一台机器拆成好几组。
        """
        # raw 里存的是 pipeline 保留下来的原始上报值；device 可能已被换成备注。
        raw = str(self.raw.get("_device_raw") or self.device or "").strip()
        if raw and DEVICE_ID_RE.fullmatch(raw):
            return raw.upper()
        m = DEVICE_ID_RE.search(self.content or "")
        if m:
            return m.group(0).upper()
        return raw

    def fingerprint(self) -> str:
        """去重指纹。

        含设备维度：两台手机各自收到同一条消息（比如运营商群发）时，
        应该各记一份，而不是被当成重复丢掉。同一台手机重复上报仍会被去重。
        """
        return f"{self.type}|{self.sender}|{self.app}|{self.content}|{self.device_key}"

    def merge_group(self, group_by: str) -> str:
        if group_by == "app":
            return f"{self.type}/{self.app or '未知应用'}"
        if group_by == "none":
            return "ALL"
        return f"{self.type}/{self.subject('sender')}"

    @classmethod
    def from_payload(cls, payload: dict) -> "Incoming":
        """把手机送上来的 JSON 归一化成 Incoming。

        兼容两种风格：
        1) 本项目推荐的显式字段（type/sender/app/content...）
        2) SmsForwarder 默认的 from/content/title 风格
        """
        def pick(*keys, default=""):
            for k in keys:
                v = payload.get(k)
                if v not in (None, ""):
                    return str(v)
            return default

        mtype = pick("type", "msg_type", "kind").lower()
        if mtype not in TYPE_DIR:
            mtype = "sms"

        return cls(
            type=mtype,
            sender=pick("sender", "from", "number", "phone"),
            app=pick("app", "package_name", "app_name"),
            title=pick("title", "sim", "card_slot"),
            content=pick("content", "msg", "text", "body"),
            device=pick("device", "device_mark"),
            app_version=pick("app_version", "version"),
            sim=pick("sim", "card_slot", "title"),
            ts=int(pick("ts", "timestamp", default="0") or 0),
            raw=payload,
        )
