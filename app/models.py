"""上报消息的数据模型。"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# 消息类型 -> 中文目录名
TYPE_DIR = {
    "sms": "短信",
    "call": "来电",
    "notify": "APP通知",
}

TYPE_LABEL = {
    "sms": "短信",
    "call": "来电",
    "notify": "通知",
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
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def when(self) -> datetime:
        ts = self.ts or int(datetime.now().timestamp() * 1000)
        return datetime.fromtimestamp(ts / 1000.0)

    def subject(self, rule: str) -> str:
        """按配置决定归档目录里的『主题』。"""
        if rule == "app":
            return self.app or self.title or "未知应用"
        # 默认按发件人
        return self.sender or self.app or "未知来源"

    def fingerprint(self) -> str:
        return f"{self.type}|{self.sender}|{self.app}|{self.content}"

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
