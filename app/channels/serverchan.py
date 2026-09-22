"""Server 酱。"""
from __future__ import annotations

from typing import Sequence

import httpx

from ..models import Incoming
from .base import Channel, render_items, render_title


class Serverchan(Channel):
    name = "serverchan"
    display = "Server 酱"

    async def send(self, items: Sequence[Incoming], device: str = "") -> tuple[bool, str]:
        key = self.cfg.get("send_key", "").strip()
        if not key:
            return False, "未配置 send_key"
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post(f"https://sctapi.ftqq.com/{key}.send",
                               data={"title": render_title(items, device),
                                     "desp": render_items(items, chr(10) + chr(10))})
        data = r.json() if r.content[:1] == b"{" else {}
        if data.get("code") not in (0, None):
            return False, f"code={data.get('code')} {data.get('message', r.text[:150])}"
        return True, "ok"
