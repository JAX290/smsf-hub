"""Gotify —— 自建推送服务。"""
from __future__ import annotations

from typing import Sequence

import httpx

from ..models import Incoming
from .base import Channel, render_items, render_title


class Gotify(Channel):
    name = "gotify"
    display = "Gotify 推送"

    async def send(self, items: Sequence[Incoming], device: str = "") -> tuple[bool, str]:
        server = self.cfg.get("server", "").rstrip("/")
        token = self.cfg.get("token", "").strip()
        if not server or not token:
            return False, "未配置 server / token"
        payload = {
            "title": render_title(items, device),
            "message": render_items(items, chr(10) + chr(10)),
            "priority": int(self.cfg.get("priority", 5) or 5),
        }
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post(f"{server}/message", params={"token": token}, json=payload)
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code} {r.text[:150]}"
        return True, "ok"
