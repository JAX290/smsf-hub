"""渠道基类 + 消息渲染。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterable, Sequence

from ..models import Incoming, TYPE_LABEL


def render_items(items: Sequence[Incoming], separator: str, max_chars: int = 3500) -> str:
    """把一批（可能是合并后的）消息渲染成一段文本。"""
    blocks = []
    for m in items:
        label = TYPE_LABEL.get(m.type, m.type)
        when = m.when.strftime("%H:%M:%S")
        head = f"[{label}] {when}"
        if m.sender:
            head += f"  {m.sender}"
        if m.app:
            head += f"  {m.app}"
        body = (m.content or "").strip()
        blocks.append(f"{head}\n{body}")
    text = separator.join(blocks)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…（内容过长已截断）"
    return text


def render_title(items: Sequence[Incoming], device: str = "") -> str:
    """给一条（或一批）消息取个标题。"""
    n = len(items)
    first = items[0] if items else None
    label = TYPE_LABEL.get(first.type, "") if first else ""
    prefix = f"[{device}] " if device else ""
    if n == 1 and first:
        who = first.sender or first.app or "未知"
        return f"{prefix}{label}来自 {who}"
    return f"{prefix}{label} 合并 {n} 条".strip()


class Channel(ABC):
    """所有推送渠道的基类。

    子类需要覆盖：
        name      —— 配置里的键名
        display   —— 面板上显示的中文名
        send()    —— 实际发送
    """

    name: str = "base"
    display: str = "未知渠道"

    def __init__(self, cfg: dict, app_cfg):
        self.cfg = cfg or {}
        self.app_cfg = app_cfg

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("enable"))

    @abstractmethod
    async def send(self, items: Sequence[Incoming], device: str = "") -> tuple[bool, str]:
        """发送一批消息。返回 (是否成功, 说明文字)。"""
        raise NotImplementedError

    def mask(self) -> dict:
        """给面板用的、抹掉敏感信息的配置快照。"""
        def hide(v):
            s = str(v)
            if len(s) <= 8:
                return "***" if s else ""
            return s[:4] + "***" + s[-4:]
        out = {}
        for k, v in self.cfg.items():
            if isinstance(v, str) and any(t in k.lower() for t in ("token", "secret", "password", "key", "webhook")):
                out[k] = hide(v)
            else:
                out[k] = v
        return out
