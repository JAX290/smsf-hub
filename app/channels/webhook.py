"""通用 Webhook —— 自己接其它系统用。"""
from __future__ import annotations

from typing import Sequence

import httpx

from ..models import Incoming
from .base import Channel, render_items, render_title


class Webhook(Channel):
    name = "webhook"
    display = "通用 Webhook"

    async def send(self, items: Sequence[Incoming], device: str = "") -> tuple[bool, str]:
        url = self.cfg.get("url", "").strip()
        if not url:
            return False, "未配置 url"
        method = str(self.cfg.get("method", "POST")).upper()
        first = items[0] if items else None
        mapping = {
            "[title]": render_title(items, device),
            "[content]": render_items(items, chr(10) + chr(10)),
            "[from]": first.sender if first else "",
            "[device]": device,
            "[time]": first.when.strftime("%Y-%m-%d %H:%M:%S") if first else "",
            "[count]": str(len(items)),
        }
        tpl = self.cfg.get("body_template", "")
        body = tpl
        for k, v in mapping.items():
            body = body.replace(k, v.replace("\\", "\\\\").replace('"', '\\"').replace(chr(10), "\\n"))

        headers = self.cfg.get("headers") or {}
        async with httpx.AsyncClient(timeout=20) as cli:
            if method == "GET":
                r = await cli.get(url, headers=headers)
            else:
                r = await cli.request(method, url, content=body.encode("utf-8"),
                                      headers={"Content-Type": "application/json", **headers})
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code} {r.text[:150]}"
        return True, "ok"
