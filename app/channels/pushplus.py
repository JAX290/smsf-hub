"""PushPlus。"""
from __future__ import annotations

from typing import Sequence

import httpx

from ..models import Incoming
from .base import Channel, render_items, render_title


class Pushplus(Channel):
    name = "pushplus"
    display = "PushPlus"

    async def send(self, items: Sequence[Incoming], device: str = "") -> tuple[bool, str]:
        token = self.cfg.get("token", "").strip()
        if not token:
            return False, "未配置 token"
        payload = {
            "token": token,
            "title": render_title(items, device),
            "content": render_items(items, chr(10) + chr(10)),
            "template": "markdown",
        }
        if self.cfg.get("topic"):
            payload["topic"] = self.cfg["topic"]
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post("https://www.pushplus.plus/send", json=payload)
        data = r.json() if r.content[:1] == b"{" else {}
        if data.get("code") not in (200, None):
            return False, f"code={data.get('code')} {data.get('msg', r.text[:150])}"
        return True, "ok"
