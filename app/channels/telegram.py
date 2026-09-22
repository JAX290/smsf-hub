"""Telegram 机器人。"""
from __future__ import annotations

from typing import Sequence

import httpx

from ..models import Incoming
from .base import Channel, render_items, render_title


class Telegram(Channel):
    name = "telegram"
    display = "Telegram 机器人"

    async def send(self, items: Sequence[Incoming], device: str = "") -> tuple[bool, str]:
        token = self.cfg.get("bot_token", "").strip()
        chat_id = str(self.cfg.get("chat_id", "")).strip()
        if not token or not chat_id:
            return False, "bot_token / chat_id 未配置"
        base = self.cfg.get("api_base", "https://api.telegram.org").rstrip("/")
        url = f"{base}/bot{token}/sendMessage"

        text = f"<b>{render_title(items, device)}</b>\n\n" + render_items(items, "\n\n")
        # HTML 模式需要转义
        text = text.replace("&", "&amp;").replace("<b>", "\x00B\x00").replace("</b>", "\x00b\x00")
        text = text.replace("<", "&lt;").replace(">", "&gt;").replace("\x00B\x00", "<b>").replace("\x00b\x00", "</b>")

        async with httpx.AsyncClient(timeout=20) as cli:
            r = await cli.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                          "disable_web_page_preview": True})
        data = r.json() if r.content else {}
        if not data.get("ok"):
            return False, f"{data.get('error_code')} {data.get('description', r.text[:150])}"
        return True, "ok"
