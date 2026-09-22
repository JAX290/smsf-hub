"""企业微信：群机器人（webhook）+ 应用消息（corpid/secret）。"""
from __future__ import annotations

from typing import Sequence

import httpx

from ..models import Incoming
from .base import Channel, render_items, render_title


class WecomRobot(Channel):
    name = "wework_robot"
    display = "企业微信群机器人"

    async def send(self, items: Sequence[Incoming], device: str = "") -> tuple[bool, str]:
        url = self.cfg.get("webhook", "").strip()
        if not url:
            return False, "未配置 webhook"

        text = render_items(items, "\n\n")
        msgtype = self.cfg.get("msgtype", "markdown")
        if msgtype == "markdown":
            content = f"**{render_title(items, device)}**\n\n{text}"
            payload = {"msgtype": "markdown", "markdown": {"content": content}}
        else:
            content = f"{render_title(items, device)}\n\n{text}"
            body = {"content": content}
            mobiles = [m.strip() for m in str(self.cfg.get("at_mobiles", "")).split(",") if m.strip()]
            if self.cfg.get("at_all"):
                body["mentioned_list"] = ["@all"]
            elif mobiles:
                body["mentioned_mobile_list"] = mobiles
            payload = {"msgtype": "text", "text": body}

        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post(url, json=payload)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if data.get("errcode") not in (0, None):
            return False, f"errcode={data.get('errcode')} {data.get('errmsg', '')}"
        return True, "ok"


class WecomAgent(Channel):
    name = "wework_agent"
    display = "企业微信应用消息"

    def __init__(self, cfg, app_cfg):
        super().__init__(cfg, app_cfg)
        self._token = ""
        self._expires = 0.0

    async def _access_token(self, cli: httpx.AsyncClient) -> str:
        import time
        if self._token and time.time() < self._expires - 60:
            return self._token
        r = await cli.get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            params={"corpid": self.cfg.get("corp_id", ""), "corpsecret": self.cfg.get("secret", "")},
        )
        data = r.json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"获取 access_token 失败: {data.get('errcode')} {data.get('errmsg')}")
        self._token = data["access_token"]
        self._expires = time.time() + int(data.get("expires_in", 7200))
        return self._token

    async def send(self, items: Sequence[Incoming], device: str = "") -> tuple[bool, str]:
        if not self.cfg.get("corp_id") or not self.cfg.get("secret") or not self.cfg.get("agent_id"):
            return False, "corp_id / secret / agent_id 未配置完整"
        text = f"{render_title(items, device)}\n\n{render_items(items, chr(10) + chr(10))}"
        async with httpx.AsyncClient(timeout=15) as cli:
            try:
                token = await self._access_token(cli)
            except Exception as exc:
                return False, str(exc)
            payload = {
                "touser": self.cfg.get("to_user", "@all"),
                "msgtype": "text",
                "agentid": int(self.cfg.get("agent_id", 0) or 0),
                "text": {"content": text},
                "safe": 0,
            }
            r = await cli.post("https://qyapi.weixin.qq.com/cgi-bin/message/send",
                               params={"access_token": token}, json=payload)
        data = r.json()
        if data.get("errcode") != 0:
            return False, f"errcode={data.get('errcode')} {data.get('errmsg', '')}"
        return True, "ok"
