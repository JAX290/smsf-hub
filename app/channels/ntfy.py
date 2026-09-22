"""ntfy —— 可自建的开源推送。"""
from __future__ import annotations

from typing import Sequence

import httpx

from ..models import Incoming
from .base import Channel, render_items, render_title


class Ntfy(Channel):
    name = "ntfy"
    display = "ntfy 推送"

    async def send(self, items: Sequence[Incoming], device: str = "") -> tuple[bool, str]:
        topic = self.cfg.get("topic", "").strip()
        if not topic:
            return False, "未配置 topic"
        server = self.cfg.get("server", "https://ntfy.sh").rstrip("/")
        headers = {"Title": render_title(items, device).encode("utf-8").decode("latin-1", "ignore")}
        token = self.cfg.get("token", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post(f"{server}/{topic}",
                               content=render_items(items, chr(10) + chr(10)).encode("utf-8"),
                               headers=headers)
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code} {r.text[:150]}"
        return True, "ok"
