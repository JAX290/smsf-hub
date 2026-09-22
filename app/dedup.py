"""去重：同样内容短时间内只处理一次。"""
from __future__ import annotations

import hashlib
import time
from collections import OrderedDict


class Dedup:
    def __init__(self, enable: bool, window_seconds: float, max_entries: int):
        self.enable = bool(enable)
        self.window = float(window_seconds)
        self.max_entries = max(100, int(max_entries))
        self._seen: OrderedDict = OrderedDict()

    def seen(self, msg) -> bool:
        """返回 True 表示这条是重复的，应跳过。"""
        if not self.enable:
            return False
        key = hashlib.sha1(msg.fingerprint().encode("utf-8", "replace")).hexdigest()
        now = time.time()
        self._evict(now)
        last = self._seen.get(key)
        if last is not None and now - last < self.window:
            return True
        self._seen[key] = now
        self._seen.move_to_end(key)
        while len(self._seen) > self.max_entries:
            self._seen.popitem(last=False)
        return False

    def _evict(self, now: float) -> None:
        while self._seen:
            k, t = next(iter(self._seen.items()))
            if now - t > self.window:
                self._seen.popitem(last=False)
            else:
                break

    def size(self) -> int:
        return len(self._seen)
