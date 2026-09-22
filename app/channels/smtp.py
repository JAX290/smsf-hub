"""邮件推送。"""
from __future__ import annotations

import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Sequence

from ..models import Incoming
from .base import Channel, render_items, render_title


class SmtpMail(Channel):
    name = "smtp"
    display = "邮件 (SMTP)"

    def _send_sync(self, subject: str, body: str) -> None:
        host = self.cfg.get("host", "").strip()
        port = int(self.cfg.get("port", 465) or 465)
        user = self.cfg.get("username", "").strip()
        pwd = self.cfg.get("password", "")
        sender = self.cfg.get("mail_from", "").strip() or user
        to = [a.strip() for a in str(self.cfg.get("mail_to", "")).split(",") if a.strip()]
        if not host or not to:
            raise RuntimeError("未配置 host / mail_to")

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = formataddr(("SmsForwarder Hub", sender))
        msg["To"] = ", ".join(to)

        if self.cfg.get("ssl", True):
            with smtplib.SMTP_SSL(host, port, timeout=20) as s:
                if user:
                    s.login(user, pwd)
                s.sendmail(sender, to, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.ehlo()
                try:
                    s.starttls()
                    s.ehlo()
                except smtplib.SMTPException:
                    pass
                if user:
                    s.login(user, pwd)
                s.sendmail(sender, to, msg.as_string())

    async def send(self, items: Sequence[Incoming], device: str = "") -> tuple[bool, str]:
        import asyncio
        prefix = self.cfg.get("subject_prefix", "[短信转发]")
        subject = f"{prefix} {render_title(items, device)}"
        body = render_items(items, chr(10) + chr(10))
        try:
            await asyncio.to_thread(self._send_sync, subject, body)
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        return True, "ok"
