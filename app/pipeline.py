"""主流水线：接收 -> 去重 -> 归档 -> 合并 -> 分发。"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

from .archive import Archive
from .channels import build_channels, dispatch
from .dedup import Dedup
from .devices import DeviceRegistry
from .merge import Merger
from .models import Incoming

log = logging.getLogger("smsf-hub.pipeline")


class Pipeline:
    def __init__(self, cfg):
        self.cfg = cfg
        self.archive = Archive(
            root=cfg.archive_root(),
            subject_rules=cfg.get("archive.subject_rules", {}),
            file_max_mb=cfg.get("archive.file_max_mb", 5),
            total_max_mb=cfg.get("archive.total_max_mb", 512),
            warn_percent=cfg.get("archive.warn_percent", 80),
            content_max_chars=cfg.get("archive.content_max_chars", 4000),
        )
        self.dedup = Dedup(
            enable=cfg.get("dedup.enable", True),
            window_seconds=cfg.get("dedup.window_seconds", 60),
            max_entries=cfg.get("dedup.max_entries", 5000),
        )
        self.channels = build_channels(cfg)
        self.merger = Merger(
            enable=cfg.get("merge.enable", True),
            window_seconds=cfg.get("merge.window_seconds", 60),
            max_items=cfg.get("merge.max_items", 20),
            group_by=cfg.get("merge.group_by", "subject"),
            separator=cfg.get("merge.separator", chr(92) + "n---" + chr(92) + "n"),
            flush_cb=self._dispatch,
        )
        keep = int(cfg.get("panel.recent_keep", 500) or 500)
        self.recent = deque(maxlen=keep)
        rf = str(cfg.get("panel.recent_file", "./data/recent.jsonl"))
        self.recent_file = Path(rf) if os.path.isabs(rf) else (Path(cfg.path).parent / rf).resolve()
        self._recent_lock = threading.Lock()
        self._load_recent(keep)
        self._recent_lines = self._count_lines()

        df = str(cfg.get("panel.devices_file", "./app/data/devices.json"))
        self.devices = DeviceRegistry(Path(df) if os.path.isabs(df) else (Path(cfg.path).parent / df).resolve())
        self.stats = {
            "received": 0,
            "duplicates": 0,
            "archived": 0,
            "pushed_ok": 0,
            "pushed_fail": 0,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }

    # ---------- 最近消息落盘 ----------

    def _count_lines(self) -> int:
        try:
            with self.recent_file.open("r", encoding="utf-8") as f:
                return sum(1 for _ in f)
        except OSError:
            return 0

    def _load_recent(self, keep: int) -> None:
        """启动时把最近的消息读回内存，这样重启后面板列表不会空。"""
        try:
            if not self.recent_file.exists():
                return
            lines = self.recent_file.read_text(encoding="utf-8").splitlines()[-keep:]
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    self.recent.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            log.info("已从 %s 恢复最近 %d 条消息", self.recent_file.name, len(self.recent))
        except OSError:
            log.exception("读取最近消息文件失败")

    def _append_recent(self, record: dict) -> None:
        try:
            self.recent_file.parent.mkdir(parents=True, exist_ok=True)
            with self.recent_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + chr(10))
                self._recent_lines += 1
            # 文件太大就裁剪，只留最近 3 倍容量的条数
            limit = self.recent.maxlen * 3 if self.recent.maxlen else 1500
            if self._recent_lines > limit:
                all_lines = self.recent_file.read_text(encoding="utf-8").splitlines()
                self.recent_file.write_text(chr(10).join(all_lines[-limit:]) + chr(10), encoding="utf-8")
                self._recent_lines = limit
                log.info("最近消息文件已裁剪到 %d 条", limit)
        except OSError:
            log.exception("写入最近消息文件失败")

    # ---------- 入口 ----------

    async def handle(self, payload: dict, source_ip: str = "") -> dict:
        msg = Incoming.from_payload(payload)
        self.stats["received"] += 1

        # 登记手机（首次出现自动编号）
        try:
            rec = self.devices.touch(msg.device, source_ip)
            self.stats["devices"] = self.devices.count()
            msg.device = rec.get("remark") or rec["label"]
        except Exception:
            log.exception("手机登记失败")

        if self.dedup.seen(msg):
            self.stats["duplicates"] += 1
            log.info("重复消息已跳过: %s", msg.fingerprint()[:60])
            return {"status": "duplicate", "received": self.stats["received"]}

        if self.cfg.get("archive.enable", True):
            try:
                path = self.archive.append(msg)
                self.stats["archived"] += 1
            except Exception as exc:
                log.exception("归档失败")
                path = None
        else:
            path = None

        record = {
            "time": msg.when.strftime("%Y-%m-%d %H:%M:%S"),
            "type": msg.type,
            "sender": msg.sender,
            "app": msg.app,
            "content": (msg.content or "")[:300],
            "device": msg.device,
            "archived": bool(path),
        }
        self.recent.appendleft(record)
        self._append_recent(record)

        await self.merger.add(msg)
        return {
            "status": "ok",
            "received": self.stats["received"],
            "pending_merge": self.merger.pending(),
            "archived": bool(path),
        }

    # ---------- 合并窗口到点后的实际分发 ----------

    async def _dispatch(self, key: str, items) -> None:
        device = ""
        for m in items:
            if m.device:
                device = m.device
                break
        results = await dispatch(self.channels, items, device)
        for r in results:
            if r["ok"]:
                self.stats["pushed_ok"] += 1
            else:
                self.stats["pushed_fail"] += 1
        log.info("分发完成 key=%s 条数=%d 渠道=%d", key, len(items), len(results))

    async def shutdown(self) -> None:
        await self.merger.flush_all()

    # ---------- 面板用的汇总 ----------

    def overview(self) -> dict:
        return {
            "stats": dict(self.stats),
            "devices": {
                "total": self.devices.count(),
                "online": self.devices.online_count(300),
            },
            "archive": self.archive.stats(),
            "pending_merge": self.merger.pending(),
            "dedup_size": self.dedup.size(),
            "channels": [{"name": c.name, "display": c.display, "enabled": c.enabled} for c in self.channels],
            "merge": {
                "enable": self.merger.enable,
                "window_seconds": self.merger.window,
                "max_items": self.merger.max_items,
                "group_by": self.merger.group_by,
            },
        }
