"""手机注册表：自动登记上报过的手机，支持编号与备注名。

识别逻辑（按优先级）：
  1. 上报数据里的 device 字段（APK 首次启动自动生成的设备 ID）
  2. 若为空，退回用来源 IP（同一 WiFi 下的多台手机会被算作一台，属已知限制）

首次出现的设备自动编号为「手机1」「手机2」…
备注名可在面板里改，改完以备注名显示。
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

log = logging.getLogger("smsf-hub.devices")


class DeviceRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._devices: dict = {}
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                self._devices = json.loads(self.path.read_text(encoding="utf-8"))
                log.info("已加载 %d 台手机记录", len(self._devices))
        except Exception:
            log.exception("读取手机注册表失败，从空开始")
            self._devices = {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._devices, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            log.exception("写入手机注册表失败")

    def _next_label(self) -> str:
        n = 1
        used = {d.get("label") for d in self._devices.values()}
        while f"手机{n}" in used:
            n += 1
        return f"手机{n}"

    def touch(self, device_value: str, source_ip: str = "") -> dict:
        """登记一次上报，返回该设备的记录。"""
        key = (device_value or "").strip()
        if not key:
            key = f"ip:{source_ip}" if source_ip else "unknown"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            rec = self._devices.get(key)
            if rec is None:
                rec = {
                    "key": key,
                    "label": self._next_label(),
                    "remark": "",
                    "first_seen": now,
                    "last_seen": now,
                    "count": 0,
                    "last_ip": source_ip,
                }
                self._devices[key] = rec
                log.info("发现新手机：%s (key=%s)", rec["label"], key[:24])
            rec["last_seen"] = now
            rec["count"] = int(rec.get("count", 0)) + 1
            if source_ip:
                rec["last_ip"] = source_ip
            self._save()
            return dict(rec)

    def rename(self, key: str, remark: str) -> bool:
        with self._lock:
            if key not in self._devices:
                return False
            self._devices[key]["remark"] = remark
            self._save()
            return True

    def remove(self, key: str) -> bool:
        with self._lock:
            if key not in self._devices:
                return False
            self._devices.pop(key)
            self._save()
            return True

    def all(self) -> list:
        rows = []
        for rec in self._devices.values():
            rows.append({
                "key": rec["key"],
                "label": rec["label"],
                "remark": rec.get("remark", ""),
                "display": rec.get("remark") or rec["label"],
                "first_seen": rec.get("first_seen", ""),
                "last_seen": rec.get("last_seen", ""),
                "count": rec.get("count", 0),
                "last_ip": rec.get("last_ip", ""),
            })
        rows.sort(key=lambda r: r["first_seen"])
        return rows

    def count(self) -> int:
        return len(self._devices)

    def online_count(self, within_seconds: int = 300) -> int:
        """最近 N 秒内有上报的算「在线」。"""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(seconds=within_seconds)
        n = 0
        for rec in self._devices.values():
            try:
                if datetime.strptime(rec.get("last_seen", ""), "%Y-%m-%d %H:%M:%S") >= cutoff:
                    n += 1
            except Exception:
                pass
        return n

    def name_for(self, device_value: str) -> str:
        """给一条消息取设备显示名。"""
        key = (device_value or "").strip()
        rec = self._devices.get(key)
        if rec:
            return rec.get("remark") or rec["label"]
        return device_value or "未登记"
