"""飞书群机器人（支持加签）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Sequence

import httpx

from ..models import Incoming
from .base import Channel, render_items, render_title


class FeishuRobot(Channel):
    name = "feishu_robot"
    display = "飞书群机器人"

    def _payload(self, content: str) -> dict:
        payload = {"msg_type": "text", "content": {"text": content}}
        secret = self.cfg.get("secret", "").strip()
        if secret:
            # 飞书算法：key = "timestamp\nsecret"，消息体为空
            ts = str(int(time.time()))
            string_to_sign = f"{ts}\n{secret}"
            code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
            payload["timestamp"] = ts
            payload["sign"] = base64.b64encode(code).decode("utf-8")
        return payload

    async def send(self, items: Sequence[Incoming], device: str = "") -> tuple[bool, str]:
        url = self.cfg.get("webhook", "").strip()
        if not url:
            return False, "未配置 webhook"
        content = f"{render_title(items, device)}\n\n{render_items(items, chr(10) + chr(10))}"
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post(url, json=self._payload(content))
        data = r.json() if r.content else {}
        code = data.get("code", data.get("StatusCode", 0))
        if code not in (0, None):
            return False, f"code={code} {data.get('msg', data.get('StatusMessage', r.text[:150]))}"
        return True, "ok"
