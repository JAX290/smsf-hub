"""主流水线：接收 -> 去重 -> 归档 -> 合并 -> 分发。"""
from __future__ import annotations

import json
import logging
import os
import re
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

# ---- 心跳 ------------------------------------------------------------------
#  手机端每 10 分钟发一次「我还活着」，带上 App 版本 / 权限是否齐全 / 服务是否在跑。
#
#  为什么要这个：光看「最近有没有消息」判断不了死活 ——
#  手机安静一晚上（没短信没通知）和被系统杀了，在数据上长得一模一样。
#  心跳是主动信号，能把这俩区分开，面板上就能显示成绿/黄/红。
#
#  约定：心跳包用固定的 from 值标记（见手机端 HeartbeatWorker）。
#  这类包不进归档、不进消息流、不计入消息数，只更新设备状态。
HEARTBEAT_MARK = "__heartbeat__"


def is_heartbeat(msg: Incoming) -> bool:
    """这条上报是不是心跳包。"""
    return (msg.sender or "").strip() == HEARTBEAT_MARK \
        or (msg.app or "").strip() == HEARTBEAT_MARK


# 手机端把负载写成一行（见 HeartbeatWorker.buildPayload）：
#     HBT|版本名|版本号|sms=1,call=1,notify=1,location=1|working=1
#
# 为什么不直接发 JSON：WebhookUtils 会把 content 套进用户配置的模板里，
# 套完 JSON 结构就散了。用这种行格式即使被前后包了别的内容，也能正则捞出来。
HEARTBEAT_RE = re.compile(r"HBT\|([^|]*)\|([^|]*)\|([^|]*)\|working=(\d)")


def parse_heartbeat(content: str) -> dict:
    """把心跳负载解析成 update_heartbeat 要的 dict。解析不了就返回空。"""
    m = HEARTBEAT_RE.search(content or "")
    if not m:
        return {}
    ver, code, perms_s, working = m.group(1), m.group(2), m.group(3), m.group(4)
    perms = {}
    for item in (perms_s or "").split(","):
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        perms[k.strip()] = v.strip() == "1"
    try:
        code_i = int(code)
    except Exception:
        code_i = 0
    return {
        "version": ver.strip(),
        "code": code_i,
        "perms": perms,
        "working": working == "1",
    }

# ---- 手机端上报格式的兼容处理 ----------------------------------------------
# SmsForwarder 转发「应用通知」时，默认模板和短信几乎一样：
#   type 仍是 sms、应用包名塞在 sender 里、正文里带「UID：」行。
# 这样面板上的「类型筛选（通知）」永远筛不出东西、「应用」列也是空的。
# 这里按内容特征做一次纠正：含 UID 行的当通知，包名从发件人挪到应用名。
_NOTIFY_HINT = ("UID：", "UID:")
_TEL_RE = re.compile(r"^[\d+\-\s]{5,}$")


def classify_notify(mtype: str, sender: str, content: str):
    """返回纠正后的 (type, sender, app)。app 为空表示不用改。"""
    if mtype != "sms":
        return mtype, sender, ""
    text = content or ""
    if not any(h in text for h in _NOTIFY_HINT):
        return mtype, sender, ""          # 没有通知特征，就是普通短信
    s = (sender or "").strip()
    if s and not _TEL_RE.match(s):
        return "notify", "", s             # 包名/应用名 → 挪到 app
    return "notify", sender, ""


def fix_record(rec: dict) -> dict:
    """对历史记录做同样的纠正，供面板展示时使用（不改动磁盘上的原始数据）。"""
    mtype, sender, app = classify_notify(rec.get("type", ""), rec.get("sender", ""), rec.get("content", ""))
    if mtype == rec.get("type") and sender == rec.get("sender") and not app:
        return rec
    out = dict(rec)
    out["type"] = mtype
    out["sender"] = sender
    if app:
        out["app"] = app
    return out


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
            # 先把手机上报的原始设备值留一份：devices.touch 之后 device 会被换成
            # 用户可改的备注，而归档目录名需要的是稳定标识（设备 ID 不会变）。
            raw_device = msg.device
            _hb = is_heartbeat(msg)
            rec = self.devices.touch(raw_device, source_ip,
                                     kind="heartbeat" if _hb else "message")
            self.stats["devices"] = self.devices.count()
            msg.device = rec.get("remark") or rec["label"]
            msg.raw["_device_raw"] = raw_device

            # 【新增】心跳：更新设备状态后立即返回，不往下走归档/合并/分发
            if _hb:
                status = parse_heartbeat(payload.get("content") or "")
                if not status:
                    log.warning("心跳负载解析失败（设备 %s），按空状态处理", raw_device)
                self.devices.update_heartbeat(raw_device, status)
                self.stats["heartbeats"] = self.stats.get("heartbeats", 0) + 1
                log.info("收到心跳：设备=%s 版本=%s 权限=%s",
                         raw_device, status.get("version", "?"), status.get("perms", {}))
                return {"status": "heartbeat", "received": self.stats["received"]}
        except Exception:
            log.exception("手机登记失败")

        # 兼容手机端的通知上报格式（包名在 sender、正文带 UID 行）
        _t, _s, _a = classify_notify(msg.type, msg.sender, msg.content)
        msg.type, msg.sender = _t, _s
        if _a:
            msg.app = _a

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
            "content": (msg.content or "")[:2000],   # 面板要能展开看详情，留长一点
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
            if r.get("skipped"):
                continue          # 按转发规则跳过：不算成功、也不算失败
            if r["ok"]:
                self.stats["pushed_ok"] += 1
            else:
                self.stats["pushed_fail"] += 1
        log.info("分发完成 key=%s 条数=%d 终端=%d", key, len(items), len(results))

    def reload_channels(self) -> int:
        """面板改完渠道后热加载，不用重启服务。返回当前启用的终端数。"""
        self.channels = build_channels(self.cfg)
        log.info("渠道已重新加载，当前启用 %d 个终端", len(self.channels))
        return len(self.channels)

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
            "channels": [{"name": c.name, "display": c.title, "enabled": c.enabled,
                          "instance": c.inst_id} for c in self.channels],
            "merge": {
                "enable": self.merger.enable,
                "window_seconds": self.merger.window,
                "max_items": self.merger.max_items,
                "group_by": self.merger.group_by,
            },
        }
