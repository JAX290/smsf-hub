"""渠道基类 + 消息渲染。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterable, Sequence

from ..models import Incoming, TYPE_LABEL

# 规则里「类型」的写法容错：手机上叫 app，服务端叫 notify，两种都认
TYPE_ALIAS = {
    "sms": "sms", "短信": "sms", "短消息": "sms",
    "call": "call", "来电": "call", "电话": "call", "通话": "call",
    "app": "notify", "notify": "notify", "通知": "notify", "应用通知": "notify",
    "location": "location", "定位": "location", "位置": "location",
    "sent": "sent", "已发送": "sent", "发送": "sent",
}


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


def split_rule(value) -> list:
    """把规则字段拆成关键词列表。逗号（中英文）分隔，去空白。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        parts = [str(v) for v in value]
    else:
        s = str(value).replace("，", ",").replace(";", ",").replace("；", ",")
        parts = s.split(",")
    return [p.strip() for p in parts if p and p.strip()]


def _hit(keywords: Sequence[str], candidates: Sequence[str]) -> bool:
    """任一候选里包含任一关键词就算命中（不区分大小写）。"""
    if not keywords:
        return True
    cand = [str(c or "").lower() for c in candidates]
    for kw in keywords:
        k = kw.lower()
        for c in cand:
            if k and k in c:
                return True
    return False


class Channel(ABC):
    """所有推送渠道的基类。

    子类需要覆盖：
        name      —— 配置里的键名（渠道类型）
        display   —— 面板上显示的中文名
        send()    —— 实际发送

    一个渠道类型可以有好几个实例（面板上的「终端」），每个实例有自己的
    cfg、自己的 id/label，以及自己的转发规则 rules。
    """

    name: str = "base"
    display: str = "未知渠道"

    def __init__(self, cfg: dict, app_cfg):
        self.cfg = cfg or {}
        self.app_cfg = app_cfg
        self.inst_id: str = str(self.cfg.get("id") or "")
        self.inst_label: str = str(self.cfg.get("label") or "")
        rules = self.cfg.get("rules")
        self.rules: dict = rules if isinstance(rules, dict) else {}

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("enable"))

    @property
    def title(self) -> str:
        """面板/日志里区分同一类型的多个终端。"""
        return f"{self.display} · {self.inst_label}" if self.inst_label else self.display

    # ---------- 转发规则 ----------

    def accepts(self, item: Incoming) -> bool:
        """这条消息该不该发到这个终端。四个规则都通过才发；留空 = 不限制。"""
        if not self._match_tier(item):
            return False
        if not self._match_type(item):
            return False
        if not _hit(split_rule(self.rules.get("apps")),
                    [item.app, item.title, item.sender]):
            return False
        if not _hit(split_rule(self.rules.get("devices")),
                    [item.device, item.device_key, str(item.raw.get("_device_raw") or "")]):
            return False
        return True

    def _match_tier(self, item: Incoming) -> bool:
        """按消息分级过滤：低于 min_tier 的不推。

        默认门槛取 config.yaml 的 priority.min_push_tier（3 = 重要及以上），
        某个终端也可以用自己的 min_tier 覆盖它 —— 比如「全部消息」终端设 0。
        """
        if not self.app_cfg.get("priority.enable", True):
            return True
        want = self.rules.get("min_tier")
        if want in (None, ""):
            want = self.app_cfg.get("priority.min_push_tier", 3)
        try:
            want = int(want)
        except (TypeError, ValueError):
            return True
        if want <= 0:
            return True
        tier = getattr(item, "tier", -1)
        if tier is None or tier < 0:
            return True          # 没算过就不拦，避免误伤
        return int(tier) >= want

    def _match_type(self, item: Incoming) -> bool:
        wanted = split_rule(self.rules.get("types"))
        if not wanted:
            return True
        actual = TYPE_ALIAS.get(str(item.type or "").lower(), str(item.type or "").lower())
        for w in wanted:
            if TYPE_ALIAS.get(w.lower(), w.lower()) == actual:
                return True
        return False

    def filter_items(self, items: Sequence[Incoming]) -> list:
        """从一批消息里挑出本终端要发的那些。"""
        if not self.rules:
            return list(items)
        return [m for m in items if self.accepts(m)]

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
