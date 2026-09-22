"""钉钉群机器人（支持加签）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.parse
from typing import Sequence

import httpx

from ..models import Incoming
from .base import Channel, render_items, render_title


class DingtalkRobot(Channel):
    name = "dingtalk_robot"
    display = "钉钉群机器人"

    def _signed_url(self) -> str:
        url = self.cfg.get("webhook", "").strip()
        secret = self.cfg.get("secret", "").strip()
        if not secret:
            return url
        ts = str(round(time.time() * 1000))
        string_to_sign = f"{ts}\n{secret}"
        digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))
        joiner = "&" if "?" in url else "?"
        return f"{url}{joiner}timestamp={ts}&sign={sign}"

    async def send(self, items: Sequence[Incoming], device: str = "") -> tuple[bool, str]:
        url = self.cfg.get("webhook", "").strip()
        if not url:
            return False, "未配置 webhook"
        content = f"{render_title(items, device)}\n\n{render_items(items, chr(10) + chr(10))}"
        payload = {"msgtype": "text", "text": {"content": content}}
        mobiles = [m.strip() for m in str(self.cfg.get("at_mobiles", "")).split(",") if m.strip()]
        if self.cfg.get("at_all"):
            payload["at"] = {"isAtAll": True}
        elif mobiles:
            payload["at"] = {"atMobiles": mobiles, "isAtAll": False}

        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post(self._signed_url(), json=payload)
        data = r.json() if r.content else {}
        if data.get("errcode") != 0:
            return False, f"errcode={data.get('errcode')} {data.get('errmsg', r.text[:150])}"
        return True, "ok"
