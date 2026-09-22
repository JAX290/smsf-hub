"""合并窗口：短时间内的多条消息先攒着，一起推送。

目的：不刷屏、绕开渠道限流（如企业微信群机器人 20 条/分钟）、降低请求数。
参数都在 config.yaml 的 merge 段里。
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Awaitable, Callable

from .models import Incoming

log = logging.getLogger("smsf-hub.merge")


class Merger:
    def __init__(self, enable: bool, window_seconds: float, max_items: int,
                 group_by: str, separator: str,
                 flush_cb: Callable[[str, list], Awaitable[None]]):
        self.enable = bool(enable)
        self.window = float(window_seconds)
        self.max_items = max(1, int(max_items))
        self.group_by = group_by or "subject"
        self.separator = (separator or "\n---\n").replace("\\n", "\n")
        self.flush_cb = flush_cb

        self._buf = defaultdict(list)
        self._tasks = {}

    async def add(self, msg: Incoming) -> None:
        if not self.enable:
            await self.flush_cb("direct", [msg])
            return

        key = msg.merge_group(self.group_by)
        self._buf[key].append(msg)

        if len(self._buf[key]) >= self.max_items:
            await self._flush(key)
            return

        old = self._tasks.get(key)
        if old and not old.done():
            old.cancel()
        self._tasks[key] = asyncio.create_task(self._timer(key))

    async def _timer(self, key: str) -> None:
        try:
            await asyncio.sleep(self.window)
            await self._flush(key)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("合并窗口刷写出错: %s", key)

    async def _flush(self, key: str) -> None:
        items = self._buf.pop(key, [])
        task = self._tasks.pop(key, None)
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
        if items:
            await self.flush_cb(key, items)

    async def flush_all(self) -> None:
        for key in list(self._buf.keys()):
            await self._flush(key)

    def pending(self) -> int:
        return sum(len(v) for v in self._buf.values())
