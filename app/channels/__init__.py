"""渠道注册表：把 channels.yaml 里的「终端」实例化出来。"""
from __future__ import annotations

import logging
from typing import Sequence

from .. import channel_store
from ..models import Incoming
from .base import Channel, render_items, render_title
from .archive_only import ArchiveOnly
from .bark import Bark
from .dingtalk import DingtalkRobot
from .feishu import FeishuRobot
from .gotify import Gotify
from .ntfy import Ntfy
from .pushplus import Pushplus
from .serverchan import Serverchan
from .smtp import SmtpMail
from .telegram import Telegram
from .webhook import Webhook
from .wecom import WecomAgent, WecomRobot

log = logging.getLogger("smsf-hub.channels")

# 顺序即面板上的显示顺序
CHANNEL_CLASSES = [
    WecomRobot, WecomAgent,
    DingtalkRobot,
    FeishuRobot,
    Telegram,
    Bark,
    Ntfy,
    Gotify,
    Pushplus,
    Serverchan,
    SmtpMail,
    Webhook,
    ArchiveOnly,
]

CHANNEL_NAMES = [c.name for c in CHANNEL_CLASSES]
CHANNEL_BY_NAME = {c.name: c for c in CHANNEL_CLASSES}


def build_channels(app_cfg) -> list:
    """按 channels.yaml 构造启用的渠道实例。

    同一个渠道类型可以有好几个实例（终端），所以这里是一个双层循环：
    先按类型顺序，再按该类型下的终端顺序。
    """
    data = channel_store.load(app_cfg)
    out = []
    for cls in CHANNEL_CLASSES:
        for inst in (data.get(cls.name) or []):
            if not isinstance(inst, dict):
                continue
            try:
                ch = cls(dict(inst), app_cfg)
            except Exception:
                log.exception("渠道 %s 的终端 %s 初始化失败", cls.name, inst.get("id"))
                continue
            if ch.enabled:
                out.append(ch)
    return out


async def dispatch(channels: Sequence, items: Sequence[Incoming], device: str = "") -> list:
    """把一批消息发给所有启用的终端，返回每个终端的结果。

    每个终端可以先用自己的转发规则把 items 筛一遍 —— 筛完没剩东西就跳过，
    不产生一次无意义的外发请求。
    """
    results = []
    for ch in channels:
        subset = ch.filter_items(items)
        if not subset:
            results.append({"channel": ch.name, "instance": ch.inst_id,
                            "display": ch.title, "ok": True, "skipped": True,
                            "info": "按转发规则跳过（这批消息都不匹配）"})
            continue
        try:
            ok, info = await ch.send(subset, device)
        except Exception as exc:
            ok, info = False, f"{type(exc).__name__}: {exc}"
        results.append({"channel": ch.name, "instance": ch.inst_id,
                        "display": ch.title, "ok": ok, "info": info})
        if ok:
            log.info("推送成功 %s (%d 条)", ch.title, len(subset))
        else:
            log.warning("推送失败 %s: %s", ch.title, info)
    return results


__all__ = ["Channel", "CHANNEL_CLASSES", "CHANNEL_NAMES", "CHANNEL_BY_NAME",
           "build_channels", "dispatch", "render_items", "render_title"]
