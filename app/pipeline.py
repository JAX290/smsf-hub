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
from .classify import configure as configure_priority, classify as classify_tier
from .dedup import Dedup
from .devices import DeviceRegistry
from .merge import Merger
from .models import Incoming, parse_time_text

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


# ---- 摘要包（手机端攒一波再发）---------------------------------------------
#
# 为什么要攒：手机每发一条消息就要唤醒一次射频。实测某台手机一天 715 条消息
# = 715 次射频唤醒，其中 73% 是「重要」级别的真人消息、20% 是系统状态噪音。
# 攒成一批只发一次，能把唤醒次数压到 1/6 左右（见 README 的说明）。
#
# 约定：手机端把 N 条消息打成**一个 POST**，content 形如：
#     DIG|2
#     {"ts":1790697000000,"k":"notify","a":"com.tencent.mm","n":"微信","ti":"张三","c":"晚上吃饭吗"}
#     {"ts":1790697060000,"k":"notify","a":"com.mi.health","n":"","ti":"","c":"睡眠服务后台运行中"}
# 服务端在这里**拆回 N 条**，各自走正常的去重/分级/归档流程 ——
# 所以归档和面板的粒度完全不变，只是传输由 N 次变 1 次。
DIGEST_RE = re.compile(r"^\s*DIG\|(\d+)\s*$", re.M)


def parse_digest(content: str) -> list:
    """把摘要包拆成条目列表；不是摘要包就返回空列表。"""
    text = content or ""
    if "DIG|" not in text:
        return []
    m = DIGEST_RE.search(text)
    if not m:
        return []
    items = []
    for line in text[m.end():].splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            items.append(obj)
    return items


def digest_config(cfg) -> dict:
    """手机端摘要窗口的配置。挂在心跳响应里下发，手机端会自动应用 ——
    这样面板改完就能生效，不用重新编译 APK。"""
    def _int(key, default):
        try:
            return int(cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    return {
        "enable": bool(cfg.get("digest.enable", True)),
        "near_minutes": _int("digest.near_minutes", 15),
        "daily_hours": _int("digest.daily_hours", 24),
        "instant_apps": str(cfg.get("digest.instant_apps", "") or ""),
        "instant_keywords": str(cfg.get("digest.instant_keywords", "") or ""),
        "max_items": _int("digest.max_items", 200),
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


def _tier_of(rec: dict) -> tuple[int, str]:
    """给一条「落盘时还没有分级」的历史记录补算层级。"""
    tmp = Incoming(
        type=str(rec.get("type") or ""),
        sender=str(rec.get("sender") or ""),
        app=str(rec.get("app") or ""),
        content=str(rec.get("content") or ""),
        device=str(rec.get("device") or ""),
        ts=0,
    )
    return classify_tier(tmp)


def _recv_ms(rec: dict) -> int:
    """从正文里抠出手机端渲染的 receive_time（真正的「收到时刻」）。"""
    for ln in (rec.get("content") or "").splitlines():
        s = ln.strip()
        if len(s) == 19 and s[4] == "-" and s[13] == ":":
            ms = parse_time_text(s)
            if ms:
                return ms
    return 0


def fix_record(rec: dict) -> dict:
    """对历史记录做同样的纠正，供面板展示时使用（不改动磁盘上的原始数据）。

    做三件事：
      1. 纠正手机端「通知被当成短信上报」的老格式（见 classify_notify）
      2. 给 2026-10-07 之前落盘、没有 tier 字段的老记录补算分级
      3. **把显示时间改回「收到时刻」** —— 老记录落盘时用的是「上报时刻」，
         而手机离线补发时上报会晚好几小时，于是面板上会出现
         「11 点收到的消息 14 点才弹出来」。正文里的 receive_time 才是准的。
    """
    mtype, sender, app = classify_notify(rec.get("type", ""), rec.get("sender", ""), rec.get("content", ""))
    changed = (mtype != rec.get("type")) or (sender != rec.get("sender")) or bool(app)
    need_tier = rec.get("tier") in (None, "", -1, "-1")

    recv_ms = _recv_ms(rec)
    shown_ms = parse_time_text(rec.get("time", "")) if recv_ms else 0
    need_time = bool(recv_ms and shown_ms and abs(shown_ms - recv_ms) > 120_000)

    if not (changed or need_tier or need_time):
        return rec

    out = dict(rec)
    if changed:
        out["type"] = mtype
        out["sender"] = sender
        if app:
            out["app"] = app
    if need_tier:
        tier, reason = _tier_of(out)
        out["tier"] = tier
        out["tier_reason"] = reason
    if need_time:
        out["upload_time"] = rec.get("time")
        out["delay_sec"] = int((shown_ms - recv_ms) / 1000)
        out["time"] = datetime.fromtimestamp(recv_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
    return out


class Pipeline:
    def __init__(self, cfg):
        self.cfg = cfg
        # 消息分级规则（降噪核心）：从 config.yaml 的 priority: 段读
        configure_priority(cfg)
        self.archive = Archive(
            root=cfg.archive_root(),
            subject_rules=cfg.get("archive.subject_rules", {}),
            file_max_mb=cfg.get("archive.file_max_mb", 5),
            total_max_mb=cfg.get("archive.total_max_mb", 512),
            warn_percent=cfg.get("archive.warn_percent", 80),
            content_max_chars=cfg.get("archive.content_max_chars", 4000),
            warn_free_gb=cfg.get("archive.warn_free_gb", 2.0),
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
        keep = int(cfg.get("panel.recent_keep", 8000) or 8000)
        self.recent = deque(maxlen=keep)
        # 落盘文件保留多少条。比内存大得多：面板翻不够时可从这里继续读，
        # 重启后也能把历史读回内存。默认 20 万条（约 60MB）。
        self.recent_file_keep = int(cfg.get("panel.recent_file_keep", 200000) or 200000)
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
            # 文件太大就裁剪，只留最近 recent_file_keep 条
            limit = self.recent_file_keep or 200000
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
                # 顺带把「摘要窗口」配置下发下去：手机端收到后自动应用，
                # 所以面板上改完就能生效，不用重新编译 APK。
                return {"status": "heartbeat", "received": self.stats["received"],
                        "digest": digest_config(self.cfg)}
        except Exception:
            log.exception("手机登记失败")

        # 【摘要包】手机端攒了一批消息只发一次，这里拆回 N 条各自走正常流程。
        # 注意要放在去重/归档之前 —— 拆开之后每条才会按自己的内容去重和判级。
        digest_items = parse_digest(msg.content)
        if digest_items:
            done = 0
            for it in digest_items:
                sub = dict(payload)
                sub["type"] = str(it.get("k") or "notify")
                sub["from"] = str(it.get("a") or "")
                sub["app"] = str(it.get("n") or "")
                sub["title"] = str(it.get("ti") or "")
                sub["content"] = str(it.get("c") or "")
                if it.get("ts"):
                    sub["ts"] = str(it["ts"])
                    # 摘要包里每条都有自己的「收到时刻」，必须一并带上 ——
                    # 否则会被当成"整包发送的时刻"，时间又错回去了。
                    try:
                        sub["receive_time"] = datetime.fromtimestamp(
                            int(it["ts"]) / 1000).strftime("%Y-%m-%d %H:%M:%S")
                    except (TypeError, ValueError, OSError):
                        pass
                try:
                    await self.handle(sub, source_ip)
                    done += 1
                except Exception:
                    log.exception("摘要包里的条目处理失败")
            log.info("收到摘要包：设备=%s 共 %d 条", raw_device, done)
            return {"status": "digest", "items": done, "received": self.stats["received"]}

        # 兼容手机端的通知上报格式（包名在 sender、正文带 UID 行）
        _t, _s, _a = classify_notify(msg.type, msg.sender, msg.content)
        msg.type, msg.sender = _t, _s
        if _a:
            msg.app = _a

        # 消息分级（降噪核心）：归档与面板都要用，所以在归档之前先算好
        msg.tier, msg.tier_reason = classify_tier(msg)

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
            "tier": msg.tier,
            "tier_reason": msg.tier_reason,
        }
        # 上报延迟：收到 → 送达差了多少秒。超过 2 分钟才记，
        # 面板上会标出来 —— 手机端积压（夜间被系统限制后台）时一眼能看出来。
        try:
            delay = int((datetime.now() - msg.when).total_seconds())
        except (TypeError, ValueError, OSError):
            delay = 0
        if delay > 120:
            record["delay_sec"] = delay
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

    def reload_priority(self) -> dict:
        """面板改完分级规则后热加载（重新读配置文件，不用重启服务）。"""
        p = None
        try:
            from .config import load_config
            fresh = load_config(str(self.cfg.path))
            p = configure_priority(fresh)
        except Exception:
            log.exception("重新读取配置失败，沿用内存里的分级规则")
            p = configure_priority(self.cfg)
        log.info("分级规则已重新加载：重要应用 %d 条 / 噪音应用 %d 条 / "
                 "重要关键词 %d 条 / 噪音关键词 %d 条 / 推送门槛 T%d",
                 len(p.important_apps), len(p.noise_apps),
                 len(p.important_keywords), len(p.noise_keywords), p.min_push_tier)
        return {
            "important_apps": len(p.important_apps),
            "noise_apps": len(p.noise_apps),
            "min_push_tier": p.min_push_tier,
        }

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
