"""Bark —— 推送到 iOS。"""
from __future__ import annotations

from typing import Sequence

import httpx

from ..models import Incoming
from .base import Channel, render_items, render_title


class Bark(Channel):
    name = "bark"
    display = "Bark (iOS 推送)"

    async def send(self, items: Sequence[Incoming], device: str = "") -> tuple[bool, str]:
        key = self.cfg.get("device_key", "").strip()
        if not key:
            return False, "未配置 device_key"
        server = self.cfg.get("server", "https://api.day.app").rstrip("/")
        payload = {
            "device_key": key,
            "title": render_title(items, device),
            "body": render_items(items, chr(10) + chr(10)),
        }
        for k in ("group", "sound"):
            if self.cfg.get(k):
                payload[k] = self.cfg[k]
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post(f"{server}/push", json=payload)
        data = r.json() if r.content[:1] in (b"{", b"[") else {}
        if r.status_code != 200 or data.get("code") not in (200, 0, None):
            return False, f"HTTP {r.status_code} {data.get('message', r.text[:150])}"
        return True, "ok"
